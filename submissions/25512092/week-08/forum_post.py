"""Forum posts. restock.py calls run() every minute; the kit sends the lines of .market/outbox.jsonl.
The market accepts one post per 5 minutes per role, so each role has its own slot and its own priority queue
(kept in .market/forum_state.json). Events are queued when they happen; one post per slot leaves when it is due.

  shop slot   0  food clearance    a food SKU near expiry whose markdown stepped down (pricing.clearance)
              1  aging markdown    a non-food SKU whose 6-hourly markdown stepped down (pricing.aging)
              -  comparison ad     when the queue is empty: my floor vs the 2-hour market average, my prices only
  buyer slot  0  ledger record     a shop with >= 2 new settles whose grade claim the market marked dishonest
                                   (claim_honest = false); ledger numbers only, at most once per shop per 6 h
              -  market report     when the queue is empty: the 3 busiest categories of the last 2 hours

Queued items keep only the event; the text is written when the item leaves, from the prices of that moment, and
an item whose stock is gone is dropped. The promo lines are sales talk for the game (also in seller_r3.py's first
reply) and contain no digits, because buyers read prices out of shop messages.
"""
import itertools
import json
import os
import random
import sqlite3
import time

from pricing import NEAR_EXPIRY_H, aging, clearance, floor, held_cost

HERE = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(HERE, "market.db")
ME = "choo-chu"
POST_EVERY_S = 300
WINDOW_S = 2 * 3600              # report and comparison ads use the last 2 hours
MIN_N = 3                        # an average needs this many deals in the window
CALLOUT_MIN_NEW = 2
CALLOUT_EVERY_S = 6 * 3600
AD_REPEAT_S = 3600               # the same SKU is advertised at most once an hour

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
            st = json.load(f)
    except (OSError, ValueError):
        st = {}
    for k, v in {"buyer_ts": 0, "shop_ts": 0, "queue": {"shop": [], "buyer": []}, "seen": [],
                 "callout": {}, "ads": {}, "report_cats": []}.items():
        st.setdefault(k, v)
    return path, st


def _send(state_dir, post):
    for _ in range(5):                       # the kit may hold the file for a moment while it sends
        try:
            with open(os.path.join(state_dir, "outbox.jsonl"), "a", encoding="utf-8") as f:
                f.write(json.dumps(post, ensure_ascii=False) + "\n")
            return
        except PermissionError:
            time.sleep(1)
    raise PermissionError("outbox.jsonl stayed locked")


def _short(name, n=24):
    return name if len(name) <= n else name[:n] + "…"


# --- prices

def avg_2h(db, sku, now):
    a, n = db.execute("SELECT AVG(amount), COUNT(*) FROM settles WHERE sku=? AND ts>=?", (sku, now - WINDOW_S)).fetchone()
    return (a, n) if n >= MIN_N else (None, n)


def _price(sku):
    from market_db import price_of             # the same average the seller uses
    return price_of(sku)[0]


def _live(inv):
    return [u for u in inv.get("units", []) if u.get("grade") != "expired"]


# --- events -> queues

def _enqueue(st, role, prio, key, kind, log, **data):
    if key in st["seen"]:
        return
    q = st["queue"][role]
    q[:] = [it for it in q if not (it["kind"] == kind and it.get("id") == data.get("id"))]   # newer step replaces
    q.append({"prio": prio, "key": key, "kind": kind, "t": time.time(), **data})
    st["seen"] = (st["seen"] + [key])[-2000:]
    log(f"[forum] queued {role} {kind} {data.get('id')} ({key})")


