import json
import math
import time
import httpx

def min_price(u, n):
    c = u.get('cost') or 0
    h = ((u.get('expires_at') or 9e12) - n) / 3600
    if h <= 6:
        return max(300, math.ceil(c * 0.2))
    if h <= 24:
        return max(300, math.ceil(c * 0.4))
    return math.ceil((c * 1.1 + 210) / 0.99)

def run(a, k):
    key = str(a.get('customer_key') or '').strip()
    sku = str(a.get('sku') or '').strip()
    grade = str(a.get('grade') or '').strip()
    price = int(a.get('price') or 0)
    if not key or not sku or price <= 0:
        return {'ok': False, 'error': 'need key, sku, price'}
    path = 'test_state.json' if k.testing else 'handler_state.json'
    try:
        st = json.load(open(path, encoding='utf-8'))
    except Exception:
        st = {}
    res = st.get('reserved') or {}
    if k.testing and '_inventory' in a:
        units = a.get('_inventory')
    else:
        units = httpx.get(k.market + '/api/inventory', headers={'authorization': 'Bearer ' + k.token('shop')}, timeout=15).json().get('units', [])
    n = time.time()
    best = {}
    for u in units:
        h = ((u.get('expires_at') or 9e12) - n) / 3600
        if u.get('sku') != sku or u.get('cost') is None or h <= 0:
            continue
        if res.get(u.get('unit'), {}).get('until', 0) > n:
            continue
        if grade and grade != ('임박' if h <= 24 else u.get('grade')):
            continue
        p = min_price(u, n)
        if p < best.get('p', 9e12):
            best = {'p': p, 'unit': u.get('unit')}
    if not best:
        return {'ok': False, 'error': 'no free unit'}
    floor = best.get('p')
    if price < floor:
        return {'ok': False, 'floor': floor}
    offers = st.setdefault('offers', {})
    offers[key] = {'sku': sku, 'price': price, 'ts': int(n), 'unit': best.get('unit')}
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(st, f, ensure_ascii=False)
    return {'ok': True, 'unit': best.get('unit'), 'price': price, 'floor': floor}
