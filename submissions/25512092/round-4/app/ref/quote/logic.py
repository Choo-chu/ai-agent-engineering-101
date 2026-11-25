import json
import math
import time
import httpx

FRESH = '채소 야채 나물 계란 곡물 생수 김치 과일 생선 두부'.split()

def min_price(u, n):
    c = u['cost']
    h = ((u.get('expires_at') or 9e12) - n) / 3600
    return max(300, math.ceil(c * (.3 if h <= 6 else .6))) if h <= 24 else math.ceil((c * 1.1 + 210) / .99)

def hit(w, t):
    return len(w) > 1 and w[:2] in t and w[:2] not in '등급 재고 가격' and not w[0].isdigit()

def run(a, k):
    key = a.get('customer_key')
    ex, sg, ws = [], [], []
    for w in str(a.get('query') or '').replace('?', ',').replace('빼고', '말고').split():
        if '말고' in w:
            ex += sg + [w.split('말고')[0]]
            sg = []
        else:
            sg.append(w.strip(',.'))
            if w[-1] in ',.':
                ws += sg
                sg = []
    ws += sg
    sf = 'test_state.json' if k.testing else 'handler_state.json'
    try:
        st = json.load(open(sf, encoding='utf-8'))
    except:
        st = {}
    res = st.get('reserved') or {}
    if k.testing and '_inventory' in a:
        us = a['_inventory']
    else:
        us = httpx.get(k.market + '/api/inventory', headers={'authorization': 'Bearer ' + k.token('shop')}, timeout=15).json()['units']
    n = time.time()
    rs = []
    for u in us:
        h = ((u.get('expires_at') or 9e12) - n) / 3600
        if h <= 0 or not u.get('cost') or res.get(u['unit'], {}).get('until', 0) > n or any(hit(w, u['name']) for w in ex):
            continue
        t = f"{u['name']} {u.get('category')}"
        fl = min_price(u, n)
        p = 0 if h <= 24 else {'A': .8, 'B': .75}.get(u['grade'], 0) * (u.get('list_price') or 0) if any(w in t for w in FRESH) else fl * 1.05
        rs.append((not any(hit(w, t) for w in ws), h > 24, max(fl, round(p)), h, u))
    rs.sort(key=lambda r: r[:3])
    names = list(dict.fromkeys(r[4]['name'] for r in rs if r[0] == rs[0][0]))
    if not key or not rs or rs[0][0]:
        return {'ok': False, 'others': names[:3], 'say': '그 상품은 지금 없습니다. 대신 있는 상품: ' + ', '.join(names[:3])}
    _, tier, price, h, u = rs[0]
    gr = u['grade'] or '?'
    st.setdefault('offers', {})[key] = {'sku': u['sku'], 'price': price, 'unit': u['unit'], 'grade': gr, 'ts': int(n)}
    json.dump(st, open(sf, 'w', encoding='utf-8'), ensure_ascii=False)
    when = f'임박 특가, 약 {round(h) or 1}시간 뒤 만료' if h <= 24 else f'소비기한 약 {round(h / 24)}일'
    others = names[1:4]
    extra = '다른 상품: ' + ', '.join(others) + '. ' if others else ''
    say = f"{names[0]} {gr}등급({when}), {price:,}크레딧입니다. {extra}구매하시려면 원하시는 상품 이름을 말씀해 주세요. 바로 결제서를 드려요."
    return {'ok': True, 'sku': u['sku'], 'name': names[0], 'grade': gr, 'price': price, 'expires_h': round(h, 1), 'others': others, 'say': say}
