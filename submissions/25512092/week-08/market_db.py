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
"""
import json
import os
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
    CREATE TABLE IF NOT EXISTS meta (k TEXT PRIMARY KEY, v TEXT);
    """)
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
        if e.get("kind") != "settle":
            continue
        d = e["data"]
        sku = d.get("sku") or d.get("item")
        avg, _ = sku_avg(db, sku, e["ts"])
        url = (d.get("shop") or "").rstrip("/")
        db.execute("INSERT OR IGNORE INTO settles VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                   (e["seq"], e["ts"], d.get("buyer"), url, names.get(url), sku, d.get("name"), d.get("grade"),
                    d.get("amount"), None if d.get("claim_honest") is None else int(bool(d["claim_honest"])), avg))
        added += 1
    if entries:
        db.execute("INSERT OR REPLACE INTO meta VALUES ('last_seq', ?)", (str(entries[-1]["seq"]),))

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

    db.execute("INSERT OR REPLACE INTO meta VALUES ('refreshed', ?)", (str(now),))
    db.commit()
    db.close()
    tmp = STATS_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(stats, f, ensure_ascii=False)
    os.replace(tmp, STATS_PATH)                       # readers never see a half-written file
    log(f"[market_db] +{added} settles, {len(stats['skus'])} SKUs priced, hot: "
        + ", ".join(f"{stats['skus'][k]['name'] or k}({stats['skus'][k]['sold_30m']})" for k in stats["hot"][:3]))
    return True


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
