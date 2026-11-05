"""Market price DB (SQLite) — every settled deal in the market, refreshed at most once per 5 minutes.

    python market_db.py            refresh now and print the hottest SKUs
    python market_db.py --report   print my buys and sales with the market average at that time

Who uses it
  restock.py  calls refresh() every run (the kit runs it every 60 s); refresh() does nothing if the
              last refresh is younger than REFRESH_S. Only restock.py writes the DB.
  market_buyer.py, seller_r3.py  read market_stats.json (written by refresh) through price_of().

Tables
  settles    one row per settled deal in the ledger: seq, ts, buyer, shop (name, if the shop is still
             registered), sku, name, grade, amount, claim_honest, market_avg_at (the SKU's average
             before this deal, so my own rows show what the market price was when I bought or sold)
  snapshots  every refresh: per SKU the average price and how many sold in the last 5 and 30 minutes
  my_stock   every unit my shop bought from supply: unit, sku, cost, grade, supplied_at, market_avg_at
  broken     every goods unit that broke after a sale: shop, sku, hours after sale, warranty, refund

Signals in market_stats.json (code-made; forum text never goes to a harness)
  shop_flags  per shop (name and URL): deals, dishonest grade claims, broken units — from the ledger, plus
              forum posts whose ledger refs show a dishonest claim
  sku_break   per SKU: share of sold units that broke
  wanted      SKUs that buyers asked for on the forum ("구합니다", "looking for" ...)
"""
import json
import os
import re
import sqlite3
import sys
import time

import httpx

HERE = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(HERE, "market.db")
STATS_PATH = os.path.join(HERE, "market_stats.json")
MARKET = os.environ.get("MARKET_URL", "https://market.ourolabs.ai")
ME = "choo-chu"

REFRESH_S = 300          # refresh at most every 5 minutes
AVG_WINDOW_S = 2 * 3600  # the average price uses deals of the last 2 hours ...
MIN_N = 3                # ... and needs at least this many deals, else all deals of that SKU
BOOTSTRAP = 20000        # ledger entries read back on the first refresh


def connect():
    db = sqlite3.connect(DB_PATH, timeout=30)
    db.executescript("""
    CREATE TABLE IF NOT EXISTS settles (seq INTEGER PRIMARY KEY, ts REAL, buyer TEXT, shop_url TEXT, shop TEXT,
        sku TEXT, name TEXT, grade TEXT, amount INTEGER, claim_honest INTEGER, market_avg_at REAL);
    CREATE INDEX IF NOT EXISTS settles_sku ON settles (sku, ts);
    CREATE TABLE IF NOT EXISTS snapshots (ts REAL, sku TEXT, avg_price REAL, n INTEGER, sold_5m INTEGER,
        sold_30m INTEGER, PRIMARY KEY (ts, sku));
    CREATE TABLE IF NOT EXISTS my_stock (unit TEXT PRIMARY KEY, sku TEXT, name TEXT, cost INTEGER, grade TEXT,
        supplied_at REAL, market_avg_at REAL);
    CREATE TABLE IF NOT EXISTS broken (seq INTEGER PRIMARY KEY, ts REAL, buyer TEXT, shop_url TEXT, shop TEXT,
        sku TEXT, hours_after_sale REAL, warranty_hours REAL, refunded INTEGER);
    CREATE TABLE IF NOT EXISTS meta (k TEXT PRIMARY KEY, v TEXT);
    CREATE TABLE IF NOT EXISTS hourly (hour REAL PRIMARY KEY, sales INTEGER, revenue INTEGER, profit INTEGER,
        low_cost INTEGER, low_profit INTEGER, high_cost INTEGER, high_profit INTEGER, cats TEXT,
        stock_cost INTEGER, cash INTEGER);
    CREATE TABLE IF NOT EXISTS policy (ts REAL PRIMARY KEY, high_share REAL, high_max INTEGER, reason TEXT);
    CREATE TABLE IF NOT EXISTS cash (ts REAL PRIMARY KEY, balance INTEGER, stock_cost INTEGER, units INTEGER,
        storage_per_day INTEGER);
    """)
    if "unit" not in [r[1] for r in db.execute("PRAGMA table_info(settles)")]:
        db.execute("ALTER TABLE settles ADD COLUMN unit TEXT")       # links my sales to my_stock (cost)
    return db


