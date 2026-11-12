"""Wider buying with idle cash (person's decision 11/12 ~14:20, from a 24 h simulation of A-D; applied: the best two by
expected profit / 12 h+ unsold increase at cost, normal goods first when close -> C and B). Rules in wide_trial.json
(read on every call; off without it or after the guard trips):
  B  high-price buying margin filter 8% -> 6% (b_margin), only for SKUs my shop has sold before (any time)
  C  hot SKUs that turn in <= 1 h (depts/hot_fast.py), normal goods only (est. cost <= HIGH_MIN): my_share 0.8 -> 1.2
  guard  high-price units (cost > qc.HIGH_MIN) held unsold over STALE_H (12 h), counted from the live inventory: at
         or over base + max_add_n (10) units or base + max_add_cost (5,000,000) -> both off, one urgent Telegram
         (base = the value when applied: 63 units, 35,875,897). Checked by tools/wide_trial_watch.py every 5 min and
         at the start of every buy plan.
  report one Telegram check_h (3) hours after the start (report()).
Lines bought because of B / C (B: the expected margin 6-8%; C: the units over the 0.8 target) -> logs/wide_trial.jsonl.
"""
import json
import os
import sqlite3
import time
from datetime import datetime

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RULES = os.path.join(HERE, "wide_trial.json")
LINES = os.path.join(HERE, "logs", "wide_trial.jsonl")
STALE_H = 12
ME = "choo-chu"
_sold = {"ts": 0, "skus": set()}


