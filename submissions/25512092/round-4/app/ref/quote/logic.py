import json
import math
import time
import httpx

FRESH = '채소 야채 나물 계란 곡물 생수 김치 과일 생선 두부'.split()

def min_price(u, n):
    c = u.get('cost') or 0
    h = ((u.get('expires_at') or 9e12) - n) / 3600
    if h <= 6:
        return max(300, math.ceil(c * .3))
    if h <= 24:
        return max(300, math.ceil(c * .6))
    return math.ceil((c * 1.1 + 210) / .99)

def run(a, k):
    key = a.get('customer_key')
    ws = (a.get('query') or '').split()
    sf = 'test_state.json' if k.testing else 'handler_state.json'
    try:
        st = json.load(open(sf, encoding='utf-8'))
    except:
        st = {}
    res = st.get('reserved') or {}
    if k.testing and '_inventory' in a:
        us = a.get('_inventory')
    else:
        us = httpx.get(k.market + '/api/inventory', headers={'authorization': 'Bearer ' + k.token('shop')}, timeout=15).json().get('units', [])
    n = time.time()
    rs = []
    for u in us:
        h = ((u.get('expires_at') or 9e12) - n) / 3600
        if h <= 0 or u.get('cost') is None or res.get(u.get('unit'), {}).get('until', 0) > n:
            continue
        t = f"{u.get('name')} {u.get('category')}"
        fresh = any(w in t for w in FRESH)
        floor = min_price(u, n)
        p = 0 if h <= 24 else {'A': .8, 'B': .75}.get(u.get('grade'), 0) * (u.get('list_price') or 0) if fresh else floor * 1.05
        rs.append((not any(w in t for w in ws), 0 if h <= 24 else 1 if fresh else 2, max(floor, round(p)), h, u))
    rs.sort(key=lambda r: r[:3])
    names = list(dict.fromkeys(r[4].get('name') for r in rs if r[0] == rs[0][0]))
    if not key or not rs or rs[0][0]:
        return {'ok': False, 'others': names[:3], 'say': '그 상품은 지금 없습니다. 있는 상품: ' + ', '.join(names[:3])}
    _, tier, price, h, u = rs[0]
    gr = u.get('grade') or '?'
    st.setdefault('offers', {})[key] = {'sku': u.get('sku'), 'price': price, 'unit': u.get('unit'), 'grade': gr, 'ts': int(n)}
    json.dump(st, open(sf, 'w', encoding='utf-8'), ensure_ascii=False)
    exp = u.get('expires_at')
    when = f'유통기한 임박 특가, 약 {round(h) or 1}시간 뒤 만료' if tier == 0 else '소비기한 ' + time.strftime('%m/%d', time.localtime(exp)) + '까지' if exp else '소비기한 미상'
    others = names[1:4]
    extra = '다른 상품: ' + ', '.join(others) + '. ' if others else ''
    say = f"{names[0]} {gr}등급({when}), {price:,}크레딧입니다. {extra}구매하시려면 '살게요'라고 답해 주세요."
    return {'ok': True, 'sku': u.get('sku'), 'name': names[0], 'grade': gr, 'price': price, 'expires_h': round(h, 1) if exp else None, 'others': others, 'say': say}
