import json
from math import ceil
import time
import httpx
FRESH = '채소 야채 나물 계란 곡물 생수 김치 과일 생선 두부'.split()
def min_price(u, n):
    c = u.get('cost') or 0
    h = ((u.get('expires_at') or 9e12) - n) / 3600
    if h <= 6:
        return max(300, ceil(c * .2))
    if h <= 24:
        return max(300, ceil(c * .4))
    return ceil((c * 1.1 + 210) / .99)
def run(a, k):
    q = (a.get('query') or '').split()
    try:
        res = json.load(open('test_state.json' if k.testing else 'handler_state.json', encoding='utf-8')).get('reserved', {})
    except:
        res = {}
    if k.testing and '_inventory' in a:
        us = a.get('_inventory')
    else:
        us = httpx.get(k.market + '/api/inventory', headers={'authorization': 'Bearer ' + k.token('shop')}, timeout=15).json().get('units', [])
    n = time.time()
    hot, rows = {}, {}
    for u in us:
        h = ((u.get('expires_at') or 9e12) - n) / 3600
        if h <= 0 or res.get(u.get('unit'), {}).get('until', 0) > n:
            continue
        text = f"{u.get('name')}{u.get('category')}"
        if q and not any(w in text for w in q):
            continue
        grade = u.get('grade') or '?'
        key = f"{u.get('sku')}|{str(u.get('name'))[:30]}|{grade}"
        if h <= 24:
            g = hot.setdefault(key, {'n': 0, 'h': h, 'p': 9e9})
            g['h'] = min(g.get('h'), h)
            g['p'] = min(g.get('p'), min_price(u, n))
        else:
            g = rows.setdefault(key, {'n': 0, 'cost': 0, 'grade': grade, 'list': u.get('list_price') or 0, 'fresh': any(w in text for w in FRESH)})
            g['cost'] = max(g.get('cost'), u.get('cost') or 0)
        g['n'] += 1
    out = ['[임박] sku|name|grade|count|hours|price']
    out += [f"{key}|{g.get('n')}|{round(g.get('h'), 1)}|{g.get('p')}" for key, g in hot.items()]
    out.append('[일반] sku|name|grade|count|floor|list|price')
    for key, g in rows.items():
        floor = min_price(g, n)
        price = round(floor * 1.05)
        if g.get('fresh'):
            price = round({'A': .8, 'B': .75}.get(g.get('grade'), 0) * g.get('list'))
        out.append(f"{key}|{g.get('n')}|{floor}|{g.get('list')}|{max(floor, price)}")
    return {'stock': chr(10).join(out)}
