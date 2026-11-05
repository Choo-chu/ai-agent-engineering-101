"""Which case the shop and the buyer are in, and the rules each case turns on. restock.py calls tick() every
minute; the case is decided at most every CASE_EVERY_S and stored in market.db (table cases).

  shop case (first match wins)
    endgame    from 48 h before the round ends    floor: endgame markdown (pricing.endgame), restock from
                                                   normal rules until 36 h before the end, then none
    cash_low   cash < CASH_RESERVE (1.5M)          floor: cost; no restock (warning in the log under 1M)
    overstock  stock at cost >= STOCK_CAP (2.5M)   floor: cost, or the aging markdown when lower; no restock
               (hysteresis: it ends only when stock falls under STOCK_EXIT, 2.2M)
    normal     otherwise                           floor: max(cost, market average); restock with the
                                                   low/high split; selective 48 h warranty
    always on: food clearance (the lower floor wins) and answers to '구합니다' posts (forum_post.py)

  A case holds at least MIN_HOLD_S (30 min) after it changes, except that entering endgame or cash_low happens
  at once. decide() is the one place that picks a case; everything else reads it through current().

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
STOCK_EXIT = 2_200_000      # overstock ends only under this
MIN_HOLD_S = 30 * 60
IMMEDIATE = ("endgame", "cash_low")
CASE_EVERY_S = 300
BUYER_ENDGAME_H = 24
WARRANTY_H = 48
WARRANTY_MAX_BREAK = 0.05
WARRANTY_MIN_N = 5          # the SKU needs this many market sales before its break rate counts


def raw_shop_case(inv, now, prev=None):
    """(case, reason) from the numbers alone, with the overstock hysteresis."""
    cash, stock = inv.get("balance", 0), pricing.held_cost(inv)
    if pricing.endgame_step(now) is not None:
        return "endgame", "48 h before the end"
    if cash < CASH_RESERVE:
        return "cash_low", f"cash {cash:,} < {CASH_RESERVE:,}"
    if stock >= STOCK_CAP:
        return "overstock", f"stock {stock:,} >= {STOCK_CAP:,}"
    if prev == "overstock" and stock >= STOCK_EXIT:
        return "overstock", f"stock {stock:,} still >= {STOCK_EXIT:,} (hysteresis)"
    return "normal", f"stock {stock:,}, cash {cash:,}"


def raw_buyer_case(now):
    if now >= pricing.ROUND_END - BUYER_ENDGAME_H * 3600:
        return "endgame", "24 h before the end"
    return "normal", "before the last 24 h"


def hold(prev, since, new, reason, now):
    """Keep prev for MIN_HOLD_S after it began, unless new is endgame / cash_low."""
    if prev is None or new == prev:
        return new, reason
    if new not in IMMEDIATE and now - since < MIN_HOLD_S:
        return prev, f"{reason}, but {prev} holds until {MIN_HOLD_S // 60} min ({(now - since) / 60:.0f} min so far)"
    return new, reason


def decide(inv, now, state):
    """state: {"shop": case, "shop_since": ts, "buyer": case, "buyer_since": ts} (empty at first).
    Returns ((shop case, reason), (buyer case, reason))."""
    sc, sr = raw_shop_case(inv, now, state.get("shop"))
    bc, br = raw_buyer_case(now)
    return (hold(state.get("shop"), state.get("shop_since", 0), sc, sr, now),
            hold(state.get("buyer"), state.get("buyer_since", 0), bc, br, now))


def load_state(db):
    v = meta(db, "case_state")
    if v:
        return __import__("json").loads(v)
    row = db.execute("SELECT shop_case, buyer_case, ts FROM cases ORDER BY ts DESC LIMIT 1").fetchone()
    return {"shop": row[0], "shop_since": row[2], "buyer": row[1], "buyer_since": row[2]} if row else {}


def current(inv=None):
    """(shop case, buyer case): the last decided one; between ticks nothing changes. With no decision yet
    (or one older than 15 min), decide now from inventory.json without storing it."""
    db = connect()
    try:
        row = db.execute("SELECT shop_case, buyer_case, ts FROM cases ORDER BY ts DESC LIMIT 1").fetchone()
        state = load_state(db)
    finally:
        db.close()
    if row and time.time() - row[2] < 3 * CASE_EVERY_S:
        return row[0], row[1]
    inv = inv if inv is not None else pricing.load_inventory()
    (sc, _), (bc, _) = decide(inv, time.time(), state)
    return sc, bc


def shop_case(inv, now=None):
    return current(inv)[0]


def buyer_case(now=None):
    return current()[1]


def tick(inv, log=print):
    import json
    db = connect()
    try:
        now = time.time()
        if now - float(meta(db, "case_ts", 0)) < CASE_EVERY_S:
            return
        st = load_state(db)
        (sc, sr), (bc, br) = decide(inv, now, st)
        cash, stock = int(inv.get("balance", 0)), pricing.held_cost(inv)
        for role, new, why in (("shop", sc, sr), ("buyer", bc, br)):
            old = st.get(role)
            if old != new:
                held = f", {old} held {(now - st.get(role + '_since', now)) / 60:.0f} min" if old else ""
                log(f"[case] {role} {old or '-'} -> {new}: {why}{held}")
                st[role], st[role + "_since"] = new, now
        db.execute("INSERT INTO cases VALUES (?,?,?,?,?,?)", (now, sc, bc, cash, stock, f"{sr} | {br}"))
        db.execute("INSERT OR REPLACE INTO meta VALUES ('case_ts', ?)", (str(now),))
        db.execute("INSERT OR REPLACE INTO meta VALUES ('case_state', ?)", (json.dumps(st),))
        db.commit()
        log(f"[case] shop {sc} ({sr}), buyer {bc}: cash {cash:,}, stock at cost {stock:,}")
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
    "buyer_min_offers": ["1", "3"],                   # counteroffers before the buyer may accept or walk
}
BUYER_COLUMN = {"buyer_normal_first": "variant", "buyer_min_offers": "mo_variant"}
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
        col = BUYER_COLUMN[key]
        rows = db.execute(
            f"SELECT d.{col}, d.list_price, (SELECT s.amount FROM settles s WHERE s.buyer=? AND s.sku=d.sku "
            f"AND s.ts BETWEEN d.ts - 60 AND d.ts + 900 ORDER BY s.ts LIMIT 1) FROM buyer_deals d "
            f"WHERE d.{col} IS NOT NULL AND d.buyer_case='normal' AND d.outcome != 'skip'", (ME_NAME,)).fetchall()
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
