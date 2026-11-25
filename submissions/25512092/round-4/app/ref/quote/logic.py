import json
import math
import re
import time
import httpx

SW = '기한 국내산 신선 등급 가격 재고 상품 결제서 영수증 receipt 있나 있어 주세요 알려 얼마 오늘 구매 판매 시간 보관 다른 포장 구성 대한'.split()
NO = '않겠|않을|안 ?살|아니|필요 ?없|취소|환불|보류'
FRESH = '채소 야채 나물 계란 곡물 생수 김치 과일 생선 두부'.split()

def rd(f):
    try:
        return open(f, encoding='utf-8').read()
    except:
        return ''

def ok(w):
    return w[1:] and w[0] > '9' and not any(x in w for x in SW)

def Q(w):
    return {w, re.sub('(이나|으로|이랑|[은는이가을를와과나도만의로랑요])$', '', w)}

def hit(w, t):
    return ok(w) and any(x.endswith(q) for x in re.findall('[가-힣A-Za-z]+', t) for q in Q(w) if q[1:])

def run(a, k):
    key = a.get('customer_key')
    s = str(a.get('query') or '')
    ex, ws = [], []
    for c in re.split('[?,!]|[.] |[.]$', s):
        *e, w = re.split('[말빼]고', c)
        ex += ' '.join(e).split()
        ws += [] if re.search(NO, c) else w.split()
    g = re.findall('([ABC]) ?등급', s) + ['']
    fo = re.search('임박[^ ]* ?[말빼]고|임박한 [건것]|신선한 ?[거것]|넉넉', s)
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
    try:
        V = set(re.findall('[가-힣]{2,}', ' '.join(c['name'] for c in json.loads(rd('analysis/data/live_catalog.json') or '[]') if c['kind'] == 'food') + a.get('_voc', '')))
    except:
        V = set()
    N = {u['name'] for u in us}
    it = [any(hit(w, t) for t in N) for w in ws if ok(w) and Q(w) & V or any(hit(w, t) for t in N)]
    rk = V and 2 * sum(it) > len(it)
    n = time.time()
    rs = []
    for u in us:
        h = ((u.get('expires_at') or 9e12) - n) / 3600
        t = u['name']
        if h <= 0 or not u.get('cost') or res.get(u['unit'], {}).get('until', 0) > n or any(hit(w, t) for w in ex) or fo and h <= 24:
            continue
        c = u['cost']
        fl = max(300, math.ceil(c * (.3 if h <= 6 else .6))) if h <= 24 else math.ceil((c * 1.1 + 210) / .99)
        p = 0 if h <= 24 else {'A': .8, 'B': .75}.get(u['grade'], 0) * (u.get('list_price') or 0) if any(w in f"{t} {u.get('category')}" for w in FRESH) else fl * 1.05
        sc = len({w for w in ws if hit(w, t)}) if rk or all(x in s for x in re.sub('[([][^])]*[])]', '', t.split('/')[0]).split() if ok(x)) else 0
        rs.append((-sc, u['grade'] != g[0], max(fl, round(p)), h, u))
    rs.sort(key=lambda r: r[:3])
    names = list(dict.fromkeys(r[4]['name'] for r in rs if r[0] == rs[0][0]))
    if not key or not rs or not rs[0][0]:
        return {'ok': False, 'others': names[:3], 'say': '그 상품은 지금 없습니다. 대신 있는 상품: ' + ', '.join(names[:3])}
    _, _, price, h, u = rs[0]
    gr = u['grade'] or '?'
    st.setdefault('offers', {})[key] = {'sku': u['sku'], 'price': price, 'unit': u['unit'], 'grade': gr, 'ts': int(n)}
    json.dump(st, open(sf, 'w', encoding='utf-8'), ensure_ascii=False)
    when = f'임박 특가, 약 {round(h) or 1}시간 뒤 만료' if h <= 24 else f'소비기한 약 {round(h / 24)}일'
    others = names[1:4]
    extra = '다른 상품: ' + ', '.join(others) + '. ' if others else ''
    say = f"{names[0]} {gr}등급({when}), {price:,}크레딧입니다. {extra}구매하시려면 원하시는 상품 이름을 말씀해 주세요. 바로 결제서를 드려요."
    return {'ok': True, 'sku': u['sku'], 'name': names[0], 'grade': gr, 'price': price, 'expires_h': round(h, 1), 'others': others, 'say': say}
