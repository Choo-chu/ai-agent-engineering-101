"""Forum posts — called by restock.py every run; the kit sends .market/outbox.jsonl lines (one post per 5 min
per role is all the market accepts, so this file keeps the same pace).

  as buyer : a report of one of my settled purchases, with its ledger ref (paid vs list price, grade, the
             market average then). Buyer posts and the votes on them count in the buyer's ALL.
  as shop  : an ad for the stock that sits longest on my shelf, with a promo line from PROMO.

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


def shop_post(inv):
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
        p = shop_post(inv)
        if p:
            _send(state_dir, p)
            st["shop_ts"] = now
            log(f"[forum] shop post: {p['post'][:90]}")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(st, f)
