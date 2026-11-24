import json
import math
import time
import httpx


def run(a, k):
    words = str(a.get('query') or '').split()
    path = 'test_state.json' if k.testing else 'handler_state.json'
    try:
        res = json.load(open(path, encoding='utf-8'))['reserved']
    except Exception:
        res = {}
    if k.testing and '_inventory' in a:
        units = a['_inventory']
    else:
        head = {'authorization': 'Bearer ' + k.token('shop')}
        units = httpx.get(k.market + '/api/inventory', headers=head, timeout=15).json()['units']
    now = time.time()
    rows = {}
    for u in units:
        r = res.get(u.get('unit'))
        if isinstance(r, dict) and r.get('until', 0) > now:
            continue
        text = str(u.get('name', '')) + ' ' + str(u.get('category', ''))
        if words and not any(w in text for w in words):
            continue
        sku = u.get('sku')
        if sku not in rows:
            rows[sku] = [str(u.get('name', ''))[:30], {}, 0, u.get('list_price', '')]
        g = rows[sku]
        grade = str(u.get('grade') or '?')
        g[1][grade] = g[1].get(grade, 0) + 1
        g[2] = max(g[2], float(u.get('cost') or 0))
    lines = ['sku|name|grades|floor|list']
    for sku, g in rows.items():
        counts = ' '.join(x + str(n) for x, n in sorted(g[1].items()))
        floor = math.ceil((g[2] * 1.1 + 210) / 0.99)
        lines.append(f'{sku}|{g[0]}|{counts}|{floor}|{g[3]}')
    return {'count': len(rows), 'stock': '\n'.join(lines)[:4000]}
