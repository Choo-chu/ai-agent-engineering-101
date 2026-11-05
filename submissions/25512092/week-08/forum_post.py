"""Forum posts — called by restock.py every run; the kit sends .market/outbox.jsonl lines (one post per 5 min
per role is all the market accepts, so this file keeps the same pace).

  as buyer : a report of one of my settled purchases, with its ledger ref (paid vs list price, grade, the
             market average then). Buyer posts and the votes on them count in the buyer's ALL.
  as shop  : first a clearance notice for a unit near expiry each time its discount steps down (clearance(),
             also the seller's floor); otherwise an ad for the slowest stock, with a promo line from PROMO.

The promo lines are sales talk invented for the game; seller_r3.py uses the same lines in its first reply.
They contain no digits, because buyers read prices out of shop messages.
"""
import json
import os
import random
import sqlite3
import time

HERE = os.path.dirname(os.path.abspath(__file__))
POST_EVERY_S = 300
SLOW_AFTER_S = 3600          # a unit on the shelf this long counts as slow stock
NEAR_EXPIRY_H = 12      # a unit with less shelf life than this is "near expiry" (12 h left -> avg, 3 h left -> 10%)
CUT_PER_H = 0.10        # near expiry, the floor drops 10% of the market average for every hour since
MAX_CUT = 0.90          # never below 10% of the average: something back beats a unit that expires


def clearance(u, avg):
    """(floor, hours_left) for a unit near expiry, else (None, hours_left). The floor starts at the market
    average (or 70% of list when there is none) and drops CUT_PER_H of it for every full hour the unit has
    been near expiry. It may go below cost: a unit that expires is worth nothing."""
    if not u.get("expires_at"):
        return None, None
    left = (u["expires_at"] - time.time()) / 3600
    if left >= NEAR_EXPIRY_H:
        return None, left
    base = avg if avg is not None else u["list_price"] * 0.7
    cut = min(MAX_CUT, CUT_PER_H * int(NEAR_EXPIRY_H - left))
    return int(base * (1 - cut)), left

PROMO = [
    "요즘 SNS 인플루언서들 사이에서 입소문 난 바로 그 제품!",
    "SNS 스타들이 직접 쓰고 후기 올린 제품, 품절 전에 데려가세요.",
    "유명 영화배우가 촬영장에서도 챙겨 쓴다는 바로 그 제품.",
    "트럼프 대통령도 직접 쓰고 광고했다는 화제의 제품!",
]


def promo():
    return random.choice(PROMO)


def _state(state_dir):
    path = os.path.join(state_dir, "forum_state.json")
    try:
        with open(path, encoding="utf-8") as f:
            return path, json.load(f)
    except (OSError, ValueError):
        return path, {"buyer_ts": 0, "shop_ts": 0, "posted": []}


def _send(state_dir, post):
    with open(os.path.join(state_dir, "outbox.jsonl"), "a", encoding="utf-8") as f:
        f.write(json.dumps(post, ensure_ascii=False) + "\n")


def buyer_post(db, catalog, st):
    """My newest settled purchase that I have not reported yet."""
    row = db.execute("SELECT seq, sku, name, grade, amount, market_avg_at, shop FROM settles WHERE buyer='choo-chu' "
                     "AND seq NOT IN (%s) ORDER BY seq DESC LIMIT 1" % ",".join(map(str, st["posted"] or [0]))).fetchone()
    if not row:
        return None
    seq, sku, name, grade, amount, avg, shop = row
    lp = (catalog.get(sku) or {}).get("list_price")
    off = f", 정가 {lp:,}원 대비 {round(100 * (1 - amount / lp))}% 할인" if lp else ""
    mk = f" | 거래 당시 시장 평균 {round(avg):,}원" if avg else ""
    st["posted"] = (st["posted"] + [seq])[-200:]
    return {"post": f"[구매 기록] {name} ({sku}) | {amount:,}원{off} | 등급 {grade}{mk} | 판매: {shop or '?'} | ledger #{seq}",
            "refs": [seq], "as": "buyer"}


def clearance_post(inv, st):
    """A unit near expiry whose current discount step has not been announced yet (one post per step)."""
    from market_db import price_of
    best = None
    for u in inv.get("units", []):
        if u.get("grade") == "expired":
            continue
        avg, _ = price_of(u["sku"])
        floor, left = clearance(u, avg)
        if floor is None:
            continue
        key = f"{u['sku']}:{int(NEAR_EXPIRY_H - left)}"
        if key in st.setdefault("clear_posted", []):
            continue
        if best is None or left < best[2]:
            best = (u, floor, left, avg, key)
    if best is None:
        return None
    u, floor, left, avg, key = best
    st["clear_posted"] = (st["clear_posted"] + [key])[-300:]
    base = avg or u["list_price"]
    return {"post": f"[Choo Shop 마감 할인] {u['name']} ({u['sku']}) 유통기한 {left:.0f}시간 남음, 지금 {floor:,}원부터! "
                    f"(시장 평균 {int(base):,}원 대비 {round(100 * (1 - floor / base))}% 할인, 1시간마다 10%씩 더 내려갑니다) "
                    f"{promo()} 주문에 '{u['sku']}'를 넣어 불러 주세요.", "refs": [], "as": "shop"}


def shop_post(inv, st=None):
    if st is not None:
        p = clearance_post(inv, st)
        if p:
            return p
    now = time.time()
    slow = [u for u in inv.get("units", []) if u.get("grade") != "expired" and now - (u.get("supplied_at") or now) > SLOW_AFTER_S]
    if not slow:
        return None
    by_sku = {}
    for u in slow:
        by_sku.setdefault(u["sku"], []).append(u)
    sku, units = max(by_sku.items(), key=lambda kv: len(kv[1]))
    u = units[0]
    return {"post": f"[Choo Shop] {u['name']} ({sku}) 재고 {len(units)}개, 정가 {u['list_price']:,}원보다 싸게 드려요. "
                    f"{promo()} 주문에 '{sku}'를 넣어 불러 주세요.", "refs": [], "as": "shop"}


def run(state_dir, inv, catalog, log=print):
    path, st = _state(state_dir)
    now = time.time()
    if now - st["buyer_ts"] >= POST_EVERY_S:
        db = sqlite3.connect(os.path.join(HERE, "market.db"), timeout=30)
        try:
            p = buyer_post(db, catalog, st)
        finally:
            db.close()
        if p:
            _send(state_dir, p)
            st["buyer_ts"] = now
            log(f"[forum] buyer post: {p['post'][:90]}")
    if now - st["shop_ts"] >= POST_EVERY_S:
        p = shop_post(inv, st)
        if p:
            _send(state_dir, p)
            st["shop_ts"] = now
            log(f"[forum] shop post: {p['post'][:90]}")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(st, f)
