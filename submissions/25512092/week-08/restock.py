"""Restock hook — the kit runs it every 60 s in Round 3:  python restock.py --state .market

1. Refreshes market.db / market_stats.json (at most once per 5 minutes, market_db.REFRESH_S).
2. Records the units my shop holds in market.db (my_stock: cost and the market average when they arrived).
3. Cash snapshot (market_db.record_cash), hourly/daily sales reports (sales_report.py), forum posts (forum_post.py).
4. Buys more of what sells fast across the market, only from cash above CUSHION, only while stock at cost is
   under MAX_STOCK_COST, never in the last 36 h of the round. Low-price SKUs (unit cost <= 100k) as before;
   high-price SKUs (100k-500k) in busy categories, one unit each, within the policy's share and unit cap.
Last line: {"buy": [{"sku": ..., "qty": ...}, ...]} (the kit buys at most 10 lines per run).
"""
import argparse
import json
import math
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import decisions  # noqa: E402
import forum_post  # noqa: E402
import pricing  # noqa: E402
import strategy  # noqa: E402
import sales_report  # noqa: E402
from market_db import ME, connect, load_stats, price_of, record_cash, record_stock, refresh  # noqa: E402
from sales_report import HIGH_MAX, HIGH_MIN  # noqa: E402

COST_SHARE = {"goods": 0.60, "food": 0.50}   # expected cost / list price, averaged over the grade draw
MIN_MARGIN = 0.10      # market average must beat the expected cost by 10%
MIN_SOLD_30M = 3       # market-wide units sold in 30 min to count as "selling"
MY_SHARE = 0.25        # share of the market's sales I plan stock for, until the next window (20 min)
from limits import MAX_LINES, MAX_QTY  # noqa: E402  hard limits (limits.py)
SPEND_SHARE = 0.4      # at most this share of the spendable balance per run
CUSHION = strategy.CASH_RESERVE    # 1.5M: restock spends only (cash - CUSHION); under it the case is cash_low
FOOD_MIN_SHELF_H = 24  # food must last at least this long on the shelf
MAX_BREAK = 0.15       # skip goods that break this often after a sale
WANTED_QTY = 3         # units of a SKU buyers asked for on the forum, even when it is not selling fast yet
TRIAL_MARKET_30M, TRIAL_QTY = 3, 2   # '부패주의' with none held and none of my sales: trial buy when the market sold >= 3
MAX_STOCK_COST = strategy.STOCK_CAP  # 4.0M: at or over it the case is overstock (11/05: the shop was offline
                                      # 7 h while restock kept buying, and 4.1M of the 5M start sat on the shelf)
# unit cost <= HIGH_MIN is low price; HIGH_MIN..HIGH_MAX is high price, bought only in busy categories, with
# its share of the budget and its unit cap from sales_report.policy() (30% and 2 at the start, adjusted daily)


