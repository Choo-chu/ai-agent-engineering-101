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

from market_db import ME, connect, load_stats, meta
from depts.logistics import perishable, perishable_line, perishable_numbers  # noqa: F401

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # week-08/ (this file is in depts/)
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


def extras(db, t0, t1, catalog):
    """Stage 1/2 numbers for a report period."""
    out = {}
    rows = db.execute("SELECT ts, shop_case FROM cases WHERE ts < ? ORDER BY ts", (t1,)).fetchall()
    dur = {}
    for (ts, c), nxt in zip(rows, rows[1:] + [(t1, None)]):
        a, b = max(ts, t0), min(nxt[0], t1)
        if b > a:
            dur[c] = dur.get(c, 0) + round((b - a) / 60)
    out["case_minutes"] = dur
    out["case_switches"] = sum(1 for (_, a), (ts, b) in zip(rows, rows[1:]) if a != b and t0 <= ts < t1)
    import strategy
    out["variants"] = {}
    for key in strategy.VARIANTS:
        w = strategy.weights(db, key)
        perf = strategy.performance(db, key)
        out["variants"][key] = {v: {"weight": w[v], "n": perf[v][0], "metric": perf[v][1]} for v in w}
    surplus = 0
    for sku, amount in db.execute("SELECT sku, amount FROM settles WHERE buyer=? AND ts>=? AND ts<?", (ME, t0, t1)):
        lp = (catalog.get(sku) or {}).get("list_price")
        surplus += (lp - amount) if lp else 0
    refund = db.execute("SELECT COALESCE(SUM(paid), 0) FROM my_broken WHERE refunded=1 AND broke_at>=? AND broke_at<?",
                        (t0, t1)).fetchone()[0]
    out["buyer_surplus"] = surplus + refund
    out["buyer_refunds"] = refund
    wr = db.execute("""SELECT COUNT(*), COALESCE(SUM((SELECT s.amount FROM settles s WHERE s.shop=? AND s.sku=b.sku
                       AND s.buyer=b.buyer AND s.ts<=b.ts ORDER BY s.ts DESC LIMIT 1)), 0)
                       FROM broken b WHERE b.shop=? AND b.refunded=1 AND b.ts>=? AND b.ts<?""", (ME, ME, t0, t1)).fetchone()
    out["warranty_refunds"] = {"n": wr[0], "amount": wr[1]}
    out["warranty_sales"] = db.execute("SELECT COUNT(*) FROM settles WHERE shop=? AND warranty_hours>0 AND ts>=? AND ts<?",
                                       (ME, t0, t1)).fetchone()[0]
    out["want_sales"] = db.execute("""SELECT COUNT(DISTINCT s.seq) FROM settles s JOIN want_replies w ON w.sku=s.sku
                                      WHERE s.shop=? AND s.ts>=w.ts AND s.ts<=w.ts+7200 AND s.ts>=? AND s.ts<?""",
                                   (ME, t0, t1)).fetchone()[0]
    scores = load_stats().get("shop_score", {})
    out["top_shops"] = [(k, v["score"]) for k, v in sorted(scores.items(), key=lambda kv: -kv[1]["score"])[:3]]
    return out


def day_money(db, t0, t1, s):
    """Cash, stock at cost and storage from the 5-min cash table; sales profit; book change; STOCK_CAP runs."""
    rows = db.execute("SELECT ts, balance, stock_cost, storage_per_day FROM cash WHERE ts>=? AND ts<? ORDER BY ts",
                      (t0, t1)).fetchall()
    out = {"profit": s["profit"], "revenue": s["revenue"], "rows": len(rows)}
    if rows:
        out.update(cash0=rows[0][1], cash1=rows[-1][1], stock0=rows[0][2], stock1=rows[-1][2],
                   storage=round(sum(r[3] or 0 for r in rows) / len(rows) * (rows[-1][0] - rows[0][0]) / 86400),
                   book_change=(rows[-1][1] + rows[-1][2]) - (rows[0][1] + rows[0][2]))
    try:
        cap = db.execute("SELECT shop_case, budget_free - budget, plan_free, plan FROM cap_runs WHERE ts>=? AND ts<?",
                         (t0, t1)).fetchall()
    except Exception:
        cap = []
    out["cap_runs"] = len(cap)
    out["cap_blocked"] = sum(1 for c in cap if c[0] == "overstock")
    out["cap_budget_cut"] = sum(c[1] for c in cap)
    extra = {}
    for _, _, pf, p in cap:
        mine, free = {}, {}
        for x in json.loads(p):
            mine[x["sku"]] = mine.get(x["sku"], 0) + x["qty"]
        for x in json.loads(pf):
            free[x["sku"]] = free.get(x["sku"], 0) + x["qty"]
        for k, q in free.items():
            extra[k] = extra.get(k, 0) + max(0, q - mine.get(k, 0))
    out["cap_extra"] = sorted(((k, v) for k, v in extra.items() if v), key=lambda kv: -kv[1])
    return out


