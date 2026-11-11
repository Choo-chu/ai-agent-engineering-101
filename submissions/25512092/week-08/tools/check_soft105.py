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


TOL_S = 2700          # board_hist is written every 30-43 min (kit ticks): 20 min missed the 16:35 report's "now"
FAIL = "읽기 실패"
RETRIES = 3           # a failed reading: try again with each of the next board snapshots
WAIT_S = 5400         # at most this long for one next snapshot


def row_at(t, tol=TOL_S, after=None, db_path=None):
    """(ts, my buyer row) of the board_hist snapshot nearest t within tol (after: only snapshots after it), or
    (None, None)."""
    import sqlite3
    db = sqlite3.connect(db_path or os.path.join(HERE, "market.db"), timeout=60)
    try:
        r = db.execute("SELECT ts, buyer FROM board_hist WHERE ts > ? ORDER BY ABS(ts - ?) LIMIT 1",
                       (after or 0, t)).fetchone()
    finally:
        db.close()
    if not r or abs(r[0] - t) > tol:
        return None, None
    try:
        return r[0], json.loads(r[1])
    except (TypeError, ValueError):
        return None, None


def live_row(j, me="choo-chu"):
    """My buyer row from a live board json, with rank as board_hist has it."""
    b = next(x for x in j["buyers"] if x.get("name") == me)
    row = dict(b, rank=1 + sum(1 for r in j["buyers"] if (r.get("all") or 0) > (b.get("all") or 0)))
    if row.get("deals") is None or row.get("all") is None:
        raise ValueError("board row without deals / all")
    return row


def report(s, now=None, path=SN_LOG, cur=None, board=None, db_path=None, clock=time.time):
    """(text, the readings that failed). cur: (ts, row) for "now" (a retry passes the next snapshot); otherwise the
    live board, then the nearest snapshot."""
    import morning_summary as ms
    if board is None:
        import board_speed as bs
        board = bs.board
    now = now or time.time()
    t0 = s["t0"]
    h = max((now - t0) / 3600, 0.01)
    failed = []
    j = None
    if cur is None:
        try:
            j = board()
            cur = (clock(), live_row(j))          # the reading time, for deals per hour
        except Exception:
            j = None
            cur = row_at(now, db_path=db_path)
    (tp, bp), (ta, b0), (t1, b1) = row_at(t0 - h * 3600, db_path=db_path), row_at(t0, db_path=db_path), cur
    for name, b in (("직전 시작", bp), ("적용 때", b0), ("지금", b1)):
        if b is None:
            failed.append(name)

    def dph(ta_, x, tb_, y):
        if x is None or y is None or x.get("deals") is None or y.get("deals") is None or tb_ <= ta_:
            return FAIL
        return f"{(y['deals'] - x['deals']) / ((tb_ - ta_) / 3600):.1f}"

    a, p = stats(t0, now, path), stats(t0 - h * 3600, t0, path)
    g = lambda b, k: FAIL if b is None else b.get(k)
    L = [f"soft_neg 즉시 수락 x1.05 {h:.1f}시간 점검: {datetime.fromtimestamp(t0):%m-%d %H:%M} 적용, 후 vs 직전 같은 길이"]
    L.append(f"- 시간당 deals(보드) {dph(ta, b0, t1, b1)} vs {dph(tp, bp, ta, b0)}; soft_neg 기록 기준 결제 성공 "
             f"{a['paid_ph']:.1f} vs {p['paid_ph']:.1f}/시간")
    L.append(f"- 성사율 {pct(a['rate'])} ({a['deals']}/{a['n']}) vs {pct(p['rate'])} ({p['deals']}/{p['n']})")
    L.append(f"- 평균 초과 체결(20만 미만 SKU) {a['over']}건"
             + (f", 평균 대비 {a['over_ratio']:.3f}배" if a["over_ratio"] else "") + f" vs {p['over']}건")
    rk = lambda b: FAIL if b is None else f"{b.get('rank')}위"
    L.append(f"- saved {g(b0, 'saved')} -> {g(b1, 'saved')}, ALL {g(b0, 'all')} ({rk(b0)}) -> "
             f"{g(b1, 'all')} ({rk(b1)})")
    L.append(f"- 적용 때 {s.get('all_line', '-')}")
    try:
        L.append(f"- 지금 {ms.all_line(j if j is not None else board())}")
    except Exception as e:
        L.append(f"- 지금 ALL 위·아래: 보드 {FAIL} ({type(e).__name__})")
        failed.append("ALL 위·아래")
    if failed:
        L.append(f"- 보드 {FAIL}: {', '.join(failed)} -> 다음 스냅샷 값으로 다시 시도")
    return "\n".join(L), failed


def next_snapshot(after, wait_s=None, sleep=time.sleep, db_path=None):
    """(ts, my buyer row) of the first board_hist snapshot after `after`, waiting up to wait_s (WAIT_S); (None, None)."""
    import sqlite3
    end = time.time() + (WAIT_S if wait_s is None else wait_s)
    while True:
        db = sqlite3.connect(db_path or os.path.join(HERE, "market.db"), timeout=60)
        try:
            r = db.execute("SELECT ts, buyer FROM board_hist WHERE ts > ? ORDER BY ts LIMIT 1", (after,)).fetchone()
        finally:
            db.close()
        if r:
            try:
                return r[0], json.loads(r[1])
            except (TypeError, ValueError):
                after = r[0]
                continue
        if time.time() >= end:
            return None, None
        sleep(60)


def send_with_retry(s, send, now=None, sleep=time.sleep, db_path=None, board=None, path=SN_LOG, clock=time.time):
    """The report; while a board reading failed, again with each next snapshot (up to RETRIES). Returns the texts."""
    now = now or time.time()
    key = f"check_soft105:{s['t0']}"
    text, failed = report(s, now=now, cur=None, board=board, db_path=db_path, path=path, clock=clock)
    send("daily", key, text)
    out, after = [text], now
    for k in range(RETRIES):
        if not failed:
            break
        ts, row = next_snapshot(after, sleep=sleep, db_path=db_path)
        if ts is None:
            send("daily", f"{key}:retry{k + 1}", f"soft_neg x1.05 점검: 다음 스냅샷이 {WAIT_S // 60}분 안에 없어 다시 읽기 중단")
            break
        text, failed = report(s, now=ts, cur=(ts, row), board=board, db_path=db_path, path=path)
        text = f"[다시 읽음 {k + 1}: {datetime.fromtimestamp(ts):%H:%M} 스냅샷]\n" + text
        send("daily", f"{key}:retry{k + 1}", text)
        out.append(text)
        after = ts
    return out


def main():
    if "--start" in sys.argv:
        t0 = next((float(x.split("=", 1)[1]) for x in sys.argv if x.startswith("--t0=")), None)
        print(start(t0=t0))
        return
    s = load() or start()
    if "--dry" in sys.argv:
        print(report(s)[0])
        return
    while time.time() < s["t0"] + H * 3600:
        time.sleep(min(60, max(1, s["t0"] + H * 3600 - time.time())))
    import alerts
    try:
        send_with_retry(s, alerts.send)
    except Exception as e:
        alerts.send("urgent", "check_soft105_fail", f"soft_neg x1.05 3시간 점검 실패: {type(e).__name__}: {e}")


if __name__ == "__main__":
    main()