def log(msg):
    print(f"[restock] {msg}", flush=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--state", default=".market")
    state = ap.parse_args().state
    try:
        refresh(log=log)
    except Exception as e:
        log(f"market_db refresh failed: {e}")
    try:
        with open(os.path.join(state, "inventory.json"), encoding="utf-8") as f:
            inv = json.load(f)
        with open(os.path.join(state, "catalog.json"), encoding="utf-8") as f:
            catalog = json.load(f)
    except (OSError, ValueError) as e:
        log(f"no inventory/catalog yet: {e}")
        print(json.dumps({"buy": []}))
        return
    units = inv.get("units", [])
    try:
        record_stock(units, log=log)
    except Exception as e:
        log(f"record_stock failed: {e}")

    try:
        record_cash(inv, log=log)
    except Exception as e:
        log(f"record_cash failed: {e}")
    try:
        strategy.tick(inv, log=log)
    except Exception as e:
        log(f"strategy tick failed: {e}")
    try:
        sales_report.tick(inv, catalog, log=log)
    except Exception as e:
        log(f"sales report failed: {e}")
    try:
        forum_post.run(state, inv, catalog, log=log)
    except Exception as e:
        log(f"forum post failed: {e}")

    case = strategy.shop_case(inv)
    r = inv.get("restock") or {}
    now = time.time()
    soon = r.get("open") or (r.get("opens_at") or now) - now <= 60
    if case in ("cash_low", "overstock") or pricing.restock_stopped():
        if (inv.get("restock") or {}).get("open"):
            log(f"case {case}{', last 36 h' if pricing.restock_stopped() else ''}: no restock")
            decisions.record("purchasing", "no_restock", case, 0, f"shop case {case}"
                             + (", last 36 h" if pricing.restock_stopped() else ""), limit_hit={"overstock": "STOCK_CAP", "cash_low": "CASH_RESERVE"}.get(case, "RESTOCK_STOP_H"))
        if case == "overstock" and not pricing.restock_stopped() and soon:
            safe(cap_record, inv, units, catalog, 0, [], case)    # log only: what the cap kept from buying
        print(json.dumps({"buy": []}))
        return
    if not soon:
        print(json.dumps({"buy": []}))           # window not open soon: nothing to plan yet
        return

    held_cost = pricing.held_cost(inv)
    budget = min((inv.get("balance", 0) - CUSHION) * SPEND_SHARE, MAX_STOCK_COST - held_cost)
    if budget <= 0:
        log(f"cash {inv.get('balance', 0):,} leaves nothing above the {CUSHION:,} reserve: no restock")
        decisions.record("purchasing", "no_restock", case, 0, f"budget {int(budget):,}: cash "
                         f"{inv.get('balance', 0):,}, stock at cost {held_cost:,}", limit_hit="CASH_RESERVE/STOCK_CAP")
        safe(cap_record, inv, units, catalog, 0, [], case)
        print(json.dumps({"buy": []}))
        return
    lines = []

    def plan_log(m):
        log(m)
        lines.append(m)
    plan = make_plan(inv, units, catalog, budget, plan_log)
    for m in lines:                                  # one decision per planned / skipped / merged line
        kind = "dedup" if m.startswith("[dedup]") else "skip" if m.endswith("-> skip") else "buy" if " -> buy " in m else None
        if kind:
            decisions.record("purchasing", kind, m.split(":")[0][:60], m.rsplit("-> ", 1)[-1], m[:300])
    safe(cap_record, inv, units, catalog, budget, plan, case)
    print(json.dumps({"buy": plan}))


def safe(fn, *a):
    """Logging helpers must never cost the run its buy line."""
    try:
        fn(*a)
    except Exception as e:
        log(f"{fn.__name__} failed: {e}")


def make_plan(inv, units, catalog, budget, log):
    """The buy lines for this budget (unchanged rules; moved out of main so cap_record can run it without the cap)."""
    held, held_high = {}, 0
    for u in units:
        if u.get("grade") != "expired":
            held[u["sku"]] = held.get(u["sku"], 0) + 1
            held_high += u.get("cost", 0) > HIGH_MIN
    surge = {s["sku"]: s.get("factor", 1.0) for s in (inv.get("surge") or []) if isinstance(s, dict)}
    stats = load_stats()
    pol = sales_report.policy()
    left = {"high": budget * pol["high_share"], "low": budget * (1 - pol["high_share"])}
    high_room = max(0, pol["high_max"] - held_high)
    hot_cats = busy_categories(catalog)
    log(f"budget {int(budget):,}: low {int(left['low']):,} / high {int(left['high']):,} "
        f"({pol['high_share']:.0%}), high-price units {held_high}/{pol['high_max']}, busy categories {hot_cats}")

    wanted_cats = set(stats.get("wanted_cats", []))
    wanted = set(stats.get("wanted", [])) | {k for k in stats["skus"]
                                            if (catalog.get(k) or {}).get("category", "").split(">")[-1] in wanted_cats}
    hot = list(stats.get("hot", []))
    rest = sorted(set(stats["skus"]) - set(hot), key=lambda k: -stats["skus"][k]["sold_30m"])
    plan, line_of = [], {}                       # line_of: sku -> (index in plan, the list it came from)
    order = [(k, "hot") for k in hot] + [(k, "wanted") for k in sorted(wanted - set(hot))] + [(k, "rest") for k in rest]
    for sku, src in order:                       # a wanted SKU is also in rest: one line per SKU (see [dedup])
        s = stats["skus"].get(sku)
        c = catalog.get(sku) or {}
        if not s or not c.get("list_price"):
            continue
        forum = sku in wanted
        avg, n = price_of(sku, stats)
        if avg is None or stats.get("sku_break", {}).get(sku, 0) > MAX_BREAK:
            continue
        kind = c.get("kind", "goods")
        if kind == "food" and (c.get("shelf_hours") or 0) < FOOD_MIN_SHELF_H:
            continue
        cost = c["list_price"] * COST_SHARE.get(kind, 0.6) * surge.get(sku, 1.0)
        if cost > HIGH_MAX or avg < cost * (1 + MIN_MARGIN):
            continue
        if cost > HIGH_MIN:                       # high price: a busy category, one unit, within the cap
            if (c.get("category") or "").split(">")[-1] not in hot_cats or s["sold_30m"] < 1 or held.get(sku):
                continue
            tier, qty = "high", min(1, high_room)
        else:                                     # low price: as before, hot or wanted on the forum
            if sku not in hot and not forum or (s["sold_30m"] < MIN_SOLD_30M and not forum):
                continue
            target = max(math.ceil(s["sold_30m"] * (20 / 30) * MY_SHARE), WANTED_QTY if forum else 0)
            tier, qty = "low", min(MAX_QTY, target - held.get(sku, 0))
        qty = min(qty, int(left[tier] // cost))
        rot = ""
        if sales_report.perishable(c):            # '부패주의': at most what my shop sold of it in the last 30 min
            mine, planned = my_sold_30m(sku), qty
            if mine == 0 and held.get(sku, 0) == 0 and s["sold_30m"] >= TRIAL_MARKET_30M:
                rule, qty = "trial", min(TRIAL_QTY, int(left[tier] // cost))   # none held, the market sells it
            else:
                rule, qty = "my sales", min(qty, mine)
            rot = (f", perishable rule '{rule}' (my sales 30m {mine}, held {held.get(sku, 0)}, "
                   f"market 30m {s['sold_30m']}, planned {planned} -> {max(qty, 0)})")
            if qty <= 0:
                log(f"[{tier}] {s['name'] or sku}: est. cost {int(cost)}{rot} -> skip")
        if qty <= 0:
            continue
        if sku in line_of:                        # second time this run: keep one line, the larger qty
            i, first = line_of[sku]
            q1 = plan[i]["qty"]
            q = max(q1, qty)
            log(f"[dedup] {sku} {first} {q1} / {src} {qty} -> {q}")
            left[tier] -= (q - q1) * cost
            if tier == "high":
                high_room -= q - q1
            plan[i]["qty"] = q
            continue
        line_of[sku] = (len(plan), src)
        left[tier] -= qty * cost
        if tier == "high":
            high_room -= qty
        plan.append({"sku": sku, "qty": qty})
        log(f"[{tier}] {s['name'] or sku}: sold {s['sold_5m']}/5m {s['sold_30m']}/30m, avg {avg}, est. cost {int(cost)}, "
            f"held {held.get(sku, 0)}{' (wanted on forum)' if forum else ''}{rot} -> buy {qty}")
        if len(plan) == MAX_LINES:
            break
    return plan


def cap_record(inv, units, catalog, budget, plan, case):
    """Log only, buying is not changed: when STOCK_CAP blocked or cut this run, the budget and the buy lines
    without the cap (same rules, quiet), into the log ([cap]) and market.db cap_runs (for the daily report)."""
    cash, stock = int(inv.get("balance", 0)), int(pricing.held_cost(inv))
    free = (cash - CUSHION) * SPEND_SHARE                   # the budget without the cap
    if free <= 0 or free <= budget + 1:
        return                                              # the cap did not bind: cash did, or nothing
    try:
        free_plan = make_plan(inv, units, catalog, free, lambda m: None)
    except Exception as e:
        log(f"[cap] plan without the cap failed: {e}")
        free_plan = []
    names = {k: (catalog.get(k) or {}).get("name") or k for k in [p["sku"] for p in free_plan]}
    mine, free_qty = {}, {}                                 # a SKU can sit on two lines (wanted + rest): add up
    for p in plan:
        mine[p["sku"]] = mine.get(p["sku"], 0) + p["qty"]
    for p in free_plan:
        free_qty[p["sku"]] = free_qty.get(p["sku"], 0) + p["qty"]
    extra = [(k, q - mine.get(k, 0)) for k, q in free_qty.items() if q > mine.get(k, 0)]
    log(f"[cap] case {case}, cash {cash:,}, stock at cost {stock:,}: budget without the cap {int(free):,} vs "
        f"actual {int(max(budget, 0)):,}; without the cap would also buy: "
        + (", ".join(f"{names[k][:24]} x{q}" for k, q in extra) or "nothing more"))
    decisions.record("purchasing", "cap", case, {"budget_free": int(free), "budget": int(max(budget, 0)),
                                                 "extra": dict(extra)},
                     f"cash {cash:,}, stock at cost {stock:,}", limit_hit="STOCK_CAP")
    db = connect()
    try:
        db.execute("CREATE TABLE IF NOT EXISTS cap_runs (ts REAL PRIMARY KEY, shop_case TEXT, cash INTEGER, "
                   "stock_cost INTEGER, budget_free INTEGER, budget INTEGER, plan_free TEXT, plan TEXT)")
        db.execute("INSERT OR REPLACE INTO cap_runs VALUES (?,?,?,?,?,?,?,?)",
                   (time.time(), case, cash, stock, int(free), int(max(budget, 0)),
                    json.dumps(free_plan), json.dumps(plan)))
        db.commit()
    finally:
        db.close()


def my_sold_30m(sku):
    """Units of this SKU my shop sold in the last 30 minutes (settles, refreshed every 5 min)."""
    db = connect()
    try:
        return db.execute("SELECT COUNT(*) FROM settles WHERE shop=? AND sku=? AND ts>=?",
                          (ME, sku, time.time() - 1800)).fetchone()[0]
    finally:
        db.close()


def busy_categories(catalog, top=5):
    """The leaf categories with the most settles in the last 2 hours, market-wide."""
    db = connect()
    try:
        rows = db.execute("SELECT sku, COUNT(*) FROM settles WHERE ts>=? GROUP BY sku", (time.time() - 7200,)).fetchall()
    finally:
        db.close()
    cats = {}
    for sku, n in rows:
        leaf = ((catalog.get(sku) or {}).get("category") or "").split(">")[-1]
        if leaf:
            cats[leaf] = cats.get(leaf, 0) + n
    return sorted(cats, key=cats.get, reverse=True)[:top]


if __name__ == "__main__":
    main()