def rules(path=None):
    try:
        with open(path or RULES, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def save(r, path=None):
    path = path or RULES
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(r, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


def on(key, r=None):
    r = rules() if r is None else r
    return bool(r.get("enabled")) and not r.get("off_ts") and key in (r.get("applied") or [])


def sold_skus(db_path=None, now=None, ttl=600):
    """SKUs my shop has sold (market.db settles, any time); cached for ttl seconds."""
    now = now or time.time()
    if db_path is None and now - _sold["ts"] < ttl:
        return _sold["skus"]
    d = sqlite3.connect(f"file:{db_path or os.path.join(HERE, 'market.db')}?mode=ro", uri=True, timeout=30)
    try:
        s = {k for (k,) in d.execute("SELECT DISTINCT sku FROM settles WHERE shop=?", (ME,))}
    finally:
        d.close()
    if db_path is None:
        _sold.update(ts=now, skus=s)
    return s


def b_margin(sku, default, r=None, sold=None):
    """The high-price margin filter for `sku`: B's min (6%) for a SKU my shop has sold, else `default`."""
    r = rules() if r is None else r
    if not on("B", r):
        return default
    try:
        s = sold_skus() if sold is None else sold
    except sqlite3.Error:
        return default
    return min(default, float(r.get("B_min_margin", 0.06))) if sku in s else default


def c_shares(fast_share, is_high, r=None):
    """hot_fast's {sku: share} with C's share (1.2) for the normal-goods SKUs on it (high-price keep theirs)."""
    r = rules() if r is None else r
    if not on("C", r):
        return dict(fast_share)
    c = float(r.get("C_share", 1.2))
    return {k: (v if is_high(k) else max(v, c)) for k, v in fast_share.items()}


def note(lines, log=print, path=None):
    """[{opt, sku, qty}] planned because of B / C -> one row each."""
    if not lines:
        return
    try:
        with open(path or LINES, "a", encoding="utf-8") as f:
            for x in lines:
                f.write(json.dumps(dict(x, ts=round(time.time()))) + "\n")
        log("[wide trial] " + ", ".join(f"{x['opt']} {x['sku']} +{x['qty']}" for x in lines))
    except OSError:
        pass


def aged_high(units, now=None):
    """(units, cost) of held high-price units (cost > qc.HIGH_MIN) supplied over STALE_H ago."""
    from depts.qc import HIGH_MIN
    now = now or time.time()
    xs = [u for u in units if u.get("grade") != "expired" and (u.get("cost") or 0) > HIGH_MIN and u.get("supplied_at")
          and u["supplied_at"] <= now - STALE_H * 3600]
    return len(xs), int(sum(u["cost"] for u in xs))


def live_units(inv_path=None):
    with open(inv_path or os.path.join(HERE, ".market", "inventory.json"), encoding="utf-8") as f:
        return json.load(f).get("units") or []


def guard(units=None, now=None, send=None, path=None, log=print):
    """Both off + one urgent Telegram when the 12 h+ unsold high-price stock grew by max_add_n units or max_add_cost
    over the base. Returns 'tripped', 'ok', or 'off' (not running)."""
    r = rules(path)
    if not r.get("enabled") or r.get("off_ts"):
        return "off"
    now = now or time.time()
    units = live_units() if units is None else units
    n, cost = aged_high(units, now)
    b = r.get("base") or {}
    dn, dc = n - b.get("n", 0), cost - b.get("cost", 0)
    if dn < r.get("max_add_n", 10) and dc < r.get("max_add_cost", 5_000_000):
        return "ok"
    why = (f"12시간+ 미판매 고가 {n}개 {cost:,} (적용 때 {b.get('n')}개 {b.get('cost', 0):,}, {dn:+}개 {dc:+,}; 기준 "
           f"+{r.get('max_add_n', 10)}개 또는 +{r.get('max_add_cost', 5_000_000):,})")
    r.update(off_ts=round(now), off_why=why)
    save(r, path)
    log(f"[wide trial] guard tripped: {why} -> {'/'.join(r.get('applied') or [])} off")
    if send is None:
        import alerts
        send = alerts.send
    try:
        send("urgent", "wide_trial_off", f"후보 넓히기 {'+'.join(r.get('applied') or [])} 자동 끔: {why}. "
             f"고가 마진 8%, 일반 my_share 0.8로 돌아감")
    except Exception as e:
        log(f"[wide trial] alert failed: {type(e).__name__}: {e}")
    return "tripped"


def _lines(t0, t1, path=None):
    out = []
    try:
        with open(path or LINES, encoding="utf-8") as f:
            for ln in f:
                try:
                    x = json.loads(ln)
                except ValueError:
                    continue
                if t0 <= x.get("ts", 0) < t1:
                    out.append(x)
    except OSError:
        pass
    return out


def window(skus, t0, t1, d):
    """My supplies and sales of `skus` in [t0, t1): (buy n, buy cost, sold n, revenue, profit)."""
    if not skus:
        return 0, 0, 0, 0, 0
    q = ",".join("?" * len(skus))
    b = d.execute(f"SELECT COUNT(*), COALESCE(SUM(cost), 0) FROM my_stock WHERE sku IN ({q}) AND supplied_at>=? AND "
                  f"supplied_at<?", (*skus, t0, t1)).fetchone()
    s = d.execute(f"SELECT COUNT(*), COALESCE(SUM(s.amount), 0), COALESCE(SUM(m.cost), 0) FROM settles s JOIN my_stock m "
                  f"ON m.unit=s.unit WHERE s.shop=? AND s.sku IN ({q}) AND s.ts>=? AND s.ts<?", (ME, *skus, t0, t1)).fetchone()
    return b[0], int(b[1]), s[0], int(s[1]), int(s[1] - s[2])


def report(now=None, path=None, lines_path=None, db_path=None, inv_path=None):
    """The check_h report text: cash, the B / C lines (planned extra units), my buys and sales of those SKUs after vs
    the same length before, the 12 h+ unsold high-price trend every hour."""
    r = rules(path)
    now = now or time.time()
    t0 = r["since"]
    h = max((now - t0) / 3600, 0.01)
    xs = _lines(t0, now, lines_path)
    L = [f"후보 넓히기 {'+'.join(r.get('applied') or [])} {h:.1f}시간 점검 ({datetime.fromtimestamp(t0):%m-%d %H:%M} 적용"
         + (f", {datetime.fromtimestamp(r['off_ts']):%H:%M} 자동 끔" if r.get("off_ts") else "") + ", 후 vs 직전 같은 길이)"]
    d = sqlite3.connect(f"file:{db_path or os.path.join(HERE, 'market.db')}?mode=ro", uri=True, timeout=60)
    try:
        c = lambda t: d.execute("SELECT balance, stock_cost FROM cash ORDER BY ABS(ts - ?) LIMIT 1", (t,)).fetchone()
        c0, c1 = c(t0), c(now)
        if c0 and c1:
            L.append(f"- 현금 {c0[0]:,} -> {c1[0]:,} ({c1[0] - c0[0]:+,}), 재고 원가 {c0[1]:,} -> {c1[1]:,} "
                     f"({c1[1] - c0[1]:+,})")
        for opt, name in (("B", "B 고가 마진 6%"), ("C", "C 일반 my_share 1.2")):
            ys = [x for x in xs if x["opt"] == opt]
            skus = sorted({x["sku"] for x in ys})
            a, p = window(skus, t0, now, d), window(skus, t0 - h * 3600, t0, d)
            L.append(f"- {name}: 계획 추가분 {sum(x['qty'] for x in ys)}개 ({len(skus)}개 SKU); 그 SKU들 매입 {a[0]}개 "
                     f"{a[1]:,} vs {p[0]}개 {p[1]:,}, 판매 {a[2]}개 매출 {a[3]:,} 이익 {a[4]:,} vs {p[2]}개 {p[3]:,} {p[4]:,}")
    finally:
        d.close()
    import sys
    sys.path.insert(0, os.path.join(HERE, "tools"))
    import morning_summary as M
    tr = M.aged_high_trend(now, inv_path=inv_path, db_path=db_path, step_h=1, span_h=max(1, round(h)))
    b = r.get("base") or {}
    L.append(f"- {tr.split(': ', 1)[-1]} | 기준: 적용 때 {b.get('n')}개 {b.get('cost', 0):,} +{r.get('max_add_n', 10)}개 "
             f"또는 +{r.get('max_add_cost', 5_000_000):,}")
    return "\n".join(L)


def report_due(now=None, send=None, path=None, log=print, **kw):
    """Send report() once, check_h hours after the start. True when sent."""
    r = rules(path)
    now = now or time.time()
    if not r.get("since") or r.get("reported") or now < r["since"] + r.get("check_h", 3) * 3600:
        return False
    if send is None:
        import alerts
        send = alerts.send
    send("daily", f"wide_trial_report:{r['since']}", report(now, path=path, **kw))
    r = rules(path)
    r["reported"] = round(now)
    save(r, path)
    return True
