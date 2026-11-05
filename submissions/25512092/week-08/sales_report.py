"""My shop's sales reports and the low/high-price buying split. restock.py calls tick() every minute.

  hourly  after each full hour: sales, revenue, profit (price - unit cost from my_stock), profit / cost for
          low-price (unit cost <= HIGH_MIN) and high-price units, sales per category, stock at cost, cash
          -> market.db table hourly + one log line
  daily   after midnight: the day's totals, the 3 SKUs that made the most, the 3 slowest stock SKUs, broken /
          refunds -> reports/daily_YYYYMMDD.md, then adjust the split (policy table):
            high-price stock unsold > 24 h, or a refund on a high-price unit  -> high share -10 %p (min 20%)
            else high profit/cost >= low profit/cost (and some high sales)   -> high share +10 %p (max 50%),
                                                                                 high-price units held +1 (max 5)
"""
import json
import os
import time
from datetime import datetime, timedelta

from market_db import ME, connect, meta

HERE = os.path.dirname(os.path.abspath(__file__))
REPORTS = os.path.join(HERE, "reports")
HIGH_MIN = 100_000              # unit cost above this is "high price" ...
HIGH_MAX = 500_000              # ... up to this
START_SHARE, START_MAX = 0.30, 2
SHARE_STEP, SHARE_MIN, SHARE_CAP, MAX_CAP = 0.10, 0.20, 0.50, 5


def policy(db=None):
    own = db is None
    db = db or connect()
    try:
        row = db.execute("SELECT high_share, high_max FROM policy ORDER BY ts DESC LIMIT 1").fetchone()
        if row is None:
            db.execute("INSERT INTO policy VALUES (?,?,?,?)", (time.time(), START_SHARE, START_MAX, "start"))
            db.commit()
            row = (START_SHARE, START_MAX)
        return {"high_share": row[0], "high_max": row[1]}
    finally:
        if own:
            db.close()


def my_sales(db, t0, t1):
    """(seq, ts, sku, name, amount, cost) of my shop's settles in [t0, t1)."""
    return db.execute("""SELECT s.seq, s.ts, s.sku, s.name, s.amount, m.cost FROM settles s JOIN my_stock m ON m.unit=s.unit
                         WHERE s.ts>=? AND s.ts<? ORDER BY s.seq""", (t0, t1)).fetchall()


def summarize(rows, catalog):
    out = {"sales": len(rows), "revenue": 0, "profit": 0, "low_cost": 0, "low_profit": 0, "high_cost": 0,
           "high_profit": 0, "cats": {}}
    for _, _, sku, _, amount, cost in rows:
        out["revenue"] += amount
        out["profit"] += amount - cost
        tier = "high" if cost > HIGH_MIN else "low"
        out[f"{tier}_cost"] += cost
        out[f"{tier}_profit"] += amount - cost
        leaf = ((catalog.get(sku) or {}).get("category") or "?").split(">")[-1]
        out["cats"][leaf] = out["cats"].get(leaf, 0) + 1
    return out


def rate(profit, cost):
    return profit / cost if cost else None


def pct(x):
    return "-" if x is None else f"{100 * x:.0f}%"


def hourly(db, inv, catalog, log):
    now = time.time()
    hour = now // 3600 * 3600 - 3600                  # the last full hour (epoch hours line up with KST hours)
    done = meta(db, "hourly_done")                    # start of the next hour still to report
    if done is not None and hour < float(done):
        return
    s = summarize(my_sales(db, hour, hour + 3600), catalog)
    stock = sum(u.get("cost", 0) for u in inv.get("units", []) if u.get("grade") != "expired")
    cash = int(inv.get("balance", 0))
    db.execute("INSERT OR REPLACE INTO hourly VALUES (?,?,?,?,?,?,?,?,?,?,?)",
               (hour, s["sales"], s["revenue"], s["profit"], s["low_cost"], s["low_profit"], s["high_cost"],
                s["high_profit"], json.dumps(s["cats"], ensure_ascii=False), stock, cash))
    db.execute("INSERT OR REPLACE INTO meta VALUES ('hourly_done', ?)", (str(hour + 3600),))
    db.commit()
    cats = ", ".join(f"{k} {v}" for k, v in sorted(s["cats"].items(), key=lambda kv: -kv[1])[:4]) or "-"
    log(f"[report] {datetime.fromtimestamp(hour):%m-%d %H}:00 sold {s['sales']}, revenue {s['revenue']:,}, "
        f"profit {s['profit']:,} (low {pct(rate(s['low_profit'], s['low_cost']))}, "
        f"high {pct(rate(s['high_profit'], s['high_cost']))}), by category: {cats}; stock {stock:,}, cash {cash:,}")


