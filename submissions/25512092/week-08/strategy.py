"""Which case the shop and the buyer are in, and the rules each case turns on. restock.py calls tick() every
minute; the case is decided at most every CASE_EVERY_S and stored in market.db (table cases).

  shop case (first match wins)
    endgame    from 48 h before the round ends    floor: endgame markdown (pricing.endgame), restock from
                                                   normal rules until 36 h before the end, then none
    cash_low   cash < CASH_RESERVE (1.5M)          floor: cost; no restock (warning in the log under 1M)
    overstock  stock at cost >= STOCK_CAP (2.5M)   floor: cost, or the aging markdown when lower; no restock
    normal     otherwise                           floor: max(cost, market average); restock with the
                                                   low/high split; selective 48 h warranty
    always on: food clearance (the lower floor wins) and answers to '구합니다' posts (forum_post.py)

  buyer case
    endgame    from 24 h before the end            cap = budget (the market's mandate still limits it)
    normal     otherwise                           cap = min(budget, market average); SKU by expected
                                                   surplus; C-grade goods only with a warranty; shop score
"""
import time

import pricing
from market_db import connect, meta

CASH_RESERVE = 1_500_000
CASH_WARN = 1_000_000
STOCK_CAP = 2_500_000
CASE_EVERY_S = 300
BUYER_ENDGAME_H = 24
WARRANTY_H = 48
WARRANTY_MAX_BREAK = 0.05
WARRANTY_MIN_N = 5          # the SKU needs this many market sales before its break rate counts


def shop_case(inv, now=None):
    now = now or time.time()
    if pricing.endgame_step(now) is not None:
        return "endgame"
    if inv.get("balance", 0) < CASH_RESERVE:
        return "cash_low"
    if pricing.held_cost(inv) >= STOCK_CAP:
        return "overstock"
    return "normal"


def buyer_case(now=None):
    return "endgame" if (now or time.time()) >= pricing.ROUND_END - BUYER_ENDGAME_H * 3600 else "normal"


def current(inv=None):
    """(shop case, buyer case): the last one decided, or decided now from inventory.json when there is none."""
    db = connect()
    try:
        row = db.execute("SELECT shop_case, buyer_case, ts FROM cases ORDER BY ts DESC LIMIT 1").fetchone()
    finally:
        db.close()
    if row and time.time() - row[2] < 3 * CASE_EVERY_S:
        return row[0], row[1]
    inv = inv if inv is not None else pricing.load_inventory()
    return shop_case(inv), buyer_case()


def tick(inv, log=print):
    db = connect()
    try:
        now = time.time()
        if now - float(meta(db, "case_ts", 0)) < CASE_EVERY_S:
            return
        sc, bc = shop_case(inv, now), buyer_case(now)
        cash, stock = int(inv.get("balance", 0)), pricing.held_cost(inv)
        prev = db.execute("SELECT shop_case, buyer_case FROM cases ORDER BY ts DESC LIMIT 1").fetchone()
        db.execute("INSERT INTO cases VALUES (?,?,?,?,?)", (now, sc, bc, cash, stock))
        db.execute("INSERT OR REPLACE INTO meta VALUES ('case_ts', ?)", (str(now),))
        db.commit()
        change = "" if prev == (sc, bc) else f" (was {prev[0]}/{prev[1]})" if prev else " (first)"
        log(f"[case] shop {sc}, buyer {bc}{change}: cash {cash:,}, stock at cost {stock:,}")
        if cash < CASH_WARN:
            log(f"WARNING cash {cash:,} < {CASH_WARN:,}")
    finally:
        db.close()


def warranty_hours(u, case, stats):
    """[16] 48 h for A-grade goods whose market break rate is known and at most 5%, in the normal case only."""
    if case != "normal" or u.get("kind") == "food" or u.get("grade") != "A":
        return 0
    if (stats.get("sku_n") or {}).get(u["sku"], 0) < WARRANTY_MIN_N:
        return 0
    if (stats.get("sku_break") or {}).get(u["sku"], 0) > WARRANTY_MAX_BREAK:
        return 0
    return WARRANTY_H
