"""Student ranking every 3 hours (person 11/12 ~16:10): the midterm's Round 3 rank is the board Players table's
student_pct (shop ALL + buyer ALL recomputed among the students). One Telegram at every HOURS-th hour (00, 03, 06 ...):
our student_pct and student rank, our student_total, the gap to the 9th and 10th student totals, and our saved vs
the best other student buyer's saved (the 2nd among students). Read-only: GET /api/board only.
    python tools/student_rank_watch.py [--once | --dry]
"""
import os
import sys
import time
from datetime import datetime

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
ME = "Choo-chu"
HOURS = 3
END = datetime(2026, 11, 17, 23, 59).timestamp()


def fetch():
    import httpx
    from market_db import MARKET
    return httpx.get(f"{MARKET}/api/board", params={"round": 3}, timeout=30).json()


def numbers(j, me=ME):
    st = [p for p in j.get("players") or [] if p.get("student")]
    st.sort(key=lambda p: -(p.get("student_total") or 0))
    mine = next(p for p in st if p["player"] == me)
    rank = 1 + sum(1 for p in st if (p.get("student_total") or 0) > mine["student_total"])
    tot = [p["student_total"] for p in st]
    stud_buyers = {(p.get("buyer") or {}).get("name") for p in st}
    my_b = (mine.get("buyer") or {}).get("name")
    saved = {b["name"]: b.get("saved") for b in j.get("buyers") or [] if b["name"] in stud_buyers and b.get("saved") is not None}
    others = sorted(((v, n) for n, v in saved.items() if n != my_b), reverse=True)
    return {"pct": mine.get("student_pct"), "rank": rank, "n": len(st), "total": mine["student_total"],
            "ninth": tot[8] if len(tot) > 8 else None, "tenth": tot[9] if len(tot) > 9 else None,
            "saved": saved.get(my_b), "second": others[0] if others else None,
            "saved_rank": 1 + sum(1 for v, _ in others if v > (saved.get(my_b) or 0))}


def text(x, now=None):
    now = now or time.time()
    g = lambda v: "-" if v is None else f"{x['total'] - v:+.3f}"
    sec = x["second"]
    s = (f"saved {x['saved']} 학생 {x['saved_rank']}위, 다음 학생 {sec[1]} {sec[0]} (차이 {x['saved'] - sec[0]:+.4f})"
         if sec and x["saved"] is not None else f"saved {x['saved']}")
    return (f"학생 순위 {datetime.fromtimestamp(now):%m-%d %H:%M}: {x['rank']}위/{x['n']} (student_pct {x['pct']}), "
            f"합계 {x['total']:.3f}; 9위 {x['ninth']} ({g(x['ninth'])}), 10위 {x['tenth']} ({g(x['tenth'])}) | " + s)


def due(now, last):
    """The latest HOURS-th hour mark at or before now, if it was not reported yet."""
    t = datetime.fromtimestamp(now)
    mark = t.replace(minute=0, second=0, microsecond=0, hour=t.hour - t.hour % HOURS).timestamp()
    return mark if mark > (last or 0) else None


def main():
    if "--dry" in sys.argv:
        print(text(numbers(fetch())))
        return
    import alerts
    last = None
    while time.time() < END + 3600:
        now = time.time()
        mark = due(now, last)
        if mark and now - mark < 1800:
            try:
                alerts.send("daily", f"student_rank:{int(mark)}", text(numbers(fetch()), now))
                last = mark
            except Exception as e:
                print(f"{datetime.now():%H:%M:%S} failed: {type(e).__name__}: {e}", flush=True)
        elif mark:
            last = mark                                # started late in a slot: wait for the next mark
        if "--once" in sys.argv:
            return
        time.sleep(60)


if __name__ == "__main__":
    main()