def collect(st, inv, db, log):
    now = time.time()
    for u in _live(inv):
        avg = _price(u["sku"])
        c, left = clearance(u, avg, now)
        if c is not None:
            _enqueue(st, "shop", 0, f"clear:{u['sku']}:{int(NEAR_EXPIRY_H - left)}", "clearance", log, id=u["sku"])
            continue
        a, step = aging(u, avg, now)
        if a is not None:
            _enqueue(st, "shop", 1, f"aging:{u['sku']}:{step}", "aging", log, id=u["sku"])

    rows = db.execute("SELECT seq, COALESCE(shop, shop_url) FROM settles WHERE claim_honest=0 AND "
                      "COALESCE(shop, shop_url) IS NOT NULL AND COALESCE(shop, '') != ? ORDER BY seq", (ME,)).fetchall()
    by_shop = {}
    for seq, shop in rows:
        by_shop.setdefault(shop, []).append(seq)
    queued = {it["id"] for it in st["queue"]["buyer"] if it["kind"] == "callout"}
    for shop, seqs in by_shop.items():
        c = st["callout"].get(shop, {"seq": 0, "ts": 0})
        new = [s for s in seqs if s > c["seq"]]
        if len(new) >= CALLOUT_MIN_NEW and now - c["ts"] >= CALLOUT_EVERY_S and shop not in queued:
            _enqueue(st, "buyer", 0, f"callout:{shop}:{new[-1]}", "callout", log, id=shop)


# --- rendering (at send time)

def render_markdown(it, inv, kind):
    """A clearance or aging post for the SKU, at the floor the seller enforces right now."""
    now, stock = time.time(), held_cost(inv)
    units = [u for u in _live(inv) if u["sku"] == it["id"]]
    test = clearance if kind == "clearance" else aging
    units = [u for u in units if test(u, _price(u["sku"]), now)[0] is not None]
    if not units:
        return None                               # sold or no longer marked down
    u = units[0]
    avg = _price(u["sku"])
    f, _ = floor(u, avg, stock, now)
    base = avg or u["list_price"]
    off = round(100 * (1 - f / base))
    if kind == "clearance":
        left = clearance(u, avg, now)[1]
        head = f"[Choo Shop 마감 할인] {u['name']} ({u['sku']}) 유통기한 {left:.0f}시간 남음, 지금 {f:,}원부터! "
        tail = "1시간마다 10%씩 더 내려갑니다"
    else:
        head = f"[Choo Shop 재고 정리] {u['name']} ({u['sku']}) 재고 {len(units)}개, 지금 {f:,}원부터! "
        tail = "6시간마다 10%씩 더 내려갑니다"
    return {"post": head + f"(시장 평균 {int(base):,}원 대비 {off}% 할인, {tail}) {promo()} "
                           f"주문에 '{u['sku']}'를 넣어 불러 주세요.", "refs": [], "as": "shop"}


def render_callout(it, db, st):
    shop = it["id"]
    c = st["callout"].get(shop, {"seq": 0, "ts": 0})
    seqs = [s for (s,) in db.execute("SELECT seq FROM settles WHERE claim_honest=0 AND COALESCE(shop, shop_url)=? "
                                     "AND seq>? ORDER BY seq", (shop, c["seq"]))]
    if len(seqs) < CALLOUT_MIN_NEW:
        return None
    st["callout"][shop] = {"seq": seqs[-1], "ts": time.time()}
    shown = ", ".join(f"#{s}" for s in seqs[:10]) + (f" 외 {len(seqs) - 10}건" if len(seqs) > 10 else "")
    return {"post": f"[정산 기록] {shop}: 등급 주장과 실제 등급 불일치 {len(seqs)}건 (ledger {shown})",
            "refs": seqs[:5], "as": "buyer"}


