"""Buyer accept rule (depts/accept_rule.py), 24 h experiment (person's decision 11/08 ~14:10): switches it on, checks
the board every CHECK_S and switches it off at once (urgent Telegram) when my buyer's saved falls under SAVED_MIN or
its lead over the second best saved is <= LEAD_MIN; after 24 h (or the stop) switches it off and reports:
accepts (logs/accept_rule.jsonl), deals among them, paid (a settle of that SKU at that price by my buyer within 20
min), price / item / budget mismatches (judge flags), deals / surplus / saved / ranks on the board, start vs end.
    python tools/accept_watch.py            (log in logs/accept_watch.log)
"""
import json
import os
import sqlite3
import sys
import time
from collections import Counter
from datetime import datetime

import httpx

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
os.chdir(HERE)
from depts import accept_rule  # noqa: E402

ME = "choo-chu"
CHECK_S = 1800
SAVED_MIN = 0.395
LEAD_MIN = 0.02
LOG = os.path.join(HERE, "logs", "accept_watch.log")


def log(m):
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(f"{datetime.now():%m-%d %H:%M:%S} {m}\n")


def board():
    j = httpx.get("https://market.ourolabs.ai/api/board", params={"round": 3}, timeout=30).json()
    B = [b for b in j["buyers"] if b.get("all") is not None]
    me = next(b for b in B if b["name"] == ME)
    second = max(b["saved"] for b in B if b is not me)
    return {"saved": me["saved"], "deals": me["deals"], "surplus": me["surplus"], "all": me["all"], "second": second,
            "saved_rank": 1 + sum(1 for b in B if b["saved"] > me["saved"]),
            "all_rank": 1 + sum(1 for b in B if b["all"] > me["all"])}


def set_rule(**kw):
    r = accept_rule.rules()
    r.update(kw)
    with open(accept_rule.RULES, "w", encoding="utf-8") as f:
        json.dump(r, f)


def accepts(t0):
    out = []
    try:
        with open(accept_rule.LOG, encoding="utf-8") as f:
            for ln in f:
                e = json.loads(ln)
                if e["ts"] >= t0:
                    out.append(e)
    except OSError:
        pass
    return out


def report(t0, b0, b1, stopped=None):
    A = accepts(t0)
    deals = [a for a in A if a["deal"]]
    db = sqlite3.connect(os.path.join(HERE, "market.db"), timeout=60)
    try:
        paid = [a for a in deals if db.execute("SELECT 1 FROM settles WHERE buyer=? AND sku=? AND amount=? AND ts BETWEEN ? AND ?",
                                              (ME, a["sku"], a["receipt_price"] or a["price"], a["ts"] - 60, a["ts"] + 1200)).fetchone()]
    finally:
        db.close()
    flags = Counter(a.get("flag") for a in deals if a.get("flag") not in (None, "ok", "good", "fine"))
    mism = {k: v for k, v in flags.items() if k in ("receipt_mismatch", "item_mismatch", "over_budget", "no_receipt", "grade")}
    kit = Counter()                                  # the kit's refusals at checkout (grade, shelf life, ...)
    try:
        want = {(a["sku"], int(a["receipt_price"] or a["price"])) for a in deals if a not in paid}
        with open(os.path.join(HERE, ".market", "payments.jsonl"), encoding="utf-8") as f:
            for ln in f:
                p = json.loads(ln) if ln.strip() else {}
                if not p.get("paid") and (p.get("item"), int(float(p.get("price") or 0))) in want:
                    kit[(p.get("reason") or "?")[:40]] += 1
    except (OSError, ValueError):
        pass
    surplus_add = sum((a.get("list_price") or 0) - (a["receipt_price"] or a["price"]) for a in paid)
    return "\n".join([
        f"buyer 수락 규칙(accept_rule_95) {'중단' if stopped else '24시간'} 결과 ({datetime.fromtimestamp(t0):%m-%d %H:%M} ~ {datetime.now():%m-%d %H:%M})"
        + (f": {stopped}" if stopped else ""),
        f"- 규칙으로 수락 {len(A)}건 (walk 대신 {sum(a['instead_of'] == 'walk' for a in A)}, 시간 한도 {sum(a['instead_of'] == 'time_limit' for a in A)}, "
        f"턴 한도 {sum(a['instead_of'] == 'turn_limit' for a in A)}), 그중 성사 {len(deals)}, 결제 {len(paid)} "
        f"({(len(paid) / len(deals)) if deals else 0:.0%})",
        f"- 등급·품목·가격 불일치(우리 buyer 판정) {sum(mism.values())}건 {dict(mism) if mism else ''}; 그 밖의 판정 {dict(flags) if flags else '-'}",
        f"- kit 결제 거절 사유(등급·유통기한 등): {dict(kit) if kit else '없음'}",
        f"- 결제된 수락 건의 정가 대비 절약 합 {surplus_add:,}",
        f"- 보드: deals {b0['deals']} -> {b1['deals']}, surplus {b0['surplus']:,} -> {b1['surplus']:,}, saved {b0['saved']} -> {b1['saved']} "
        f"(2위 {b0['second']} -> {b1['second']}), saved 순위 {b0['saved_rank']} -> {b1['saved_rank']}, ALL {b0['all']} ({b0['all_rank']}위) -> "
        f"{b1['all']} ({b1['all_rank']}위)"])


