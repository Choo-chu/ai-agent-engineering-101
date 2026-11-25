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
    sf = 'test_state.json' if k.testing else 'handler_state.json'
    try:
        res = json.load(open(sf, encoding='utf-8')).get('reserved') or {}
    except Exception:
        res = {}
    if k.testing and '_inventory' in a:
        units = a.get('_inventory')
    else:
        head = {'authorization': 'Bearer ' + k.token('shop')}
        units = httpx.get(k.market + '/api/inventory', headers=head, timeout=15).json().get('units', [])
    n = time.time()
    low = 0
    count = {}
    for u in units:
        h = ((u.get('expires_at') or 9e12) - n) / 3600
        if h <= 0 or u.get('cost') is None or res.get(u.get('unit'), {}).get('until', 0) > n:
            continue
        if h <= 24:
            p = min_price(u, n)
            low = min(low, p) if low else p
        name = str(u.get('name')).split(']')[-1].strip()[:12].strip()
        count[name] = count.get(name, 0) + 1
    names = sorted(count, key=lambda x: -count.get(x))[:8]
    desc = 'choo-chu | 신선식품 정직 가게. 물어보시면 바로 결제서까지 드려요. '
    if names:
        desc += '지금 있는 것: ' + ', '.join(names) + '. '
    if low:
        step = 1000 if low >= 1000 else 100
        desc += f'임박 특가 {low // step * step:,}원대부터. '
    desc = (desc + '등급·소비기한 정직 표기.')[:300]
    path = 'test_card.json' if k.testing else 'card.json'
    try:
        with open(path, 'w', encoding='utf-8') as f:
            json.dump({'name': k.name, 'description': desc}, f, ensure_ascii=False)
        written = True
    except Exception as e:
        written = False
        desc = desc + ' / ' + type(e).__name__
    return {'ok': written, 'written': written, 'description': desc, 'chars': len(desc)}