def meta(db, k, default=None):
    row = db.execute("SELECT v FROM meta WHERE k=?", (k,)).fetchone()
    return row[0] if row else default


def sku_avg(db, sku, now):
    row = db.execute("SELECT AVG(amount), COUNT(*) FROM settles WHERE sku=? AND ts>=?",
                     (sku, now - AVG_WINDOW_S)).fetchone()
    if row[1] >= MIN_N:
        return row[0], row[1]
    row = db.execute("SELECT AVG(amount), COUNT(*) FROM settles WHERE sku=?", (sku,)).fetchone()
    return (row[0], row[1]) if row[1] else (None, 0)


def fetch_ledger(c, after):
    """All ledger entries after `after` (negative: that many before the newest), 500 per call."""
    out = []
    while True:
        r = c.get(f"{MARKET}/api/ledger", params={"after": after})
        r.raise_for_status()
        page = r.json()
        out += page
        if len(page) < 500:
            return out
        after = page[-1]["seq"]


def backfill_units(db):
    """Settles of my shop stored before the unit column existed: read their ledger entry again."""
    rows = db.execute("SELECT seq FROM settles WHERE unit IS NULL AND (shop=? OR shop_url IN "
                      "(SELECT shop_url FROM settles WHERE shop=?)) LIMIT 50", (ME, ME)).fetchall()
    if not rows:
        return
    with httpx.Client(timeout=30) as c:
        for (seq,) in rows:
            try:
                page = c.get(f"{MARKET}/api/ledger", params={"after": seq - 1}).json()
            except Exception:
                continue
            e = next((e for e in page if e["seq"] == seq), None)
            unit = ((e or {}).get("data") or {}).get("unit") or "-"
            db.execute("UPDATE settles SET unit=? WHERE seq=?", (unit, seq))


def refresh(force=False, log=print):
    db = connect()
    now = time.time()
    if not force and now - float(meta(db, "refreshed", 0)) < REFRESH_S:
        db.close()
        return False
    with httpx.Client(timeout=30) as c:
        last = int(meta(db, "last_seq", 0))
        entries = fetch_ledger(c, last if last else -BOOTSTRAP)
        try:
            names = {s["url"].rstrip("/"): s["name"] for s in c.get(f"{MARKET}/api/shops").json()["shops"]}
        except Exception:
            names = {}
    added = 0
    for e in entries:
        if e.get("kind") == "broken":
            d = e["data"]
            url = (d.get("shop") or "").rstrip("/")
            db.execute("INSERT OR IGNORE INTO broken VALUES (?,?,?,?,?,?,?,?,?)",
                       (e["seq"], e["ts"], d.get("buyer"), url, names.get(url), d.get("item"),
                        d.get("hours_after_sale"), d.get("warranty_hours"), d.get("refunded")))
            continue
        if e.get("kind") != "settle":
            continue
        d = e["data"]
        sku = d.get("sku") or d.get("item")
        avg, _ = sku_avg(db, sku, e["ts"])
        url = (d.get("shop") or "").rstrip("/")
        db.execute("INSERT OR IGNORE INTO settles VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                   (e["seq"], e["ts"], d.get("buyer"), url, names.get(url), sku, d.get("name"), d.get("grade"),
                    d.get("amount"), None if d.get("claim_honest") is None else int(bool(d["claim_honest"])), avg,
                    d.get("unit")))
        added += 1
    if entries:
        db.execute("INSERT OR REPLACE INTO meta VALUES ('last_seq', ?)", (str(entries[-1]["seq"]),))
    backfill_units(db)

    # snapshot: per SKU sold in the last 30 minutes, plus every SKU I hold or bought before
    stats = {"ts": now, "skus": {}, "hot": [], "my_buys": {}}
    rows = db.execute("""SELECT sku, MAX(name), SUM(ts>=?), COUNT(*) FROM settles WHERE ts>=? GROUP BY sku""",
                      (now - 300, now - 1800)).fetchall()
    for sku, name, s5, s30 in rows:
        avg, n = sku_avg(db, sku, now)
        stats["skus"][sku] = {"name": name, "avg": round(avg), "n": n, "sold_5m": s5, "sold_30m": s30}
        db.execute("INSERT OR REPLACE INTO snapshots VALUES (?,?,?,?,?,?)", (now, sku, avg, n, s5, s30))
    for (sku,) in db.execute("SELECT DISTINCT sku FROM settles WHERE buyer=? OR shop=? "
                             "UNION SELECT DISTINCT sku FROM my_stock", (ME, ME)).fetchall():
        if sku not in stats["skus"]:
            avg, n = sku_avg(db, sku, now)
            if avg is not None:
                stats["skus"][sku] = {"name": None, "avg": round(avg), "n": n, "sold_5m": 0, "sold_30m": 0}
    stats["hot"] = sorted(stats["skus"], key=lambda k: (stats["skus"][k]["sold_5m"], stats["skus"][k]["sold_30m"]),
                          reverse=True)[:30]
    for sku, paid, k in db.execute("SELECT sku, AVG(amount), COUNT(*) FROM settles WHERE buyer=? GROUP BY sku", (ME,)):
        stats["my_buys"][sku] = {"avg_paid": round(paid), "n": k}

    stats.update(signals(db, names))
    db.execute("INSERT OR REPLACE INTO meta VALUES ('refreshed', ?)", (str(now),))
    db.commit()
    db.close()
    tmp = STATS_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(stats, f, ensure_ascii=False)
    os.replace(tmp, STATS_PATH)                       # readers never see a half-written file
    bad = [k for k, v in stats["shop_flags"].items() if v["bad"] and not k.startswith("http")]
    log(f"[market_db] forum wanted {len(stats['wanted'])} SKUs, categories {stats['wanted_cats'][:5]}; shops to avoid: {', '.join(bad) or 'none'}")
    log(f"[market_db] +{added} settles, {len(stats['skus'])} SKUs priced, hot: "
        + ", ".join(f"{stats['skus'][k]['name'] or k}({stats['skus'][k]['sold_30m']})" for k in stats["hot"][:3]))
    return True


