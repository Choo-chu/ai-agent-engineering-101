"""Stage-2 experiments, run by the departments inside the CEO's policy: one variant per negotiation by weight
(sales: shop_normal_ask, shop_overstock_floor; buyer: buyer_normal_first, buyer_min_offers), weights moved every
3 hours toward the variant with the best profit (shop) or surplus (buyer) per negotiation."""
import time

from market_db import ME as ME_NAME, connect, meta


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
            __import__("decisions").record("buyer" if key.startswith("buyer") else "sales", "variant_weights", key,
                                           dict(w), reason)
        db.commit()
    finally:
        db.close()
