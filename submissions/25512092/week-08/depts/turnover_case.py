"""Overstock by turnover (person's decision 11/09 ~23:40). While the automatic STOCK_CAP is on (limits.auto_cap_on), the
CEO's shop case (depts/ceo.raw_shop_case) is overstock only when
  1. the median supply -> sale time of my units sold in the last WINDOW_H (6 h) is over MEDIAN_H (3 h), with at least
     MIN_SALES (10) sales, or
  2. of the units supplied in the last SUPPLY_H (24 h, and not before the automatic cap was switched on) that are at
     least OLD_H (6 h) old, the share of their cost still unsold is over OLD_SHARE (25%), judged once their cost is at
     least MIN_COST (5M)
(the same two measures as the cap brake, depts/cap_brake.py). "stock >= cap" and low cash are not overstock then: low
cash only stops buying (the restock budget is cash - 3M), the price floors stay normal.
Thresholds: stock_cap_auto.json "case" ({median_h, window_h, min_sales, old_h, old_share, supply_h, min_cost}).
"""
import os
import sqlite3
import statistics
import time

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ME = "choo-chu"
DEFAULT = {"median_h": 3, "window_h": 6, "min_sales": 10, "old_h": 6, "old_share": 0.25, "supply_h": 24,
           "min_cost": 5_000_000}


def measure(now=None, since=0, c=None, db_path=None):
    now = now or time.time()
    c = dict(DEFAULT, **(c or {}))
    db = sqlite3.connect(db_path or os.path.join(HERE, "market.db"), timeout=30)
    try:
        ages = [x[0] for x in db.execute(
            "SELECT s.ts - m.supplied_at FROM settles s JOIN my_stock m ON m.unit=s.unit WHERE s.shop=? AND s.ts>=? "
            "AND m.supplied_at IS NOT NULL", (ME, now - c["window_h"] * 3600))]
        el = db.execute("SELECT m.cost, EXISTS(SELECT 1 FROM settles s WHERE s.unit=m.unit AND s.shop=? AND s.ts<=?) "
                        "FROM my_stock m WHERE m.supplied_at>=? AND m.supplied_at<=?",
                        (ME, now, max(since or 0, now - c["supply_h"] * 3600), now - c["old_h"] * 3600)).fetchall()
    finally:
        db.close()
    el_cost = sum(x or 0 for x, _ in el)
    un_cost = sum(x or 0 for x, sold in el if not sold)
    return {"sales": len(ages), "median_h": round(statistics.median(ages) / 3600, 2) if ages else None,
            "old_cost": el_cost, "old_unsold": un_cost, "old_share": round(un_cost / el_cost, 4) if el_cost else None}


def overstock(now=None, r=None, db_path=None):
    """(True / False, reason)."""
    import limits
    r = limits.auto_cap_rules() if r is None else r
    c = dict(DEFAULT, **(r.get("case") or {}))
    m = measure(now, r.get("since") or 0, c, db_path)
    why = []
    if m["sales"] >= c["min_sales"] and m["median_h"] is not None and m["median_h"] > c["median_h"]:
        why.append(f"sale median {m['median_h']} h > {c['median_h']} h ({m['sales']} sales in {c['window_h']} h)")
    if m["old_cost"] >= c["min_cost"] and m["old_share"] is not None and m["old_share"] > c["old_share"]:
        why.append(f"{c['old_h']} h+ unsold {m['old_share']:.1%} > {c['old_share']:.0%} of {m['old_cost']:,}")
    if why:
        return True, "turnover: " + "; ".join(why)
    return False, (f"turnover ok: median {m['median_h']} h ({m['sales']} sales), {c['old_h']} h+ unsold "
                   f"{'-' if m['old_share'] is None else f'{m['old_share']:.1%}'} of {m['old_cost']:,}")