def main():
    import alerts
    import decisions
    t0 = time.time()
    b0 = board()
    set_rule(enabled=True, since=round(t0), until=round(t0 + 86400), low=accept_rule.LOW, high=accept_rule.HIGH)
    decisions.record("buyer", "accept_rule_on", "accept_rule", b0,
                     "person 11/08 ~14:10: 24 h; walk / time / turn limit -> accept the last ask at 50-95% of the market average "
                     "within the cap; stop at saved < 0.395 or lead <= 0.02")
    alerts.send("info", "accept_rule_on", f"buyer 수락 규칙 24시간 실험 시작 {datetime.now():%H:%M}: walk·시간·턴 한도 대신, 마지막 호가가 시장 평균의 "
                f"50~95%이고 예산 안이면 수락 (코드, LLM 없음). 시작 saved {b0['saved']} (2위 {b0['second']}). 30분마다 확인, "
                f"saved < {SAVED_MIN} 또는 2위와 차이 <= {LEAD_MIN}이면 즉시 끔", log=log)
    log(f"on, board {b0}")
    stopped = None
    while time.time() < t0 + 86400:
        time.sleep(min(CHECK_S, max(5, t0 + 86400 - time.time())))
        try:
            b = board()
        except Exception as e:
            log(f"board failed: {type(e).__name__}")
            continue
        log(f"check {b}")
        why = (f"saved {b['saved']} < {SAVED_MIN}" if b["saved"] < SAVED_MIN else
               f"2위와 차이 {b['saved'] - b['second']:.4f} <= {LEAD_MIN}" if b["saved"] - b["second"] <= LEAD_MIN else None)
        if why:
            stopped = why
            set_rule(enabled=False, stopped=round(time.time()), stop_reason=why)
            decisions.record("buyer", "accept_rule_stop", "accept_rule", b, why)
            alerts.send("urgent", "accept_rule_stop", f"buyer 수락 규칙 즉시 중단: {why}\n" + report(t0, b0, b), log=log)
            log(f"stopped: {why}")
            return
    set_rule(enabled=False, ended=round(time.time()))
    b1 = board()
    decisions.record("buyer", "accept_rule_end", "accept_rule", b1, "24 h done, rule off; keep it or not is the person's decision")
    alerts.send("daily", f"accept_rule_report:{int(t0)}", report(t0, b0, b1) + "\n24시간 끝: 규칙 꺼짐. 계속할지는 사람 결정", log=log)
    log("report sent")


if __name__ == "__main__":
    main()