WANT = re.compile(r"구합니다|구해요|찾습니다|찾아요|삽니다|wanted|looking for|want to buy|need", re.I)
SKU_RE = re.compile(r"G[0-9a-f]{8}")
FORUM_PATH = os.path.join(HERE, ".market", "forum.json")
BAD_DISHONEST = 2          # a shop with this many dishonest grade claims is avoided
BAD_BROKEN_SHARE = 0.10    # ... or with this share of its sold units broken (at least 3)


def signals(db, names):
    """Shop flags, SKU break rates and forum demand. Everything is checked against the ledger."""
    flags = {}

    def flag(key, field, k=1):
        if key:
            f = flags.setdefault(key, {"deals": 0, "dishonest": 0, "broken": 0, "forum_dishonest": 0})
            f[field] += k

    for url, shop, n, bad in db.execute("SELECT shop_url, MAX(shop), COUNT(*), SUM(claim_honest=0) FROM settles "
                                        "GROUP BY shop_url"):
        for key in (url, shop):
            flag(key, "deals", n)
            flag(key, "dishonest", bad or 0)
    for url, shop, n in db.execute("SELECT shop_url, MAX(shop), COUNT(*) FROM broken GROUP BY shop_url"):
        for key in (url, shop):
            flag(key, "broken", n)

    sku_break = {}
    for sku, sold, broke in db.execute("SELECT s.sku, COUNT(*), (SELECT COUNT(*) FROM broken b WHERE b.sku=s.sku) "
                                       "FROM settles s GROUP BY s.sku HAVING COUNT(*) >= 5"):
        if broke:
            sku_break[sku] = round(broke / sold, 3)

    try:
        with open(os.path.join(HERE, ".market", "catalog.json"), encoding="utf-8") as f:
            leaves = {(c.get("category") or "").split(">")[-1] for c in json.load(f).values()} - {""}
    except (OSError, ValueError):
        leaves = set()
    wanted, wanted_cats = {}, {}
    try:
        with open(FORUM_PATH, encoding="utf-8") as f:
            posts = json.load(f)
    except (OSError, ValueError):
        posts = []
    for p in posts:
        text = str(p.get("text", ""))
        if p.get("role") == "buyer" and WANT.search(text):
            for sku in SKU_RE.findall(text):
                wanted[sku] = wanted.get(sku, 0) + 1
            for leaf in leaves:
                if any(part and part in text for part in leaf.split("/")):
                    wanted_cats[leaf] = wanted_cats.get(leaf, 0) + 1
        for r in p.get("refs") or []:            # a ref the market resolved: trust its data, not the post text
            if not (isinstance(r, dict) and r.get("found")):
                continue
            d = r.get("data") or {}
            if r.get("kind") == "settle" and d.get("claim_honest") is False:
                url = (d.get("shop") or "").rstrip("/")
                flag(url, "forum_dishonest")
                flag(names.get(url), "forum_dishonest")
    for f in flags.values():
        f["bad"] = (f["dishonest"] + f["forum_dishonest"] >= BAD_DISHONEST
                    or (f["broken"] >= 3 and f["broken"] / max(f["deals"], 1) >= BAD_BROKEN_SHARE))
    return {"shop_flags": flags, "sku_break": sku_break,
            "wanted": sorted(wanted, key=wanted.get, reverse=True)[:20],
            "wanted_cats": sorted(wanted_cats, key=wanted_cats.get, reverse=True)[:10]}