def comparison_ad(inv, db, st):
    now, stock = time.time(), held_cost(inv)
    best = None
    seen = set()
    for u in sorted(_live(inv), key=lambda u: (u.get("expires_at") or float("inf"), u.get("supplied_at") or 0)):
        if u["sku"] in seen:                     # the unit the seller would ship first
            continue
        seen.add(u["sku"])
        if now - st["ads"].get(u["sku"], 0) < AD_REPEAT_S:
            continue
        x, n = avg_2h(db, u["sku"], now)
        if x is None:
            continue
        y, _ = floor(u, _price(u["sku"]), stock, now)
        z = 1 - y / x
        if z > 0 and (best is None or z > best[3]):
            best = (u, int(x), y, z)
    if best is None:
        return None
    u, x, y, z = best
    st["ads"][u["sku"]] = now
    return {"post": f"[Choo Shop] {u['name']} ({u['sku']}) 최근 2시간 평균 {x:,}원 → Choo Shop {y:,}원 "
                    f"({round(100 * z)}% 저렴, 흥정하면 이 가격까지). {promo()} 주문에 '{u['sku']}'를 넣어 불러 주세요.",
            "refs": [], "as": "shop"}


def market_report(db, catalog, st):
    now = time.time()
    rows = db.execute("SELECT seq, sku, name, grade, amount FROM settles WHERE ts>=?", (now - WINDOW_S,)).fetchall()
    cats = {}
    for seq, sku, name, grade, amount in rows:
        leaf = ((catalog.get(sku) or {}).get("category") or "").split(">")[-1]
        if leaf:
            cats.setdefault(leaf, []).append((seq, sku, name, grade, amount))
    ranked = sorted(cats, key=lambda k: len(cats[k]), reverse=True)[:6]
    if len(ranked) < 3:
        return None
    prev = set(st["report_cats"])
    pick = next((c for c in itertools.combinations(ranked, 3) if set(c) != prev), None)
    if pick is None:
        return None
    st["report_cats"] = list(pick)
    lines, seqs = [], []
    for cat in pick:
        deals = cats[cat]
        seqs += [d[0] for d in deals]
        grades = {g: sum(1 for d in deals if d[3] == g) for g in "ABC"}
        by_sku = {}
        for d in deals:
            by_sku.setdefault(d[1], []).append(d)
        top = sorted(by_sku.values(), key=len, reverse=True)[:2]
        skus = "; ".join(f"{_short(ds[0][2] or ds[0][1])} {round(sum(d[4] for d in ds) / len(ds)):,}원({len(ds)}건)"
                         for ds in top)
        lines.append(f"- {cat}: {len(deals)}건, 등급 A {grades['A']}/B {grades['B']}/C {grades['C']} | 평균 체결가 {skus}")
    return {"post": f"[시세 리포트] 최근 2시간 거래 많은 카테고리 (ledger #{min(seqs)}~#{max(seqs)})\n" + "\n".join(lines),
            "refs": [], "as": "buyer"}


def _pop(st, role, render):
    q = st["queue"][role]
    q.sort(key=lambda it: (it["prio"], it["t"]))
    while q:
        it = q.pop(0)
        p = render(it)
        if p:
            return p, it
    return None, None


def run(state_dir, inv, catalog, log=print):
    path, st = _state(state_dir)
    now = time.time()
    db = sqlite3.connect(DB_PATH, timeout=30)
    try:
        collect(st, inv, db, log)
        if now - st["shop_ts"] >= POST_EVERY_S:
            p, it = _pop(st, "shop", lambda it: render_markdown(it, inv, it["kind"]))
            p = p or comparison_ad(inv, db, st)
            if p:
                _send(state_dir, p)
                st["shop_ts"] = now
                log(f"[forum] shop {it['kind'] if it else 'comparison ad'}: {p['post'][:110]}")
        if now - st["buyer_ts"] >= POST_EVERY_S:
            p, it = _pop(st, "buyer", lambda it: render_callout(it, db, st))
            p = p or market_report(db, catalog, st)
            if p:
                _send(state_dir, p)
                st["buyer_ts"] = now
                log(f"[forum] buyer {it['kind'] if it else 'market report'}: {p['post'][:110]}")
    finally:
        db.close()
        with open(path, "w", encoding="utf-8") as f:
            json.dump(st, f, ensure_ascii=False)