def money_line(m):
    if not m["rows"]:
        return f"sales profit {m['profit']:,}; no cash snapshots"
    return (f"cash {m['cash0']:,} -> {m['cash1']:,}, stock at cost {m['stock0']:,} -> {m['stock1']:,}, "
            f"storage ~{m['storage']:,}, sales profit {m['profit']:,}, book change {m['book_change']:+,}; "
            f"STOCK_CAP runs {m['cap_runs']} (blocked {m['cap_blocked']}, budget cut {m['cap_budget_cut']:,})")


def money_md(m, catalog):
    if not m["rows"]:
        return [f"- sales profit {m['profit']:,}; no cash snapshots"]
    return [f"- cash {m['cash0']:,} -> {m['cash1']:,}",
            f"- stock at cost {m['stock0']:,} -> {m['stock1']:,}",
            f"- storage ~{m['storage']:,} (5-min snapshots of stock x storage_per_day)",
            f"- sales profit {m['profit']:,} on revenue {m['revenue']:,}; book (cash + stock at cost) change "
            f"{m['book_change']:+,}",
            f"- runs where STOCK_CAP ({__import__("strategy").STOCK_CAP:,}) blocked or cut buying: {m['cap_runs']} (blocked "
            f"{m['cap_blocked']}), budget kept back {m['cap_budget_cut']:,} in total",
            "- without the cap these runs would also have bought: "
            + (", ".join(f"{((catalog.get(k) or {}).get('name') or k)[:24]} x{q}" for k, q in m["cap_extra"][:10])
               or "nothing")]