def record_stock(units, log=print):
    """Units my shop bought from supply, with the market average when they arrived."""
    db = connect()
    new = 0
    for u in units:
        if db.execute("SELECT 1 FROM my_stock WHERE unit=?", (u["unit"],)).fetchone():
            continue
        avg, _ = sku_avg(db, u["sku"], u.get("supplied_at") or time.time())
        db.execute("INSERT INTO my_stock VALUES (?,?,?,?,?,?,?)", (u["unit"], u["sku"], u.get("name"), u.get("cost"),
                                                                  u.get("grade"), u.get("supplied_at"), avg))
        new += 1
    db.commit()
    db.close()
    if new:
        log(f"[market_db] recorded {new} new stock units")


CASH_EVERY_S = 300


def record_cash(inv, log=print):
    """Every 5 minutes: cash, stock at cost and the storage it costs per day (rate from inventory.json)."""
    db = connect()
    now = time.time()
    try:
        if now - float(meta(db, "cash_ts", 0)) < CASH_EVERY_S:
            return None
        units = [u for u in inv.get("units", []) if u.get("grade") != "expired"]
        stock = sum(u.get("cost", 0) for u in units)
        storage = round(stock * float(inv.get("storage_per_day") or 0.01))
        row = (now, int(inv.get("balance", 0)), stock, len(units), storage)
        db.execute("INSERT OR REPLACE INTO cash VALUES (?,?,?,?,?)", row)
        db.execute("INSERT OR REPLACE INTO meta VALUES ('cash_ts', ?)", (str(now),))
        db.commit()
        log(f"[cash] balance {row[1]:,}, stock at cost {stock:,} ({len(units)} units), storage ~{storage:,}/day")
        return row
    finally:
        db.close()


def load_stats():
    try:
        with open(STATS_PATH, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {"skus": {}, "hot": [], "my_buys": {}}


def price_of(sku, stats=None):
    """(market average, deals behind it) for a SKU, or (None, 0) when the market has too few deals."""
    s = (stats or load_stats())["skus"].get(sku)
    if not s or s["n"] < MIN_N:
        return None, (s or {}).get("n", 0)
    return s["avg"], s["n"]


def report():
    db = connect()
    print("my buys (buyer):  ts | sku | paid | market avg then")
    for r in db.execute("SELECT datetime(ts,'unixepoch','localtime'), name, amount, market_avg_at FROM settles "
                        "WHERE buyer=? ORDER BY ts DESC LIMIT 20", (ME,)):
        print("  ", r)
    print("my sales (shop):")
    for r in db.execute("SELECT datetime(ts,'unixepoch','localtime'), name, amount, market_avg_at FROM settles "
                        "WHERE shop=? ORDER BY ts DESC LIMIT 20", (ME,)):
        print("  ", r)
    print("my stock bought:", db.execute("SELECT COUNT(*), SUM(cost) FROM my_stock").fetchone())


if __name__ == "__main__":
    if "--report" in sys.argv:
        report()
    else:
        refresh(force=True)
        st = load_stats()
        for k in st["hot"][:10]:
            print(k, st["skus"][k])
