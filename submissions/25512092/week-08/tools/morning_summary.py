"""11/08 08:00: one Telegram with the night's summary (person's decision 11/07 ~20:20), read-only:
  urgent alerts, buyer poster fallback switches, refused receipts, injection handling, automatic policy changes,
  analyst proposals (window NIGHT_FROM -> AT), and LLM calls per agent for the last 24 h:
    seller   one '[seller] [harness]' line per call (newest kit-console-*.txt)
    buyer    one '[buyer] ... harness:' line per call (logs/market-kit.log)
    analyst  analyst_meta calls:<day> (per calendar day, analyst_brain.call_llm)
    forum    forum_meta flow:<day> (one call per day, forum_watch.flow)
    python tools/morning_summary.py [--dry]      (waits until AT; --dry: the last 12 h now, printed, not sent)
"""
import glob
import json
import os
import sqlite3
import sys
import time
from collections import Counter
from datetime import datetime

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "tools"))
os.chdir(HERE)

AT = datetime(2026, 11, 8, 8, 0).timestamp()
NIGHT_H = 12


def decisions_in(t0, t1, actions):
    out = []
    with open(os.path.join(HERE, "logs", "decisions.jsonl"), encoding="utf-8") as f:
        for ln in f:
            if any(f'"action": "{a}"' in ln for a in actions):
                d = json.loads(ln)
                if t0 <= d["ts"] < t1:
                    out.append(d)
    return out


def llm_calls(t0, t1):
    from strict_mcp_rollout import timed_lines
    con = sorted(glob.glob(os.path.join(HERE, "logs", "kit-console-*.txt")), key=os.path.getmtime)[-1]
    seller = len(timed_lines(con, "[seller] [harness] ", t0, t1, tail_bytes=400_000_000))
    buyer = 0                                       # the kit rotates market-kit.log at 20 MB into market-kit.log.1
    for name in ("market-kit.log.1", "market-kit.log"):
        p = os.path.join(HERE, "logs", name)
        if os.path.exists(p):
            buyer += sum(1 for _, ln in timed_lines(p, "[buyer]", t0, t1, tail_bytes=400_000_000) if " harness: " in ln)
    db = sqlite3.connect(os.path.join(HERE, "market.db"), timeout=30)
    try:
        days = sorted({datetime.fromtimestamp(t0).strftime("%Y%m%d"), datetime.fromtimestamp(t1 - 1).strftime("%Y%m%d")})
        analyst = {d: int((db.execute("SELECT v FROM analyst_meta WHERE k=?", (f"calls:{d}",)).fetchone() or [0])[0])
                   for d in days}
        flows = [r[0] for r in db.execute("SELECT k FROM forum_meta WHERE k LIKE 'flow:%'")]
    finally:
        db.close()
    forum = sum(1 for k in flows if k.split(":")[1] in days)
    return {"seller": seller, "buyer": buyer, "analyst_by_day": analyst, "forum_summary_days": forum}


def summary(t0, t1):
    lines = [f"밤사이 요약 {datetime.fromtimestamp(t0):%m-%d %H:%M} ~ {datetime.fromtimestamp(t1):%m-%d %H:%M}"]
    urgent = []
    with open(os.path.join(HERE, "logs", "alerts.jsonl"), encoding="utf-8") as f:
        for ln in f:
            a = json.loads(ln)
            if a.get("level") == "urgent" and t0 <= a["ts"] < t1:
                urgent.append(a)
    c = Counter(a["key"].split(":")[0] for a in urgent)
    lines.append(f"1. 긴급 알림 {len(urgent)}건" + (": " + ", ".join(f"{k} {n}" for k, n in c.most_common(8)) if urgent else ""))
    sw = decisions_in(t0, t1, ["buyer_poster_mode"])
    lines.append(f"2. 폴백 전환 {len(sw)}건" + (": " + ", ".join(f"{datetime.fromtimestamp(d['ts']):%H:%M} {d['value']}"
                                                          for d in sw[:6]) if sw else ""))
    ref = decisions_in(t0, t1, ["receipt_refused"])
    lines.append(f"3. 영수증 거절 {len(ref)}건, {sum(int(d.get('value') or 0) for d in ref):,}원"
                 + (": " + ", ".join(Counter((d.get("reason") or "").split(":")[0] for d in ref).keys()) if ref else ""))
    db = sqlite3.connect(os.path.join(HERE, "market.db"), timeout=30)
    try:
        inj = db.execute("SELECT outcome, COUNT(*) FROM buyer_deals WHERE buyer_case='injection_code' AND ts>=? AND ts<? "
                         "GROUP BY outcome", (t0, t1)).fetchall()
        changes = db.execute("SELECT id, ts, key, value, status, result FROM proposals WHERE kind='policy_change' AND "
                             "ts>=? AND ts<? ORDER BY ts", (t0, t1)).fetchall()
        props = db.execute("SELECT id, ts, key, value, status FROM proposals WHERE kind IN ('policy','limit') AND "
                           "ts>=? AND ts<? ORDER BY ts", (t0, t1)).fetchall()
    finally:
        db.close()
    no_avg = decisions_in(t0, t1, ["injection_no_avg"])
    lines.append(f"4. 인젝션 코드 협상 {sum(n for _, n in inj)}건 {dict(inj)}, 그중 시장 평균 없어 바로 walk {len(no_avg)}건")
    lines.append(f"5. 자동 정책 변경 {len(changes)}건")
    for i, ts, key, value, status, result in changes[:8]:
        v = json.loads(value)
        ch = "; ".join(f"{c['where']}: {c['old']} -> {c['new']}" for c in v.get("changes", []))
        lines.append(f"   #{i} {datetime.fromtimestamp(ts):%H:%M} {v.get('source')}: {ch}"
                     + (f" ({'버튼 ' + ', '.join(json.loads(result).keys())})" if (result or "").startswith("{") else ""))
    lines.append(f"6. 분석관 제안 {len(props)}건")
    for i, ts, key, value, status in props[:8]:
        lines.append(f"   #{i} {datetime.fromtimestamp(ts):%H:%M} {key} -> {json.loads(value)} [{status}]")
    llm = llm_calls(t1 - 86400, t1)
    lines.append(f"7. LLM 호출 (최근 24시간): seller {llm['seller']:,}, buyer {llm['buyer']:,}, 분석관 "
                 + ", ".join(f"{d[4:6]}/{d[6:]} {n}" for d, n in llm["analyst_by_day"].items())
                 + f", 포럼 요약 {llm['forum_summary_days']}회 (모두 haiku)")
    return "\n".join(lines)


def main():
    if "--dry" in sys.argv:
        now = time.time()
        print(summary(now - NIGHT_H * 3600, now))
        return
    while time.time() < AT:
        time.sleep(min(60, max(1, AT - time.time())))
    import alerts
    alerts.send("daily", "morning_summary:20261108", summary(AT - NIGHT_H * 3600, AT))


if __name__ == "__main__":
    main()
