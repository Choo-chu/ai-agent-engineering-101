"""Restock hook — the kit runs it every 60 s in Round 3:  python restock.py --state .market

1. Refreshes market.db / market_stats.json (at most once per 5 minutes, market_db.REFRESH_S).
2. Records the units my shop holds in market.db (my_stock: cost and the market average when they arrived).
3. Buys more of what sells fast across the market: SKUs ranked by units sold in the last 5 and 30 minutes,
   kept only when the market average is above the expected supply cost (the shop sells at or above
   the market average, see seller_r3.py), so every sale should make money.
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
from market_db import load_stats, price_of, record_cash, record_stock, refresh  # noqa: E402

COST_SHARE = {"goods": 0.60, "food": 0.50}   # expected cost / list price, averaged over the grade draw
MIN_MARGIN = 0.10      # market average must beat the expected cost by 10%
MIN_SOLD_30M = 3       # market-wide units sold in 30 min to count as "selling"
MY_SHARE = 0.25        # share of the market's sales I plan stock for, until the next window (20 min)
MAX_QTY = 20
SPEND_SHARE = 0.4      # at most this share of the spendable balance per run
CUSHION = 1_000_000    # never spend below this balance; under it restock stops entirely
FOOD_MIN_SHELF_H = 24  # food must last at least this long on the shelf
MAX_BREAK = 0.15       # skip goods that break this often after a sale
WANTED_QTY = 3         # units of a SKU buyers asked for on the forum, even when it is not selling fast yet
MAX_STOCK_COST = 1_500_000   # never hold more than this much stock at cost (11/05: the shop was offline for
                             # 7 h while restock kept buying, and 4.1M of the 5M start sat on the shelf)
MAX_UNIT_COST = 100_000      # skip big-ticket SKUs: one unsold mattress ties up a third of a day's budget


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
    if inv.get("balance", 0) < CUSHION:
        log(f"WARNING cash {inv.get('balance', 0):,} < {CUSHION:,}: restock stopped until sales bring it back")
    try:
        forum_post.run(state, inv, catalog, log=log)
    except Exception as e:
        log(f"forum post failed: {e}")

    if inv.get("balance", 0) < CUSHION:
        print(json.dumps({"buy": []}))
        return
    r = inv.get("restock") or {}
    now = time.time()
    if not r.get("open") and (r.get("opens_at") or now) - now > 60:
        print(json.dumps({"buy": []}))           # window not open soon: nothing to plan yet
        return

    held = {}
    for u in units:
        if u.get("grade") != "expired":
            held[u["sku"]] = held.get(u["sku"], 0) + 1
    surge = {s["sku"]: s.get("factor", 1.0) for s in (inv.get("surge") or []) if isinstance(s, dict)}
    stats = load_stats()
    held_cost = sum(u.get("cost", 0) for u in units if u.get("grade") != "expired")
    spend_left = min(max(0, (inv.get("balance", 0) - CUSHION)) * SPEND_SHARE, MAX_STOCK_COST - held_cost)
    if spend_left <= 0:
        log(f"stock at cost {held_cost:,} >= cap {MAX_STOCK_COST:,} (or balance under cushion): no restock")
        print(json.dumps({"buy": []}))
        return

    wanted_cats = set(stats.get("wanted_cats", []))
    wanted = set(stats.get("wanted", [])) | {k for k in stats["skus"]
                                            if (catalog.get(k) or {}).get("category", "").split(">")[-1] in wanted_cats}
    plan = []
    for sku in list(stats.get("hot", [])) + sorted(wanted - set(stats.get("hot", []))):
        s = stats["skus"].get(sku)
        if not s:
            continue
        forum = sku in wanted
        c = catalog.get(sku) or {}
        avg, n = price_of(sku, stats)
        if avg is None or (s["sold_30m"] < MIN_SOLD_30M and not forum) or not c.get("list_price"):
            continue
        if stats.get("sku_break", {}).get(sku, 0) > MAX_BREAK:
            continue
        kind = c.get("kind", "goods")
        if kind == "food" and (c.get("shelf_hours") or 0) < FOOD_MIN_SHELF_H:
            continue
        cost = c["list_price"] * COST_SHARE.get(kind, 0.6) * surge.get(sku, 1.0)
        if cost > MAX_UNIT_COST or avg < cost * (1 + MIN_MARGIN):
            continue
        target = max(math.ceil(s["sold_30m"] * (20 / 30) * MY_SHARE), WANTED_QTY if forum else 0)
        qty = min(MAX_QTY, target - held.get(sku, 0))
        if qty <= 0:
            continue
        qty = min(qty, int(spend_left // cost))
        if qty <= 0:
            continue
        spend_left -= qty * cost
        plan.append({"sku": sku, "qty": qty})
        log(f"{s['name'] or sku}: sold {s['sold_5m']}/5m {s['sold_30m']}/30m, avg {avg}, est. cost {int(cost)}, "
            f"held {held.get(sku, 0)}{' (wanted on forum)' if forum else ''} -> buy {qty}")
        if len(plan) == 10:
            break
    print(json.dumps({"buy": plan}))


if __name__ == "__main__":
    main()
