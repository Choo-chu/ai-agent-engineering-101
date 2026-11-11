"""3 h check of the 11/11 ~10:30 changes (person's decision): absolute saved guard with switching on again (all four
buyer features on), deep stock at most 3, high pins to 11/12 12:00, auto mode ended. One Telegram (daily) H hours
after the start, after vs the same length before:
  buyer  deals per hour, saved, ALL rank and saved rank, each feature on or off
  shop   12 h+ unsold stock (high / normal, cost and count) at the start vs now, deep-stock SKUs' buys / sales /
         turnover (median supply -> sale) / stock-out hours, Book and revenue per hour
    python tools/check_1111.py [--start | --dry]     (--start: record the start now; --dry: print the report now)
"""
import json
import os
import sys
import time
from datetime import datetime

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "tools"))
os.chdir(HERE)
STATE = os.path.join(HERE, "logs", "check_1111.json")
H = 3


def load():
    try:
        with open(STATE, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def start(now=None):
    import morning_summary as ms
    now = now or time.time()
    s = {"t0": round(now), "stock": ms.stock_line(now)}
    with open(STATE, "w", encoding="utf-8") as f:
        json.dump(s, f, ensure_ascii=False)
    return s


def features():
    from depts import accept_rule, high_accept, second_shop, soft_neg
    names = (("비싼 주문 완화", high_accept), ("D", second_shop), ("soft_neg", soft_neg), ("수락 규칙", accept_rule))
    return ", ".join(f"{n} {'켜짐' if m.on() else '꺼짐'}" for n, m in names)


def per_h(a, b, k, h):
    return (b[k] - a[k]) / h if a and b and a.get(k) is not None and b.get(k) is not None else None


def fmt(v, d=0):
    return "-" if v is None else f"{v:,.{d}f}"


def report(s, now=None):
    import board_speed as bs
    import morning_summary as ms
    from depts import deep_high
    now = now or time.time()
    t0 = s["t0"]
    h = max((now - t0) / 3600, 0.01)
    (sp, bp), (s0, b0), (s1, b1) = bs.mine_at(t0 - h * 3600), bs.mine_at(t0), bs.mine_at(now)
    L = [f"11/11 변경 {h:.1f}시간 점검: {datetime.fromtimestamp(t0):%m-%d %H:%M} 적용, 후 vs 직전 같은 길이"]
    L.append(f"- buyer 시간당 deals {fmt(per_h(b0, b1, 'deals', h), 1)} vs {fmt(per_h(bp, b0, 'deals', h), 1)}; saved "
             f"{(b0 or {}).get('saved')} -> {(b1 or {}).get('saved')} (saved {(b0 or {}).get('saved_rank')}위 -> "
             f"{(b1 or {}).get('saved_rank')}위), ALL {(b0 or {}).get('all')} ({(b0 or {}).get('rank')}위) -> "
             f"{(b1 or {}).get('all')} ({(b1 or {}).get('rank')}위)")
    L.append(f"- 장치: {features()} (끄는/켜는 saved: 비싼 주문 0.400/0.405, D 0.395/0.400, soft_neg·수락 0.388/0.393)")
    L.append(f"- 적용 때 {s['stock']}")
    L.append(f"- 지금 {ms.stock_line(now)}")
    a = deep_high.window_stats(deep_high.skus_between(t0, now), t0, now)
    p = deep_high.window_stats(deep_high.skus_between(t0 - h * 3600, t0), t0 - h * 3600, t0)
    L.append(f"- 깊게 쌓기 대상(최대 3개) SKU {a['skus']} vs {p['skus']}개: 매입 {a['buy_n']}개 {a['buy_cost']:,} vs {p['buy_n']}개 "
             f"{p['buy_cost']:,}; 판매 {a['sell_n']}개 이익 {a['profit']:,} vs {p['sell_n']}개 {p['profit']:,}; 입고→판매 중앙값 "
             f"{fmt(a['median_h'], 2)} vs {fmt(p['median_h'], 2)}시간; 품절 {a['out_h']:.1f} vs {p['out_h']:.1f}시간")
    L.append(f"- 가게 시간당 Book {fmt(per_h(s0, s1, 'book', h))} vs {fmt(per_h(sp, s0, 'book', h))}, 시간당 매출 "
             f"{fmt(per_h(s0, s1, 'revenue', h))} vs {fmt(per_h(sp, s0, 'revenue', h))}, 순위 {(s0 or {}).get('rank')} -> "
             f"{(s1 or {}).get('rank')}")
    return "\n".join(L)


def main():
    if "--start" in sys.argv:
        print(start())
        return
    s = load() or start()
    if "--dry" in sys.argv:
        print(report(s))
        return
    while time.time() < s["t0"] + H * 3600:
        time.sleep(min(60, max(1, s["t0"] + H * 3600 - time.time())))
    import alerts
    try:
        alerts.send("daily", f"check_1111:{s['t0']}", report(s))
    except Exception as e:
        alerts.send("urgent", "check_1111_fail", f"11/11 변경 3시간 점검 실패: {type(e).__name__}: {e}")


if __name__ == "__main__":
    main()
