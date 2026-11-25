import json
import math
import time
import uuid
import httpx

YES = ['살게', '할게', '그걸로', '주문할게', '좋아요', '살래', '구매할게', '결제할게', '구매하겠', '주문하겠', '결제하겠', '좋습니다', '그거 주세요']
NO = ['사지 않', '비싸', '생각해', '다음에', '알려', '?', '얼마']
STOP = ['안 살', '안살', '말고', '보류', '환불', '취소']
FRESH = '채소 야채 나물 계란 곡물 생수 김치 과일 생선 두부'.split()

def min_price(u, n):
    c = u.get('cost') or 0
    h = ((u.get('expires_at') or 9e12) - n) / 3600
    if h <= 6:
        return max(300, math.ceil(c * .3))
    if h <= 24:
        return max(300, math.ceil(c * .6))
    return math.ceil((c * 1.1 + 210) / .99)

def issue(k, st, key, u, price, now, files):
    res = {x: v for x, v in st.get('reserved').items() if v.get('customer_key') != key}
    st['reserved'] = res
    payload = {'id': str(uuid.uuid4()), 'shop': 'choo-chu', 'shop_url': k.shop_url, 'item': u.get('sku'), 'price': price, 'task': str(uuid.uuid4()), 'currency': 'credits', 'iat': now, 'unit': u.get('unit'), 'claim': str(u.get('grade') or '')}
    jwt = k.sign_jwt(payload, 'shop')
    res[u.get('unit')] = {'customer_key': key, 'until': now + 600}
    st['offers'].pop(key, None)
    with open(files[0], 'w', encoding='utf-8') as f:
        json.dump(st, f, ensure_ascii=False)
    rec = {'ts': now, 'customer_key': key, 'sku': u.get('sku'), 'unit': u.get('unit'), 'price': price, 'result': 'checkout_issued'}
    with open(files[1], 'a', encoding='utf-8') as f:
        f.write(json.dumps(rec, ensure_ascii=False) + chr(10))
    return jwt

def run(a, k):
    text = str(a.get('text') or '')
    key = str(a.get('claimed_from') or '').strip()
    if not key or any(w in text for w in STOP):
        return {'defer': True}
    files = ['test_state.json', 'test_ledger.jsonl'] if k.testing else ['handler_state.json', 'ledger.jsonl']
    now = int(time.time())
    try:
        st = json.load(open(files[0], encoding='utf-8'))
    except:
        st = {}
    offers = st.setdefault('offers', {})
    st['reserved'] = {x: v for x, v in (st.get('reserved') or {}).items() if v.get('until', 0) > now}
    if k.testing and '_inventory' in a:
        units = a.get('_inventory')
    else:
        units = httpx.get(k.market + '/api/inventory', headers={'authorization': 'Bearer ' + k.token('shop')}, timeout=15).json().get('units', [])
    free = []
    for u in units:
        h = ((u.get('expires_at') or 9e12) - now) / 3600
        if h > 0 and u.get('unit') and u.get('cost') is not None and u.get('unit') not in st.get('reserved'):
            free.append((h, u))
    offer = offers.get(key)
    if isinstance(offer, dict) and now - int(offer.get('ts', 0)) <= 1800 and any(w in text for w in YES) and not any(w in text for w in NO):
        cand = [x for x in free if x[1].get('unit') == offer.get('unit')] or sorted([x for x in free if x[1].get('sku') == offer.get('sku')], key=lambda x: x[0])
        if cand:
            h, u = cand[0]
            price = int(offer.get('price') or 0)
            if price >= min_price(u, now):
                jwt = issue(k, st, key, u, price, now, files)
                reply = f"{u.get('name')} {price:,}크레딧, 결제서를 보내 드립니다. 10분 안에 결제해 주세요."
                return {'reply': reply, 'data': {'checkout_jwt': jwt}, 'state': 'completed'}
    words = [w for w in text.replace('?', ' ').split() if len(w) >= 2]
    rows = []
    for h, u in free:
        t = f"{u.get('name')} {u.get('category')}"
        if not any(w in t or (len(w) >= 3 and w[:2] in t) for w in words):
            continue
        fresh = any(w in t for w in FRESH)
        floor = min_price(u, now)
        p = 0 if h <= 24 else {'A': .8, 'B': .75}.get(u.get('grade'), 0) * (u.get('list_price') or 0) if fresh else floor * 1.05
        rows.append((0 if h <= 24 else 1 if fresh else 2, max(floor, round(p)), h, u))
    if not rows:
        return {'defer': True}
    tier, price, h, u = min(rows, key=lambda r: r[:2])
    jwt = issue(k, st, key, u, price, now, files)
    exp = u.get('expires_at')
    when = f'유통기한 임박 특가, 약 {round(h) or 1}시간 뒤 만료' if tier == 0 else '소비기한 ' + time.strftime('%m/%d', time.localtime(exp)) + '까지' if exp else '소비기한 미상'
    name = str(u.get('name'))[:40]
    others = [x for x in dict.fromkeys(str(r[3].get('name'))[:40] for r in rows) if x != name]
    reply = f"{name} {u.get('grade') or '?'}등급({when}), {price:,}크레딧입니다. 결제서를 함께 보내드려요. 원하시면 바로 결제하시고, 다른 상품을 원하시면 말씀해 주세요."
    if others:
        reply += ' 다른 상품: ' + ', '.join(others[:3]) + '.'
    return {'reply': reply, 'data': {'checkout_jwt': jwt}, 'state': 'input_required'}
