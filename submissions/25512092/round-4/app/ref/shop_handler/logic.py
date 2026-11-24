import json
import math
import time
import uuid
import httpx

YES = ['살게', '할게', '그걸로', '주문할게', '좋아요', '살래', '구매할게', '결제할게']
NO = ['안 살', '안살', '사지 않', '보류', '말고', '비싸', '생각해', '다음에']


def get_units(a, k):
    if k.testing and '_inventory' in a:
        return a['_inventory']
    url = k.market + '/api/inventory'
    head = {'authorization': 'Bearer ' + k.token('shop')}
    r = httpx.get(url, headers=head, timeout=15)
    return r.json().get('units', [])


def load(path):
    try:
        with open(path, encoding='utf-8') as f:
            st = json.load(f)
    except Exception:
        st = {}
    if not isinstance(st, dict):
        st = {}
    if not isinstance(st.get('offers'), dict):
        st['offers'] = {}
    if not isinstance(st.get('reserved'), dict):
        st['reserved'] = {}
    return st


def run(a, k):
    text = str(a.get('text') or '')
    key = str(a.get('claimed_from') or '').strip()
    if not key:
        return {'defer': True}
    if any(w in text for w in NO):
        return {'defer': True}
    if not any(w in text for w in YES):
        return {'defer': True}
    sf = 'handler_state.json'
    lf = 'ledger.jsonl'
    if k.testing:
        sf = 'test_state.json'
        lf = 'test_ledger.jsonl'
    now = int(time.time())
    st = load(sf)
    offer = st['offers'].get(key)
    if not isinstance(offer, dict):
        return {'defer': True}
    if now - int(offer.get('ts', 0)) > 1800:
        return {'defer': True}
    res = {}
    for unit_id, v in st['reserved'].items():
        if isinstance(v, dict) and v.get('until', 0) > now:
            res[unit_id] = v
    free = []
    for u in get_units(a, k):
        if u.get('sku') != offer.get('sku') or not u.get('unit'):
            continue
        if u['unit'] in res or u.get('cost') is None:
            continue
        free.append(u)
    if not free:
        return {'defer': True}
    free.sort(key=lambda x: float(x['cost']))
    u = free[0]
    price = int(offer['price'])
    floor = math.ceil((float(u['cost']) * 1.1 + 210) / 0.99)
    if price < floor:
        return {'defer': True}
    payload = {
        'id': str(uuid.uuid4()),
        'shop': 'choo-chu',
        'shop_url': k.shop_url,
        'item': u['sku'],
        'price': price,
        'task': str(uuid.uuid4()),
        'currency': 'credits',
        'iat': now,
        'unit': u['unit'],
        'claim': str(u.get('grade') or ''),
    }
    jwt = k.sign_jwt(payload, 'shop')
    res[u['unit']] = {'customer_key': key, 'until': now + 600}
    st['reserved'] = res
    st['offers'].pop(key, None)
    with open(sf, 'w', encoding='utf-8') as f:
        json.dump(st, f, ensure_ascii=False)
    rec = {'ts': now, 'customer_key': key, 'sku': u['sku'], 'unit': u['unit'], 'price': price}
    rec['result'] = 'checkout_issued'
    with open(lf, 'a', encoding='utf-8') as f:
        f.write(json.dumps(rec, ensure_ascii=False) + '\n')
    name = u.get('name') or u['sku']
    reply = name + ' ' + str(price) + '크레딧, 결제서를 보내 드립니다. 10분 안에 결제해 주세요.'
    return {'reply': reply, 'data': {'checkout_jwt': jwt}, 'state': 'completed'}