def daily(db, inv, catalog, log):
    today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    day = today - timedelta(days=1)
    done = meta(db, "daily_done")
    if done is None:                                  # first run: start with the day in progress
        db.execute("INSERT OR REPLACE INTO meta VALUES ('daily_done', ?)", (day.strftime("%Y%m%d"),))
        db.commit()
        return
    if done >= day.strftime("%Y%m%d"):
        return
    t0, t1 = day.timestamp(), today.timestamp()
    rows = my_sales(db, t0, t1)
    s = summarize(rows, catalog)
    by_sku = {}
    for _, _, sku, name, amount, cost in rows:
        b = by_sku.setdefault(sku, {"name": name, "n": 0, "profit": 0})
        b["n"] += 1
        b["profit"] += amount - cost
    top = sorted(by_sku.items(), key=lambda kv: -kv[1]["profit"])[:3]
    now = time.time()
    held = {}
    for u in inv.get("units", []):
        if u.get("grade") != "expired":
            h = held.setdefault(u["sku"], {"name": u["name"], "n": 0, "cost": 0, "oldest": now})
            h["n"] += 1
            h["cost"] += u.get("cost", 0)
            h["oldest"] = min(h["oldest"], u.get("supplied_at") or now)
    slow = sorted(held.items(), key=lambda kv: kv[1]["oldest"])[:3]
    broken = db.execute("""SELECT b.seq, b.sku, b.hours_after_sale, b.refunded, m.cost FROM broken b
                           LEFT JOIN settles s ON s.sku=b.sku AND s.buyer=b.buyer AND s.shop=? LEFT JOIN my_stock m ON m.unit=s.unit
                           WHERE b.shop=? AND b.ts>=? AND b.ts<?""", (ME, ME, t0, t1)).fetchall()
    stock = sum(h["cost"] for h in held.values())
    lr, hr = rate(s["low_profit"], s["low_cost"]), rate(s["high_profit"], s["high_cost"])

    pol = policy(db)
    share, cap = pol["high_share"], pol["high_max"]
    stale_high = [u for u in inv.get("units", []) if u.get("grade") != "expired" and u.get("cost", 0) > HIGH_MIN
                  and now - (u.get("supplied_at") or now) > 24 * 3600]
    high_refund = [b for b in broken if b[3] and (b[4] or 0) > HIGH_MIN]
    if stale_high or high_refund:
        share = max(SHARE_MIN, round(share - SHARE_STEP, 2))
        reason = f"{len(stale_high)} high-price units unsold > 24 h, {len(high_refund)} high-price refunds"
    elif hr is not None and (lr is None or hr >= lr):
        share, cap = min(SHARE_CAP, round(share + SHARE_STEP, 2)), min(MAX_CAP, cap + 1)
        reason = f"high profit/cost {pct(hr)} >= low {pct(lr)}"
    else:
        reason = f"no change (high {pct(hr)}, low {pct(lr)})"
    db.execute("INSERT INTO policy VALUES (?,?,?,?)", (now, share, cap, f"{day:%Y-%m-%d}: {reason}"))

    lines = [f"# Choo Shop daily report {day:%Y-%m-%d}", "",
             f"- sales {s['sales']}, revenue {s['revenue']:,}, profit {s['profit']:,}",
             f"- profit / cost: low-price {pct(lr)} ({s['low_profit']:,} on {s['low_cost']:,}), "
             f"high-price {pct(hr)} ({s['high_profit']:,} on {s['high_cost']:,})",
             f"- stock at cost {stock:,}, cash {int(inv.get('balance', 0)):,}", "",
             "## Sales by category", ""] + \
            [f"- {k}: {v}" for k, v in sorted(s["cats"].items(), key=lambda kv: -kv[1])] + \
            ["", "## Top 3 SKUs by profit", ""] + \
            [f"- {v['name']} ({k}): {v['n']} sold, profit {v['profit']:,}" for k, v in top] + \
            ["", "## Slowest stock (oldest on the shelf)", ""] + \
            [f"- {v['name']} ({k}): {v['n']} units, {v['cost']:,} at cost, "
             f"{(now - v['oldest']) / 3600:.0f} h on the shelf" for k, v in slow] + \
            ["", "## Broken / refunds", ""] + \
            ([f"- ledger #{b[0]} {b[1]}: broke {b[2]:.1f} h after sale, refunded {bool(b[3])}" for b in broken] or ["- none"]) + \
            ["", "## Buying split", "", f"- high-price share {pol['high_share']:.0%} -> {share:.0%}, "
             f"high-price units held at most {pol['high_max']} -> {cap} ({reason})", ""]
    os.makedirs(REPORTS, exist_ok=True)
    path = os.path.join(REPORTS, f"daily_{day:%Y%m%d}.md")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    db.execute("INSERT OR REPLACE INTO meta VALUES ('daily_done', ?)", (day.strftime("%Y%m%d"),))
    db.commit()
    log(f"[report] daily {day:%Y-%m-%d}: sold {s['sales']}, profit {s['profit']:,} -> {os.path.basename(path)}; "
        f"high share {share:.0%}, max {cap} ({reason})")


def tick(inv, catalog, log=print):
    db = connect()
    try:
        policy(db)
        hourly(db, inv, catalog, log)
        daily(db, inv, catalog, log)
    finally:
        db.close()
