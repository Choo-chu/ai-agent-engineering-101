import json
import math
import time
import httpx


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
    return st


def run(a, k):
    key = str(a.get('customer_key') or '').strip()
    sku = str(a.get('sku') or '').strip()
    price = int(a.get('price') or 0)
    if not key or not sku or price <= 0:
        return {'ok': False, 'error': 'customer_key, sku, price are required'}
    costs = []
    for u in get_units(a, k):
        if u.get('sku') == sku and u.get('cost') is not None:
            costs.append(float(u['cost']))
    if not costs:
        return {'ok': False, 'error': 'no unit of this sku in stock'}
    floor = math.ceil((max(costs) * 1.1 + 210) / 0.99)
    if price < floor:
        return {'ok': False, 'floor': floor}
    path = 'handler_state.json'
    if k.testing:
        path = 'test_state.json'
    st = load(path)
    st['offers'][key] = {'sku': sku, 'price': price, 'ts': int(time.time())}
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(st, f, ensure_ascii=False)
    return {'ok': True, 'sku': sku, 'price': price, 'floor': floor}
