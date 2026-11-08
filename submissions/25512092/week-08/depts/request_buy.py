"""Request-based buying (person's decision 11/08 ~13:45). depts/purchasing.make_plan calls candidates() once a run.

A SKU buyers asked for by name at least MIN_REQUESTS times in the last 24 h while I had no unit of it (substitute
offers in market.db shop_subst, and "not in stock" answers of the substitute experiment in logs/subst_exp.jsonl)
becomes a buy candidate whatever its place on the hot list, when it passes the basic filters:
  margin   the market average (market_db.sku_avg) >= expected cost x (1 + purchasing.min_margin); expected cost =
           list x purchasing.COST_SHARE x live surge
  food     shelf life >= FOOD_SHELF_H (72 h), and not perishable (부패주의)
  price    expected cost <= qc.HIGH_MIN (high-price units keep their own rules)
Target: TARGET units held per SKU; at most MAX_LINES lines a run (the run has 10 lines in all).
Drop: a SKU first bought this way that sold none of its units in the 24 h after (my settles) leaves the list for good
(logs/request_buy.json, decision request_buy_drop).
"""
import json
import math
import os
import sqlite3
import time
from collections import Counter

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATE = os.path.join(HERE, "logs", "request_buy.json")
MIN_REQUESTS = 50
TARGET = 2
FOOD_SHELF_H = 72
MAX_LINES = 3
DROP_AFTER_S = 86400
ME = "choo-chu"


def _state():
    try:
        with open(STATE, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def _save(st):
    tmp = STATE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(st, f, ensure_ascii=False)
    os.replace(tmp, STATE)


def requests(db, now):
    """{sku: requests} named while I had no unit, last 24 h."""
    t0 = now - 86400
    c = Counter(x for (x,) in db.execute("SELECT x FROM shop_subst WHERE ts>=?", (t0,)))
    try:
        with open(os.path.join(HERE, "logs", "subst_exp.jsonl"), encoding="utf-8") as f:
            for ln in f:
                if '"no_offer"' in ln:
                    e = json.loads(ln)
                    if e["ts"] >= t0 and e.get("x"):
                        c[e["x"]] += 1
    except OSError:
        pass
    return c


def candidates(catalog, held, surge, log=print, now=None):
    """[(sku, qty, avg, why)] for this run, best-requested first, at most MAX_LINES. Drops and records SKUs that sold
    nothing in the 24 h after their first request-based buy."""
    import decisions
    import policy
    from depts.qc import HIGH_MIN
    from market_db import sku_avg
    from depts.purchasing import COST_SHARE
    now = now or time.time()
    st = _state()
    db = sqlite3.connect(os.path.join(HERE, "market.db"), timeout=30)
    try:
        req = requests(db, now)
        mm = policy.get("purchasing", "min_margin")
        for sku, s in list(st.items()):                # the 24 h no-sale drop
            if s.get("dropped") or not s.get("first_buy") or now - s["first_buy"] < DROP_AFTER_S:
                continue
            sold = db.execute("SELECT COUNT(*) FROM settles WHERE shop=? AND sku=? AND ts>=? AND ts<?",
                              (ME, sku, s["first_buy"], s["first_buy"] + DROP_AFTER_S)).fetchone()[0]
            if sold == 0:
                s["dropped"] = round(now)
                decisions.record("purchasing", "request_buy_drop", sku, 0,
                                 f"request-based SKU sold none in the 24 h after its first buy "
                                 f"({time.strftime('%m-%d %H:%M', time.localtime(s['first_buy']))}): no longer a candidate")
                log(f"[request] {sku}: no sale in 24 h after the first buy -> dropped")
        out = []
        for sku, n in req.most_common():
            if n < MIN_REQUESTS:
                break
            if (st.get(sku) or {}).get("dropped"):
                continue
            c = catalog.get(sku) or {}
            lp = c.get("list_price") or 0
            if not lp:
                continue
            kind = c.get("kind", "goods")
            if kind == "food" and ((c.get("shelf_hours") or 0) < FOOD_SHELF_H or "부패주의" in (c.get("category") or "")):
                continue
            cost = lp * COST_SHARE.get(kind, 0.6) * surge.get(sku, 1.0)
            if cost > HIGH_MIN:
                continue
            avg, k = sku_avg(db, sku, now)
            if avg is None or avg < cost * (1 + mm):
                continue
            qty = TARGET - held.get(sku, 0)
            if qty <= 0:
                continue
            out.append((sku, qty, round(avg), f"{n} requests in 24 h, avg {round(avg):,} (n {k}), est. cost {int(cost):,}"))
            if len(out) >= MAX_LINES:
                break
    finally:
        db.close()
    _save(st)
    return out


def bought(skus, now=None):
    """make_plan planned these: the first request-based buy time is kept for the 24 h drop."""
    if not skus:
        return
    st = _state()
    now = now or time.time()
    for sku in skus:
        s = st.setdefault(sku, {})
        s.setdefault("first_buy", round(now))
        s["last_buy"] = round(now)
    _save(st)