def payment_counts():
    """payments.jsonl so far: (lines, unpaid, unpaid for shelf life). The file has no time stamps, so hourly
    reports store these counts and report the growth since the last report."""
    lines = unpaid = shelf = 0
    try:
        with open(os.path.join(HERE, ".market", "payments.jsonl"), encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                lines += 1
                p = json.loads(line)
                if not p.get("paid"):
                    unpaid += 1
                    shelf += "shelf life" in (p.get("reason") or "")
    except (OSError, ValueError):
        pass
    return {"lines": lines, "unpaid": unpaid, "shelf": shelf}


def payment_delta(db):
    now = payment_counts()
    prev = json.loads(meta(db, "pay_seen") or "null") or now
    db.execute("INSERT OR REPLACE INTO meta VALUES ('pay_seen', ?)", (json.dumps(now),))
    return {k: now[k] - prev.get(k, 0) for k in now}


def hourly(db, inv, catalog, log):
    now = time.time()
    hour = now // 3600 * 3600 - 3600                  # the last full hour (epoch hours line up with KST hours)
    done = meta(db, "hourly_done")                    # start of the next hour still to report
    if done is not None and hour < float(done):
        return
    s = summarize(my_sales(db, hour, hour + 3600), catalog)
    stock = sum(u.get("cost", 0) for u in inv.get("units", []) if u.get("grade") != "expired")
    cash = int(inv.get("balance", 0))
    x = extras(db, hour, hour + 3600, catalog)
    x["payments"] = payment_delta(db)
    x["perishable"] = perishable_numbers(db, hour, hour + 3600, catalog, inv)
    db.execute("INSERT OR REPLACE INTO hourly VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
               (hour, s["sales"], s["revenue"], s["profit"], s["low_cost"], s["low_profit"], s["high_cost"],
                s["high_profit"], json.dumps(s["cats"], ensure_ascii=False), stock, cash,
                json.dumps(x, ensure_ascii=False)))
    db.execute("INSERT OR REPLACE INTO meta VALUES ('hourly_done', ?)", (str(hour + 3600),))
    db.commit()
    cats = ", ".join(f"{k} {v}" for k, v in sorted(s["cats"].items(), key=lambda kv: -kv[1])[:4]) or "-"
    log(f"[report] {datetime.fromtimestamp(hour):%m-%d %H}:00 sold {s['sales']}, revenue {s['revenue']:,}, "
        f"profit {s['profit']:,} (low {pct(rate(s['low_profit'], s['low_cost']))}, "
        f"high {pct(rate(s['high_profit'], s['high_cost']))}), by category: {cats}; stock {stock:,}, cash {cash:,}")
    log(f"[report] {datetime.fromtimestamp(hour):%H}:00 cases {x['case_minutes']} min, "
        f"{x['case_switches']} switches, buyer surplus "
        f"{x['buyer_surplus']:,} (refunds {x['buyer_refunds']:,}), warranty sales {x['warranty_sales']}, "
        f"warranty refunds {x['warranty_refunds']['n']} ({x['warranty_refunds']['amount']:,}), wanted-reply sales "
        f"{x['want_sales']}, top shops {x['top_shops']}")
    pay = x["payments"]
    log(f"[report] {datetime.fromtimestamp(hour):%H}:00 buyer payments: {pay['lines']} checkouts, {pay['unpaid']} unpaid, "
        f"{pay['shelf']} of them for shelf life")
    log(f"[report] {datetime.fromtimestamp(hour):%H}:00 {perishable_line(x['perishable'])}")


def extras_md(db, t0, t1, catalog):
    x = extras(db, t0, t1, catalog)
    lines = ["## Cases and variants", "",
             "- time per shop case (min): " + (", ".join(f"{k} {v}" for k, v in x["case_minutes"].items()) or "-")
             + f"; {x['case_switches']} switches"]
    for key, vs in x["variants"].items():
        lines.append(f"- {key}: " + ", ".join(f"{v} weight {d['weight']:.2f} (n {d['n']}, per negotiation {d['metric']})"
                                               for v, d in vs.items()))
    changes = db.execute("SELECT datetime(ts,'unixepoch','localtime'), key, reason FROM variant_weights "
                         "WHERE ts>=? AND ts<? AND reason!='start' GROUP BY ts, key", (t0, t1)).fetchall()
    lines += [f"- weight change {ts} {key}: {reason}" for ts, key, reason in changes] or ["- no weight change"]
    pays = [json.loads(e).get("payments") for (e,) in db.execute(
        "SELECT extra FROM hourly WHERE hour>=? AND hour<? AND extra IS NOT NULL", (t0, t1))]
    pays = [p for p in pays if p]
    if pays:
        lines.append(f"- buyer checkouts {sum(p['lines'] for p in pays)}, unpaid {sum(p['unpaid'] for p in pays)}, "
                     f"for shelf life {sum(p['shelf'] for p in pays)} (hourly growth of payments.jsonl)")
    lines += ["", "## Buyer, warranty, forum", "",
              f"- buyer surplus (list - paid + refunds) {x['buyer_surplus']:,}, refunds {x['buyer_refunds']:,}",
              f"- my warranty sales {x['warranty_sales']}, warranty refunds {x['warranty_refunds']['n']} "
              f"({x['warranty_refunds']['amount']:,})",
              f"- sales within 2 h of a '구합니다' reply: {x['want_sales']}",
              "- top shop scores: " + ", ".join(f"{k} {v:.2f}" for k, v in x["top_shops"]), ""]
    return lines


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
    __import__("decisions").record("ceo", "buying_split", "high_share/high_max", {"high_share": share, "high_max": cap},
                                   f"{day:%Y-%m-%d}: {reason}")

    money = day_money(db, t0, t1, s)
    lines = [f"# Choo Shop daily report {day:%Y-%m-%d}", "",
             f"- sales {s['sales']}, revenue {s['revenue']:,}, profit {s['profit']:,}",
             f"- profit / cost: low-price {pct(lr)} ({s['low_profit']:,} on {s['low_cost']:,}), "
             f"high-price {pct(hr)} ({s['high_profit']:,} on {s['high_cost']:,})",
             f"- stock at cost {stock:,}, cash {int(inv.get('balance', 0)):,}",
             f"- {perishable_line(perishable_numbers(db, t0, t1, catalog, inv))}", "",
             "## Cash, stock, storage, profit", ""] + money_md(money, catalog) + ["",
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
             f"high-price units held at most {pol['high_max']} -> {cap} ({reason})", ""] + extras_md(db, t0, t1, catalog)
    os.makedirs(REPORTS, exist_ok=True)
    path = os.path.join(REPORTS, f"daily_{day:%Y%m%d}.md")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    db.execute("INSERT OR REPLACE INTO meta VALUES ('daily_done', ?)", (day.strftime("%Y%m%d"),))
    db.commit()
    log(f"[report] daily {day:%Y-%m-%d}: {money_line(money)}")
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
