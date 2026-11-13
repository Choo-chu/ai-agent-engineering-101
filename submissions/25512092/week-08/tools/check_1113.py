"""3-hour check (person 11/13 ~10:20, after the sofa warranty went on again; high 1 -> 2 and high_max 200 kept, buyer
unchanged). One Telegram ("daily") at every 3rd hour (12, 15, 18 ...), each number for the last 3 h vs the 3 h before:
  1. receipts / negotiations: high-price (cost > qc.HIGH_MIN) and sofa
  2. purchases from my shop by inextro, cheapest-in-town, nocha12 (count, amount)
  3. sofa revenue, profit and warranty refunds (3 h; and the 48 h auto-off rule: refunds vs profit)
  4. high-price revenue and profit
  5. cash and stock at cost
  6. 12 h+ unsold high-price units (live inventory) vs the 60M guard
  7. student rank, student total, gap to the 9th and 11th
Read-only.
    python tools/check_1113.py [--once | --dry]
"""
import os
import sqlite3
import sys
import time
from datetime import datetime

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "tools"))
H = 3
BUYERS = ("inextro", "cheapest-in-town", "nocha12")
ME = "choo-chu"
END = datetime(2026, 11, 17, 23, 59).timestamp()


def _db(db_path):
    return sqlite3.connect(f"file:{db_path or os.path.join(HERE, 'market.db')}?mode=ro", uri=True, timeout=10)


def shop(t0, t1, db_path=None, is_sofa=None):
    """{high: (receipts, negotiations), sofa: (...), buyers: {name: (n, amount)}, high_sales: (n, revenue, profit)}"""
    from depts.qc import HIGH_MIN
    if is_sofa is None:
        from depts.sofa import is_sofa
    d = _db(db_path)
    try:
        deals = d.execute("SELECT sku, cost, outcome FROM shop_deals WHERE ts>=? AND ts<? AND outcome!='open'",
                          (t0, t1)).fetchall()
        sales = d.execute("SELECT s.buyer, s.amount, m.cost FROM settles s LEFT JOIN my_stock m ON m.unit=s.unit "
                          "WHERE s.shop=? AND s.ts>=? AND s.ts<?", (ME, t0, t1)).fetchall()
    finally:
        d.close()
    hi = [o for _, c, o in deals if (c or 0) > HIGH_MIN]
    so = [o for k, _, o in deals if is_sofa(k)]
    hs = [(a or 0, c or 0) for _, a, c in sales if (c or 0) > HIGH_MIN]
    return {"high": (hi.count("receipt"), len(hi)), "sofa": (so.count("receipt"), len(so)),
            "buyers": {b: (sum(1 for x in sales if x[0] == b), sum(x[1] or 0 for x in sales if x[0] == b)) for b in BUYERS},
            "high_sales": (len(hs), sum(a for a, _ in hs), sum(a - c for a, c in hs))}


def cash(now, db_path=None):
    d = _db(db_path)
    try:
        return d.execute("SELECT balance, stock_cost FROM cash WHERE ts<=? ORDER BY ts DESC LIMIT 1", (now,)).fetchone()
    finally:
        d.close()


def rank(j, me="Choo-chu"):
    st = sorted((p for p in j.get("players") or [] if p.get("student")), key=lambda p: -(p.get("student_total") or 0))
    i = next(k for k, p in enumerate(st) if p["player"] == me)
    tot = lambda k: st[k]["student_total"] if 0 <= k < len(st) else None
    return {"rank": i + 1, "n": len(st), "total": st[i]["student_total"], "shop": st[i].get("student_shop"),
            "buyer": st[i].get("student_buyer"), "ninth": tot(8), "eleventh": tot(10),
            "ninth_name": st[8]["player"] if len(st) > 8 else None, "eleventh_name": st[10]["player"] if len(st) > 10 else None}


