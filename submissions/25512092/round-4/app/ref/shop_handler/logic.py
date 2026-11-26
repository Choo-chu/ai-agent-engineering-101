import json, math, re, time, uuid, httpx
SW = '기한 국내산 국산 신선 등급 가격 재고 상품 결제서 영수증 receipt 있나 있어 주세요 알려 얼마 오늘 구매 판매 시간 보관 다른 포장 구성 대한 세트 반찬 찌개 냉장 냉동 친환경 모듬 제철'.split()
GN = '나물 채소 야채 과일 생선 고기 돼지고기 간식'.split()
FR = '채소 야채 나물 계란 곡물 생수 김치 과일 생선 두부'.split()
NO = '않겠|않을|안 ?살|아니|필요 ?없|취소|환불|보류'
FO = '임박[^ ]*( 상품| 품목)?[은는이을과]? ?(제외|[말빼]고|안 ?사|사지)|임박한 [건것]|임박품|신선한 ?([거것]|상품)|넉넉|충분|짧'
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
    s = a.get('text') or ''
    ck = a.get('claimed_from') or ''
    fs = ['test_state.json', 'test_ledger.jsonl'] if k.testing else ['handler_state.json', 'ledger.jsonl']
    n = int(time.time())
    rec = {'ts': n, 'customer_key': ck, 'text': s}
    def log(**x):
        open(fs[1], 'a').write(json.dumps(dict(rec, **x)) + chr(10))
        return {'defer': True}
    st = json.loads(rd(fs[0]) or '{}')
    rv = {x: v for x, v in st.get('reserved', {}).items() if v['until'] > n}
    st['reserved'] = {x: v for x, v in rv.items() if v.get('ck') != ck}
    cl = re.split('[?,!]|[.] |[.]$', re.sub('[^가-힣A-Za-z0-9 ?,!.]', ' ', re.sub('(SKU ?)?G[0-9a-f]{8}', ' ', s)))
    if not ck or any(re.search(NO, c) and not re.search('전에|없는|않은|안 되|않으면|없으면|면 |엉뚱|다른|임박|낮은|어도', c) for c in cl):
        json.dump(st, open(fs[0], 'w'))
        return log(result='defer_stop')
    us = a.get('_inventory') or httpx.get(k.market + '/api/inventory', headers={'authorization': 'Bearer ' + k.token('shop')}, timeout=15).json()['units']
    try:
        V = set(re.findall('[가-힣]{2,}', ' '.join(c['name'] for c in json.loads(rd('analysis/data/live_catalog.json') or '[]') if c['kind'] == 'food') + a.get('_voc', '')))
        assert V
    except:
        return log(result='defer_catalog')
    ex, ws = [], []
    for c in cl:
        *e, w = re.split('[말빼]고', c)
        ex += ' '.join(e).split()
        ws += [] if re.search(NO, c) else w.split()
    N = {u['name'] for u in us}
    it = [any(hit(w, t) for t in N) for w in ws if ok(w) and Q(w) & V or any(hit(w, t) for t in N)]
    rk = 2 * sum(it) > len(it)
    sk = re.findall('G[0-9a-f]{8}', s)
    lo = re.search('C ?등급[^.?!]{0,12}(제외|[말빼]고|않|안 ?사)|더 높|등급 이상|[AB] ?등급', s)
    G = 'A' if re.search('A ?등급|등급[이은는가]? ?A[^a-zA-Z]', s) and not re.search('B ?등급', s) else 'AB' if lo else 'ABC'
    m = re.search('([0-9]+) ?시간 ?(이하|미만)', s)
    hm = int(m[1]) if m else 48 if '이틀' in s else 24 if re.search(FO, s) else 0
    rs = []
    for u in us:
        h = ((u.get('expires_at') or 9e12) - n) / 3600
        t = u['name']
        sc = sum(1 if q in GN else 10 for q in {min(Q(w), key=len) for w in ws if hit(w, t)}) + 100 * (u['sku'] in sk)
        if h <= 0 or u['unit'] in st['reserved'] or any(hit(w, t) for w in ex) or sc < 1 + 19 * bool(sk) or any(re.search('[0-9] ?' + z, s) and not re.search(y + ' ?' + z, s) for y, z in re.findall('([0-9]+) ?(구|kg)', t)) or not (rk or all(x in s for x in re.sub('[([][^])]*[])]', '', t.split('/')[0]).split() if ok(x))):
            continue
        fl = max(300, math.ceil(u['cost'] * (.2 if h <= 6 else .4))) if h <= 24 else math.ceil((u['cost'] * 1.1 + 210) / .99)
        q = 0 if h <= 24 else {'A': .8, 'B': .75}.get(u['grade'], 0) * u['list_price'] if any(w in f"{t} {u.get('category')}" for w in FR) else fl * 1.05
        rs.append((-sc, u['grade'] not in G or h <= hm, max(fl, round(q)), h, u))
    if not rs:
        return log(result='defer_nomatch')
    _, bad, pr, h, u = min(rs, key=lambda r: r[:3])
    rec['sku'] = u['sku']
    if bad:
        return log(result='defer_cond')
    jwt = ([v['jwt'] for v in rv.values() if v.get('ck') == ck and v['sku'] == u['sku']] or [0])[0]
    if jwt:
        log(result='checkout_reused')
        say = '보낸 결제서 그대로예요.'
    else:
        jwt = k.sign_jwt({'id': uuid.uuid4().hex, 'shop': k.name, 'shop_url': k.shop_url, 'item': u['sku'], 'price': pr, 'task': uuid.uuid4().hex, 'currency': 'credits', 'iat': n, 'unit': u['unit'], 'claim': u['grade']}, 'shop')
        st['reserved'][u['unit']] = {'ck': ck, 'until': n + 600, 'sku': u['sku'], 'jwt': jwt}
        json.dump(st, open(fs[0], 'w'))
        log(unit=u['unit'], price=pr, result='checkout_issued')
        say = f"{u['grade']}등급({round(h) or 1}시간 뒤 만료) {pr:,}크레딧, 결제서 보내요."
    return {'reply': f"{u['name']} {say}", 'data': {'checkout_jwt': jwt}, 'state': 'input_required'}
