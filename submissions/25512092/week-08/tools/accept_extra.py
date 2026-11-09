"""Addendum to the buyer accept-rule 24 h report (person's request 11/09 ~11:20): right after tools/accept_watch.py
sends its report ("report sent" or "stopped" in logs/accept_watch.log; that process was started before this request,
so its own report is unchanged), one more Telegram: deals, surplus, served at the start vs now, and my rank on
each among the buyers with a deal, next to the 1st and 10th value.
Start values: deals / surplus from the "on, board" line of logs/accept_watch.log (11/08 14:13:45); served was not
recorded there, so it comes from market.db board_hist (my buyer row, the last snapshot before the start).
served (board): deals whose goods were worth their list price to the order (agent.md "a deal that served
nothing": food that did not last use_within_hours, goods that broke) - inferred, agent.md names no column.
    python tools/accept_extra.py [--dry]          (log in logs/accept_watch.log)
"""
import ast
import json
import os
import sqlite3
import sys
import time
from datetime import datetime

import httpx

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
os.chdir(HERE)
ME = "choo-chu"
LOG = os.path.join(HERE, "logs", "accept_watch.log")
COLS = ("saved", "deals", "surplus", "served")


def log(m):
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(f"{datetime.now():%m-%d %H:%M:%S} [extra] {m}\n")


def start():
    with open(LOG, encoding="utf-8") as f:
        for ln in f:
            if " on, board " in ln:
                t = datetime.strptime("2026-" + ln[:14], "%Y-%m-%d %H:%M:%S").timestamp()
                b = ast.literal_eval(ln.split(" on, board ", 1)[1].strip())
                break
    db = sqlite3.connect(os.path.join(HERE, "market.db"), timeout=60)
    try:
        ts, row = db.execute("SELECT ts, buyer FROM board_hist WHERE ts<=? ORDER BY ts DESC LIMIT 1", (t,)).fetchone()
    finally:
        db.close()
    snap = json.loads(row)
    return t, b, snap, ts


def done():
    with open(LOG, encoding="utf-8") as f:
        return any(("report sent" in ln and "[extra]" not in ln) or "stopped:" in ln for ln in f)


def text():
    t, b0, snap, sts = start()
    B = [b for b in httpx.get("https://market.ourolabs.ai/api/board", params={"round": 3}, timeout=30).json()["buyers"]
         if (b.get("deals") or 0) > 0]
    me = next(b for b in B if b["name"] == ME)
    s0 = {"saved": b0["saved"], "deals": b0["deals"], "surplus": b0["surplus"], "served": snap["served"]}
    lines = [f"buyer 수락 규칙 결과 보충 ({datetime.fromtimestamp(t):%m-%d %H:%M} 시작 vs {datetime.now():%m-%d %H:%M}, "
             f"deal 있는 buyer {len(B)}명 중)"]
    for k in COLS:
        vals = sorted((b.get(k) or 0 for b in B), reverse=True)
        rank = 1 + sum(1 for v in vals if v > me[k])
        fmt = (lambda v: f"{v:.4f}") if k == "saved" else (lambda v: f"{int(v):,}")
        d = me[k] - s0[k]
        lines.append(f"- {k}: {fmt(s0[k])} -> {fmt(me[k])} ({'+' if d >= 0 else ''}{fmt(d)}), 지금 {rank}위 "
                     f"(1위 {fmt(vals[0])}, 10위 {fmt(vals[min(9, len(vals) - 1)])})")
    lines.append(f"- served/deals: {s0['served'] / s0['deals']:.1%} -> {me['served'] / me['deals']:.1%} "
                 f"(시작 served는 {datetime.fromtimestamp(sts):%H:%M} 스냅샷, deals {snap['deals']} 기준)")
    lines.append(f"- ALL {b0['all']} ({b0['all_rank']}위) -> {me['all']} ({1 + sum(1 for b in B if b['all'] > me['all'])}위); "
                 "시작 시점의 다른 buyer 값은 기록이 없어 시작 순위는 saved·ALL만 있음")
    return "\n".join(lines)


def main():
    if "--dry" in sys.argv:
        print(text())
        return
    import alerts
    log("waiting for the accept-rule report")
    while not done():
        time.sleep(30)
    time.sleep(30)
    alerts.send("daily", "accept_rule_extra", text(), log=log)
    log("report sent (extra)")


if __name__ == "__main__":
    main()
