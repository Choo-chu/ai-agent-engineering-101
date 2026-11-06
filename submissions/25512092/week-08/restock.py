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
MAX_QTY = 20
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
    if case in ("cash_low", "overstock") or pricing.restock_stopped():
        if (inv.get("restock") or {}).get("open"):
            log(f"case {case}{', last 36 h' if pricing.restock_stopped() else ''}: no restock")
        print(json.dumps({"buy": []}))
        return
    r = inv.get("restock") or {}
    now = time.time()
    if not r.get("open") and (r.get("opens_at") or now) - now > 60:
        print(json.dumps({"buy": []}))           # window not open soon: nothing to plan yet
        return

    held, held_high = {}, 0
    for u in units:
        if u.get("grade") != "expired":
            held[u["sku"]] = held.get(u["sku"], 0) + 1
            held_high += u.get("cost", 0) > HIGH_MIN
    surge = {s["sku"]: s.get("factor", 1.0) for s in (inv.get("surge") or []) if isinstance(s, dict)}
    stats = load_stats()
    held_cost = pricing.held_cost(inv)
    budget = min((inv.get("balance", 0) - CUSHION) * SPEND_SHARE, MAX_STOCK_COST - held_cost)
    if budget <= 0:
        log(f"cash {inv.get('balance', 0):,} leaves nothing above the {CUSHION:,} reserve: no restock")
        print(json.dumps({"buy": []}))
        return
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
    plan = []
    for sku in hot + sorted(wanted - set(hot)) + rest:
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
        left[tier] -= qty * cost
        if tier == "high":
            high_room -= qty
        plan.append({"sku": sku, "qty": qty})
        log(f"[{tier}] {s['name'] or sku}: sold {s['sold_5m']}/5m {s['sold_30m']}/30m, avg {avg}, est. cost {int(cost)}, "
            f"held {held.get(sku, 0)}{' (wanted on forum)' if forum else ''}{rot} -> buy {qty}")
        if len(plan) == 10:
            break
    print(json.dumps({"buy": plan}))


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
