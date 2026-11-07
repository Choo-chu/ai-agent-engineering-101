"""Receipt changes (person's decision 11/07 ~09:45), used by seller_r3.py, switched by receipt_rules.json
{"category_item": bool, "claim_share": 0.5, "since"} (read per negotiation).

  category_item  an order that names a category (no SKU, the category word in the request, not a product name):
                 the receipt's item is the order's category name (e.g. 김치), the unit goes in the receipt's unit.
                 The market allows the order's item or an acceptable SKU as a receipt item; buyers such as q00 that
                 compare the receipt with the ordered category ("Ordered 침구, receipt names G0be9ed07 ... forges
                 receipts") should stop seeing a mismatch. The checkout and the ledger still name the SKU shipped.
  claim          non-food negotiations only (goods grades are fixed when they arrive; food grades fall while a unit
                 waits, so a food claim could turn false at checkout): claim_share of them put the unit's real grade
                 (A/B/C) in the receipt's claim, the rest do not. Compared by deal rate and stars.
Each negotiation with a non-food unit or a category receipt is a row of market.db shop_receipt (task, ts, sku, unit,
kind, item, claim_arm).
"""
import json
import random
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
FLAG = HERE / "receipt_rules.json"


def rules():
    try:
        j = json.loads(FLAG.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return j if time.time() >= (j.get("since") or 0) else {}


def category_item(text, unit, named_sku):
    """The order's category name when the request names the category, not a SKU or a product; else None."""
    if named_sku or not rules().get("category_item"):
        return None
    leaf = (unit.get("category") or "").split(">")[-1]
    t = (text or "").lower()
    if leaf and leaf.lower() in t and (unit.get("name") or "").lower() not in t:
        return leaf
    return None


def claim_arm(unit):
    share = float(rules().get("claim_share") or 0)
    if not share or unit.get("kind") == "food":
        return None
    return "claim" if random.random() < share else "none"


def log(connect, task, unit, item, arm):
    if not item and not arm:
        return
    try:
        db = connect()
        db.execute("CREATE TABLE IF NOT EXISTS shop_receipt (task TEXT PRIMARY KEY, ts REAL, sku TEXT, unit TEXT, "
                   "kind TEXT, item TEXT, claim_arm TEXT)")
        db.execute("INSERT OR REPLACE INTO shop_receipt VALUES (?,?,?,?,?,?,?)",
                   (task, time.time(), unit["sku"], unit["unit"], unit.get("kind"), item, arm))
        db.commit()
        db.close()
    except Exception as e:
        print(f"[receipt_exp] {e}", flush=True)


def claim_numbers(since, until):
    """Per claim arm: negotiations, receipts (deal rate), settled, average stars of the reviews matched to those
    settles (the buyer's review within 15 min after a settle of that unit)."""
    from market_db import ME, connect
    db = connect()
    try:
        db.execute("CREATE TABLE IF NOT EXISTS shop_receipt (task TEXT PRIMARY KEY, ts REAL, sku TEXT, unit TEXT, "
                   "kind TEXT, item TEXT, claim_arm TEXT)")
        out = {}
        for arm in ("claim", "none"):
            rows = db.execute("SELECT r.task, r.unit, d.outcome, d.price FROM shop_receipt r LEFT JOIN shop_deals d "
                              "ON d.task=r.task WHERE r.claim_arm=? AND r.ts>=? AND r.ts<?", (arm, since, until)).fetchall()
            rc = [r for r in rows if r[2] == "receipt"]
            stars = []
            settled = 0
            for _, unit, _, price in rc:
                s = db.execute("SELECT buyer, ts FROM settles WHERE shop=? AND unit=? AND amount=? AND ts>=?",
                               (ME, unit, price, since)).fetchone()
                if not s:
                    continue
                settled += 1
                st = db.execute("SELECT stars FROM my_results WHERE buyer=? AND ts BETWEEN ? AND ? ORDER BY ts LIMIT 1",
                                (s[0], s[1], s[1] + 900)).fetchone()
                if st:
                    stars.append(st[0])
            out[arm] = {"n": len(rows), "receipts": len(rc), "deal_rate": round(len(rc) / len(rows), 3) if rows else None,
                        "settled": settled, "stars_n": len(stars),
                        "stars": round(sum(stars) / len(stars), 2) if stars else None}
        n = db.execute("SELECT COUNT(*) FROM shop_receipt WHERE item IS NOT NULL AND ts>=? AND ts<?",
                       (since, until)).fetchone()[0]
        out["category_receipts"] = n
    finally:
        db.close()
    return out
