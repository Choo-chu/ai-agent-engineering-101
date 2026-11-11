"""High-price units over 1.5M cost (person's decision 11/11 ~20:10, with HIGH_MAX 1.5M -> 3.0M). Rules in top_high.json
(read on every call; off without it):
  holding   at most max_units (10) units with cost > min_cost held at once (stock + this plan), at most max_per_sku (2)
            per SKU even for a deep-stock SKU (deep_high's 2-5 is cut to 2 for these)
  warranty  only A grade, and only in a leaf category whose market break rate (all shops' sales, broken / sold, at least
            min_n sales) is at most max_break (6%); B and C grade: none. This decides before the sofa and B grade
            rules (depts/sales.warranty_hours). Normal shop case only, like the A grade warranty.
"""
import json
import os
import time

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RULES = os.path.join(HERE, "top_high.json")
MIN_COST = 1_500_000


def rules(path=None):
    try:
        with open(path or RULES, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def is_top(cost, r=None):
    r = rules() if r is None else r
    return bool(r.get("enabled")) and (cost or 0) > r.get("min_cost", MIN_COST)


def per_sku(r=None):
    r = rules() if r is None else r
    return int(r.get("max_per_sku", 2))


def held(units, r=None):
    """(units with cost > min_cost held, {sku: count})."""
    r = rules() if r is None else r
    per = {}
    for u in units:
        if u.get("grade") != "expired" and (u.get("cost") or 0) > r.get("min_cost", MIN_COST):
            per[u["sku"]] = per.get(u["sku"], 0) + 1
    return sum(per.values()), per


def cap_plan(plan, units, est_cost, log=print, r=None):
    """The plan with its > min_cost lines cut so that held + planned <= max_units and <= max_per_sku per SKU (in plan
    order: the first lines keep their units)."""
    r = rules() if r is None else r
    if not r.get("enabled"):
        return plan
    n, per = held(units, r)
    room = max(0, int(r.get("max_units", 10)) - n)
    out = []
    for p in plan:
        c = est_cost(p["sku"])
        if not is_top(c, r):
            out.append(p)
            continue
        q = min(p["qty"], room, per_sku(r) - per.get(p["sku"], 0))
        if q <= 0:
            log(f"[top high] {p['sku']} x{p['qty']} (est. cost {int(c):,}): over 1.5M held {n}/{r.get('max_units', 10)}, "
                f"this SKU {per.get(p['sku'], 0)}/{per_sku(r)} -> skip")
            continue
        if q < p["qty"]:
            log(f"[top high] {p['sku']} x{p['qty']} -> x{q} (over 1.5M room {room}, SKU {per.get(p['sku'], 0)}/{per_sku(r)})")
        room -= q
        per[p["sku"]] = per.get(p["sku"], 0) + q
        out.append(dict(p, qty=q))
    return out


def leaf(u):
    return (u.get("category") or "").split(">")[-1]


def cat_break(db, catalog):
    """({leaf: market break rate}, {leaf: market sales}) over all shops' settles and broken rows, by catalog leaf."""
    lf = {k: (c.get("category") or "").split(">")[-1] for k, c in catalog.items()}
    sold, broke = {}, {}
    for sku, n in db.execute("SELECT sku, COUNT(*) FROM settles GROUP BY sku"):
        if sku in lf:
            sold[lf[sku]] = sold.get(lf[sku], 0) + n
    for sku, n in db.execute("SELECT sku, COUNT(*) FROM broken GROUP BY sku"):
        if sku in lf:
            broke[lf[sku]] = broke.get(lf[sku], 0) + n
    return {k: round(broke.get(k, 0) / n, 4) for k, n in sold.items() if n}, sold


def warranty(u, case, base_h, stats, r=None):
    """Warranty hours for a unit over min_cost, or None when this rule does not decide (rule off / not over 1.5M)."""
    r = rules() if r is None else r
    if not is_top(u.get("cost"), r):
        return None
    w = r.get("warranty") or {}
    if case != "normal" or u.get("kind") == "food" or u.get("grade") not in w.get("grades", ["A"]):
        return 0
    lf = leaf(u)
    rate, n = (stats.get("cat_break") or {}).get(lf), (stats.get("cat_n") or {}).get(lf, 0)
    if rate is None or n < w.get("min_n", 30) or rate > w.get("max_break", 0.06):
        return 0
    from depts import sofa
    if sofa.applies(u):                              # an A grade sofa over 1.5M: the sofa rule's hours (72 h or none)
        return sofa.warranty_for(u)
    return base_h


def log_line(u, h, stats):
    lf = leaf(u)
    return (f"top high {u.get('sku')} grade {u.get('grade')} cost {int(u.get('cost') or 0):,}: {lf} market break "
            f"{(stats.get('cat_break') or {}).get(lf)} (n {(stats.get('cat_n') or {}).get(lf, 0)}) -> warranty {h} h "
            f"at {time.strftime('%H:%M')}")
