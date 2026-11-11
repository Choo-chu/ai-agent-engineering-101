"""3 h check of soft_neg's instant accept at <= 1.05 x the market average (person's decision 11/11 ~13:35; list >=
200,000 keeps 1.10 via high_accept, the absolute saved guard unchanged). One Telegram (daily) H hours after the start,
after vs the same length before:
  buyer deals per hour, close rate (soft_neg orders: deals / orders), saved, ALL rank,
        the ALL gap to the buyer just above and just below (at the start and now)
  plus the soft deals closed above the market average (count, average price / average)
    python tools/check_soft105.py [--start | --dry]     (--start: record the start now; --dry: print the report now)
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
STATE = os.path.join(HERE, "logs", "check_soft105.json")
SN_LOG = os.path.join(HERE, "logs", "soft_neg.jsonl")
H = 3


def load():
    try:
        with open(STATE, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def start(now=None, t0=None):
    import board_speed as bs
    import morning_summary as ms
    now = now or time.time()
    s = {"t0": round(t0 or now), "all_line": ms.all_line(bs.board())}
    with open(STATE, "w", encoding="utf-8") as f:
        json.dump(s, f, ensure_ascii=False)
    return s


def orders(t0, t1, path=SN_LOG):
    out = []
    try:
        with open(path, encoding="utf-8") as f:
            for x in f:
                try:
                    r = json.loads(x)
                except ValueError:
                    continue
                if t0 <= r.get("ts", 0) < t1:
                    out.append(r)
    except OSError:
        pass
    return out


def stats(t0, t1, path=SN_LOG):
    R = orders(t0, t1, path)
    h = max(1e-6, (t1 - t0) / 3600)
    deals = [r for r in R if r.get("deal")]
    over = [r for r in deals if r.get("market_avg") and (r.get("price") or r.get("agreed") or 0) > r["market_avg"]
            and not r.get("high_accept")]
    ratio = (sum((r.get("price") or r.get("agreed")) / r["market_avg"] for r in over) / len(over)) if over else None
    return {"n": len(R), "deals": len(deals), "rate": len(deals) / len(R) if R else None,
            "paid_ph": sum(1 for r in R if r.get("paid_ok")) / h, "over": len(over), "over_ratio": ratio}


def pct(v):
    return "-" if v is None else f"{v:.1%}"


def report(s, now=None, path=SN_LOG):
    import board_speed as bs
    import morning_summary as ms
    now = now or time.time()
    t0 = s["t0"]
    h = max((now - t0) / 3600, 0.01)
    (_, bp), (_, b0), (_, b1) = bs.mine_at(t0 - h * 3600), bs.mine_at(t0), bs.mine_at(now)
    a, p = stats(t0, now, path), stats(t0 - h * 3600, t0, path)
    dph = lambda x, y: f"{(y['deals'] - x['deals']) / h:.1f}" if x and y and x.get("deals") is not None and y.get(
        "deals") is not None else "-"
    g = lambda b, k: (b or {}).get(k)
    L = [f"soft_neg 즉시 수락 x1.05 {h:.1f}시간 점검: {datetime.fromtimestamp(t0):%m-%d %H:%M} 적용, 후 vs 직전 같은 길이"]
    L.append(f"- 시간당 deals(보드) {dph(b0, b1)} vs {dph(bp, b0)}; soft_neg 기록 기준 결제 성공 {a['paid_ph']:.1f} vs "
             f"{p['paid_ph']:.1f}/시간")
    L.append(f"- 성사율 {pct(a['rate'])} ({a['deals']}/{a['n']}) vs {pct(p['rate'])} ({p['deals']}/{p['n']})")
    L.append(f"- 평균 초과 체결(20만 미만 SKU) {a['over']}건"
             + (f", 평균 대비 {a['over_ratio']:.3f}배" if a["over_ratio"] else "") + f" vs {p['over']}건")
    L.append(f"- saved {g(b0, 'saved')} -> {g(b1, 'saved')}, ALL {g(b0, 'all')} ({g(b0, 'rank')}위) -> "
             f"{g(b1, 'all')} ({g(b1, 'rank')}위)")
    L.append(f"- 적용 때 {s.get('all_line', '-')}")
    try:
        L.append(f"- 지금 {ms.all_line(bs.board())}")
    except Exception as e:
        L.append(f"- 지금 ALL 위·아래: 보드 읽기 실패 ({type(e).__name__})")
    return "\n".join(L)


def main():
    if "--start" in sys.argv:
        t0 = next((float(x.split("=", 1)[1]) for x in sys.argv if x.startswith("--t0=")), None)
        print(start(t0=t0))
        return
    s = load() or start()
    if "--dry" in sys.argv:
        print(report(s))
        return
    while time.time() < s["t0"] + H * 3600:
        time.sleep(min(60, max(1, s["t0"] + H * 3600 - time.time())))
    import alerts
    try:
        alerts.send("daily", f"check_soft105:{s['t0']}", report(s))
    except Exception as e:
        alerts.send("urgent", "check_soft105_fail", f"soft_neg x1.05 3시간 점검 실패: {type(e).__name__}: {e}")


if __name__ == "__main__":
    main()
