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
from market_db import ME as ME_NAME, connect, meta

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
    adjust(log)


def warranty_hours(u, case, stats):
    """[16] 48 h for A-grade goods whose market break rate is known and at most 5%, in the normal case only."""
    if case != "normal" or u.get("kind") == "food" or u.get("grade") != "A":
        return 0
    if (stats.get("sku_n") or {}).get(u["sku"], 0) < WARRANTY_MIN_N:
        return 0
    if (stats.get("sku_break") or {}).get(u["sku"], 0) > WARRANTY_MAX_BREAK:
        return 0
    return WARRANTY_H


# --- stage 2: variants inside a case, chosen by weight per negotiation, compared every 3 hours

VARIANTS = {
    "shop_normal_ask": ["1.00", "1.05", "1.10"],      # first ask = market average x variant (normal case)
    "shop_overstock_floor": ["1.00", "0.95"],         # floor = cost x variant (overstock case)
    "buyer_normal_first": ["0.50", "0.60", "0.70"],   # first offer = ask x variant (buyer normal case)
}
ADJUST_EVERY_S = 3 * 3600
MIN_SAMPLES = 10        # every variant of a key needs this many negotiations before its weights move
WEIGHT_STEP = 0.10
MIN_WEIGHT = 0.20
OPEN_TIMEOUT_S = 900    # a shop negotiation still open after 15 min counts as lost


def weights(db, key):
    w = {}
    for v, wt in db.execute("SELECT variant, weight FROM variant_weights WHERE key=? ORDER BY ts", (key,)):
        w[v] = wt
    if set(w) != set(VARIANTS[key]):
        w = {v: round(1 / len(VARIANTS[key]), 4) for v in VARIANTS[key]}
        now = time.time()
        for v, wt in w.items():
            db.execute("INSERT INTO variant_weights VALUES (?,?,?,?,?,?,?)", (now, key, v, wt, None, 0, "start"))
        db.commit()
    return w


def pick(key):
    import random
    db = connect()
    try:
        w = weights(db, key)
    finally:
        db.close()
    v = random.choices(list(w), weights=list(w.values()))[0]
    return v, w


def performance(db, key, now=None):
    """{variant: (negotiations, metric)}; metric = profit (shop) or surplus (buyer) summed over all negotiations
    of the variant / their number, i.e. per-deal profit x success rate."""
    now = now or time.time()
    out = {v: [0, 0.0] for v in VARIANTS[key]}
    if key.startswith("shop"):
        rows = db.execute(
            "SELECT d.variant, d.cost, (SELECT s.amount FROM settles s WHERE s.unit=d.unit AND s.ts>=d.ts - 60 "
            "ORDER BY s.ts LIMIT 1) FROM shop_deals d WHERE d.variant_key=? AND (d.outcome!='open' OR d.ts<?)",
            (key, now - OPEN_TIMEOUT_S)).fetchall()
        for v, cost, amount in rows:
            if v in out:
                out[v][0] += 1
                out[v][1] += (amount - cost) if amount is not None else 0
    else:
        rows = db.execute(
            "SELECT d.variant, d.list_price, (SELECT s.amount FROM settles s WHERE s.buyer=? AND s.sku=d.sku "
            "AND s.ts BETWEEN d.ts - 60 AND d.ts + 900 ORDER BY s.ts LIMIT 1) FROM buyer_deals d "
            "WHERE d.variant_key=?", (ME_NAME, key)).fetchall()
        for v, lp, amount in rows:
            if v in out:
                out[v][0] += 1
                out[v][1] += (lp - amount) if amount is not None and lp else 0
    return {v: (n, round(total / n, 1) if n else None) for v, (n, total) in out.items()}


def adjust(log=print, force=False):
    db = connect()
    try:
        now = time.time()
        last = meta(db, "variant_adjust_ts")
        if last is None:
            db.execute("INSERT OR REPLACE INTO meta VALUES ('variant_adjust_ts', ?)", (str(now),))
            db.commit()
            return
        if not force and now - float(last) < ADJUST_EVERY_S:
            return
        db.execute("INSERT OR REPLACE INTO meta VALUES ('variant_adjust_ts', ?)", (str(now),))
        for key in VARIANTS:
            w, perf = weights(db, key), performance(db, key, now)
            short = {v: n for v, (n, _) in perf.items() if n < MIN_SAMPLES}
            if short:
                log(f"[variant] {key}: waiting, negotiations per variant {dict((v, n) for v, (n, _) in perf.items())}"
                    f" (need {MIN_SAMPLES} each)")
                continue
            ranked = sorted(perf, key=lambda v: perf[v][1])
            worst, best = ranked[0], ranked[-1]
            move = min(WEIGHT_STEP, max(0.0, w[worst] - MIN_WEIGHT))
            w[worst] = round(w[worst] - move, 4)
            w[best] = round(w[best] + move, 4)
            reason = f"best {best} ({perf[best][1]}), worst {worst} ({perf[worst][1]}), moved {move:.2f}"
            for v in VARIANTS[key]:
                db.execute("INSERT INTO variant_weights VALUES (?,?,?,?,?,?,?)",
                           (now, key, v, w[v], perf[v][1], perf[v][0], reason))
            log(f"[variant] {key}: {reason} -> weights {w}")
        db.commit()
    finally:
        db.close()
