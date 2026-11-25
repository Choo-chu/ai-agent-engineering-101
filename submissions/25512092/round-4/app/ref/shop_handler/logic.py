import json
import math
import time
import uuid
import httpx

STOP = ['안 살', '안살', '취소', '환불', '보류']
FRESH = '채소 야채 나물 계란 곡물 생수 김치 과일 생선 두부'.split()

def hit(w, t):
    return len(w) > 1 and w[:2] in t and w[:2] not in '등급 재고 가격' and w[0] > '9'

def run(a, k):
    s = a.get('text') or ''
    ck = a.get('claimed_from') or ''
    p = 'test_' if k.testing else ''
    fs = [(p or 'handler_') + 'state.json', p + 'ledger.jsonl']
    n = int(time.time())
    rec = {'ts': n, 'customer_key': ck, 'text': s}
    def log(**x):
        open(fs[1], 'a', encoding='utf-8').write(json.dumps(dict(rec, **x)) + chr(10))
        return {'defer': True}
    if not ck or any(w in s for w in STOP):
        return log(result='defer_stop')
    try:
        st = json.load(open(fs[0], encoding='utf-8'))
    except:
        st = {}
    rv = {x: v for x, v in st.get('reserved', {}).items() if v.get('until', 0) > n}
    us = a.get('_inventory') or httpx.get(k.market + '/api/inventory', headers={'authorization': 'Bearer ' + k.token('shop')}, timeout=15).json()['units']
    ex, ws = [], []
    for c in s.replace('?', ',').replace('. ', ',').replace('빼고', '말고').split(','):
        b, m, r = c.partition('말고')
        (ex if m else ws).extend(b.split())
        ws += r.split()
    rs = []
    for u in us:
        h = ((u.get('expires_at') or 9e12) - n) / 3600
        t = f"{u['name']} {u.get('category')}"
        if h <= 0 or not u.get('cost') or rv.get(u['unit'], {}).get('customer_key', ck) != ck or any(hit(w, u['name']) for w in ex) or not any(hit(w, t) for w in ws):
            continue
        c = u['cost']
        fl = max(300, math.ceil(c * (.3 if h <= 6 else .6))) if h <= 24 else math.ceil((c * 1.1 + 210) / .99)
        p = 0 if h <= 24 else {'A': .8, 'B': .75}.get(u['grade'], 0) * u.get('list_price', 0) if any(w in t for w in FRESH) else fl * 1.05
        rs.append((h > 24, max(fl, round(p)), h, u))
    if not rs:
        return log(result='defer_nomatch')
    _, pr, h, u = min(rs, key=lambda r: r[:2])
    rec.update(sku=u['sku'], name=u['name'])
    old = [v for v in rv.values() if v['customer_key'] == ck and v.get('sku') == u['sku']]
    if old:
        jwt = old[0]['jwt']
        log(result='checkout_reused')
        say = '앞서 보낸 결제서로 결제해 주세요.'
    else:
        pl = {'id': str(uuid.uuid4()), 'shop': 'choo-chu', 'shop_url': k.shop_url, 'item': u['sku'], 'price': pr, 'task': str(uuid.uuid4()), 'currency': 'credits', 'iat': n, 'unit': u['unit'], 'claim': u['grade'] or ''}
        jwt = k.sign_jwt(pl, 'shop')
        st['reserved'] = {x: v for x, v in rv.items() if v['customer_key'] != ck}
        st['reserved'][u['unit']] = {'customer_key': ck, 'until': n + 600, 'sku': u['sku'], 'jwt': jwt}
        json.dump(st, open(fs[0], 'w'))
        log(unit=u['unit'], price=pr, result='checkout_issued')
        say = f"{u['grade']}등급({round(h) or 1}시간 뒤 만료) {pr:,}크레딧, 결제서 보내요."
    return {'reply': f"{u['name']} {say}", 'data': {'checkout_jwt': jwt}, 'state': 'input_required'}
