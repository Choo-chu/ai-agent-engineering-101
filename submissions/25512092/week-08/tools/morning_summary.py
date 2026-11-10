"""11/08 08:00: one Telegram with the night's summary (person's decision 11/07 ~20:20), read-only:
  urgent alerts, buyer poster fallback switches, refused receipts, injection handling, automatic policy changes,
  analyst proposals (window NIGHT_FROM -> AT), and LLM calls per agent for the last 24 h:
    seller   one '[seller] [harness]' line per call (newest kit-console-*.txt)
    buyer    one '[buyer] ... harness:' line per call (logs/market-kit.log)
    analyst  analyst_meta calls:<day> (per calendar day, analyst_brain.call_llm)
    forum    forum_meta flow:<day> (one call per day, forum_watch.flow)
  12. (from 11/10 ~12:10, person) stock unsold over 12 h (cost and units, high-price / other) and storage paid
      (the 5-min cash table's storage_per_day over time), 12 h and since the round start; --daily sends at 08:00
      and 20:00 from then (the 12 h before each)
  9. (from 11/10) 우아미 소파 G5e3784e6 in the live buy_exclude.json, one line
    python tools/morning_summary.py [--dry | --daily]   (waits until AT; --dry: the last 12 h now, printed, not sent;
                                                         --daily: every day at 08:00 until the round end)
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
if "--at" in sys.argv:                            # e.g. --at 2026-11-09T08:00 (the 11/09 summary, with 8. below)
    AT = datetime.fromisoformat(sys.argv[sys.argv.index("--at") + 1]).timestamp()
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
    if t1 >= datetime(2026, 11, 9).timestamp():   # 11/08 ~11:20 (person): from the 11/09 summary
        from depts import review_link
        try:
            lines.append("8. " + review_link.line(review_link.high_sofa_reasons(t1 - 86400, t1)) + " (최근 24시간)")
        except Exception as e:
            lines.append(f"8. 고가·소파 취소 사유: 계산 실패 {type(e).__name__}")
    if t1 >= datetime(2026, 11, 10).timestamp():  # 11/09 ~19:45 (person): from the 11/10 summary
        lines.append("9. " + exclude_line())
    try:                                          # 11/09 ~23:40 (person): the high-price cost exclusion list
        from depts import high_cost_exclude
        lines.append("11. " + high_cost_exclude.line())
    except Exception as e:
        lines.append(f"11. 고가 매입 제외 목록 읽기 실패 {type(e).__name__}")
    try:                                          # 11/09 ~21:30 (person): the shop_order 6 h check, once it is due
        from depts import shop_order
        t_on = shop_order.rules().get("since")
        if t_on and t1 >= t_on + 6 * 3600 and t1 - t_on <= 36 * 3600:
            import shop_order_check
            lines.append("10. " + shop_order_check.report(t_on, t_on + 6 * 3600))
    except Exception as e:
        lines.append(f"10. 가게 순서 6시간 점검 실패 {type(e).__name__}")
    try:                                          # 11/10 ~12:10 (person): the brakes only warn, the person judges
        lines.append("12. " + stock_line(t1))
    except Exception as e:
        lines.append(f"12. 12시간+ 미판매 재고·보관비 계산 실패 {type(e).__name__}")
    return "\n".join(lines)


STALE_H = 12


def storage_paid(db, t0, t1):
    """Storage paid in [t0, t1): storage_per_day of each 5-min cash snapshot times the time to the next one."""
    rows = db.execute("SELECT ts, storage_per_day FROM cash WHERE ts>=? AND ts<? ORDER BY ts", (t0, t1)).fetchall()
    return round(sum((b[0] - a[0]) * (a[1] or 0) for a, b in zip(rows, rows[1:])) / 86400)


def stock_line(t1, inv_path=None, db_path=None):
    """Held units (live .market/inventory.json) supplied over STALE_H before t1: cost and count, high-price
    (cost > qc.HIGH_MIN) and other; storage paid in the last 12 h and since the first cash snapshot."""
    from depts.qc import HIGH_MIN
    with open(inv_path or os.path.join(HERE, ".market", "inventory.json"), encoding="utf-8") as f:
        inv = json.load(f)
    old = [u for u in inv.get("units", []) if u.get("grade") != "expired" and u.get("supplied_at")
           and u["supplied_at"] <= t1 - STALE_H * 3600]
    hi = [u for u in old if (u.get("cost") or 0) > HIGH_MIN]
    lo = [u for u in old if (u.get("cost") or 0) <= HIGH_MIN]
    c = lambda us: sum(u.get("cost") or 0 for u in us)
    db = sqlite3.connect(db_path or os.path.join(HERE, "market.db"), timeout=30)
    try:
        s12, sall = storage_paid(db, t1 - 12 * 3600, t1), storage_paid(db, 0, t1)
        per_day = (db.execute("SELECT storage_per_day FROM cash WHERE ts<? ORDER BY ts DESC LIMIT 1", (t1,)).fetchone()
                   or [0])[0]
    finally:
        db.close()
    return (f"12시간 넘게 안 팔린 재고: 원가 {c(old):,} {len(old)}개 (고가 {c(hi):,} {len(hi)}개 / 일반 {c(lo):,} {len(lo)}개); "
            f"보관비 누적 {sall:,} (최근 12시간 {s12:,}, 지금 하루 {per_day or 0:,})")


WATCH_SKU = "G5e3784e6"                           # 우아미 소파, never bought again (person 11/09 ~11:10)


def exclude_line():
    """One line: is WATCH_SKU in the live buy_exclude.json (read by depts/purchasing.excluded every restock run)?"""
    try:
        with open(os.path.join(HERE, "buy_exclude.json"), encoding="utf-8") as f:
            skus = json.load(f).get("skus") or {}
    except (OSError, ValueError, AttributeError) as e:
        return f"매입 제외 목록(buy_exclude.json) 읽기 실패 {type(e).__name__}: 우아미 소파 {WATCH_SKU} 다시 매입될 수 있음, 확인 필요"
    if WATCH_SKU in skus:
        return f"우아미 소파 {WATCH_SKU}: 매입 제외 목록에 있음 (목록 {len(skus)}개)"
    return f"우아미 소파 {WATCH_SKU}: 매입 제외 목록에 없음, 다시 매입될 수 있음 (목록 {len(skus)}개), 확인 필요"


def daily():
    """11/09 ~19:45: every day at 08:00 (the 12 h before) until the round end."""
    import alerts
    from datetime import timedelta
    from limits import ROUND_END
    while True:
        n = datetime.now()
        cands = [n.replace(hour=h, minute=0, second=0, microsecond=0) + timedelta(days=d) for d in (0, 1)
                 for h in (8, 20)]                # 11/10 ~12:10 (person): 08:00 and 20:00
        at = min(x for x in cands if x > n)
        if at.timestamp() > ROUND_END:
            return
        while time.time() < at.timestamp():
            time.sleep(min(60, max(1, at.timestamp() - time.time())))
        t = at.timestamp()
        try:
            alerts.send("daily", f"morning_summary:{at:%Y%m%d}" + ("" if at.hour == 8 else f"_{at:%H}"), summary(t - NIGHT_H * 3600, t))
        except Exception as e:
            alerts.send("urgent", f"morning_summary_fail:{at:%Y%m%d%H}", f"12시간 요약 실패: {type(e).__name__}: {e}")
        time.sleep(120)


def main():
    if "--dry" in sys.argv:
        now = time.time()
        print(summary(now - NIGHT_H * 3600, now))
        return
    if "--daily" in sys.argv:
        daily()
        return
    while time.time() < AT:
        time.sleep(min(60, max(1, AT - time.time())))
    import alerts
    alerts.send("daily", f"morning_summary:{datetime.fromtimestamp(AT):%Y%m%d}", summary(AT - NIGHT_H * 3600, AT))


if __name__ == "__main__":
    main()