def text(now, cur, prev, sofa3, sofa3p, sofa48, cash_now, cash_prev, aged, guard, rk):
    r = lambda v: f"{v[0]}/{v[1]} ({v[0] / v[1]:.1%})" if v[1] else f"{v[0]}/0"
    out = [f"3시간 점검 {datetime.fromtimestamp(now):%m-%d %H:%M} (최근 {H}시간 vs 그 전 {H}시간)",
           f"1. 영수증/협상: 고가 {r(cur['high'])} vs {r(prev['high'])}; 소파 {r(cur['sofa'])} vs {r(prev['sofa'])}",
           "2. 구매량(우리 가게): " + ", ".join(f"{b} {cur['buyers'][b][0]}건 {cur['buyers'][b][1]:,} vs {prev['buyers'][b][0]}건"
                                         for b in BUYERS),
           f"3. 소파: 매출 {sofa3['revenue']:,} 이익 {sofa3['profit']:+,} 환불 {sofa3['refunds']}건 {sofa3['refund_amount']:,} "
           f"vs 매출 {sofa3p['revenue']:,} 환불 {sofa3p['refunds']}건 | 48시간 환불 {sofa48['refund_amount']:,} vs 이익 "
           f"{sofa48['profit']:,} (환불 > 이익이면 보증 자동 해제)",
           f"4. 고가 판매: {cur['high_sales'][0]}개 매출 {cur['high_sales'][1]:,} 이익 {cur['high_sales'][2]:+,} vs "
           f"{prev['high_sales'][0]}개 {prev['high_sales'][1]:,} {prev['high_sales'][2]:+,}",
           "5. 현금: " + (f"{cash_now[0]:,} (재고 원가 {cash_now[1]:,})" if cash_now else "-")
           + (f" vs 3시간 전 {cash_prev[0]:,} ({cash_prev[1]:,})" if cash_prev else ""),
           f"6. 12시간+ 미판매 고가: {aged[0]}개 {aged[1]:,} (끄는 기준 {guard:,} 초과)"]
    if rk:
        g = lambda v: "-" if v is None else f"{rk['total'] - v:+.3f}"
        out.append(f"7. 학생 순위 {rk['rank']}위/{rk['n']} 합계 {rk['total']:.3f} (shop {rk['shop']}, buyer {rk['buyer']}); "
                   f"9위 {rk['ninth_name']} {rk['ninth']} ({g(rk['ninth'])}), 11위 {rk['eleventh_name']} {rk['eleventh']} "
                   f"({g(rk['eleventh'])})")
    else:
        out.append("7. 학생 순위: board 읽기 실패")
    return "\n".join(out)


def build(now, db_path=None, board=None, units=None, sofa_numbers=None, is_sofa=None):
    import alerts
    from depts import wide_trial
    sofa_numbers = sofa_numbers or alerts.sofa_numbers
    t0, tp = now - H * 3600, now - 2 * H * 3600
    cur, prev = shop(t0, now, db_path, is_sofa), shop(tp, t0, db_path, is_sofa)
    aged = wide_trial.aged_high(units if units is not None else wide_trial.live_units(), now)
    guard = int(wide_trial.rules().get("max_cost") or 60_000_000)
    try:
        if board is None:
            import student_rank_watch
            board = student_rank_watch.fetch()
        rk = rank(board)
    except Exception:
        rk = None
    return text(now, cur, prev, sofa_numbers(t0, now), sofa_numbers(tp, t0), sofa_numbers(now - 48 * 3600, now),
                cash(now, db_path), cash(t0, db_path), aged, guard, rk)


def main():
    if "--dry" in sys.argv:
        print(build(time.time()))
        return
    import alerts
    import student_rank_watch as W
    last = None
    while time.time() < END + 3600:
        now = time.time()
        mark = W.due(now, last)
        if mark and now - mark < 1800:
            try:
                alerts.send("daily", f"check_1113:{int(mark)}", build(now))
                last = mark
            except Exception as e:
                print(f"{datetime.now():%H:%M:%S} failed: {type(e).__name__}: {e}", flush=True)
        elif mark:
            last = mark
        if "--once" in sys.argv:
            return
        time.sleep(60)


if __name__ == "__main__":
    main()
