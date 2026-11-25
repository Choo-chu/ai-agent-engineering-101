import time
def test(f, k):
    v = dict(unit='q1', sku='Q', name='사과 2kg', grade='A', cost=1000, list_price=3000)
    u = dict(v, unit='q2', grade='C', expires_at=time.time() + 9e3)
    w = dict(v, unit='q3', sku='R', name='총각김치')
    r = f(dict(customer_key='D', query='사과', _inventory=[v, u, w]), k)
    assert r['price'] == 300 and '바로 결제서' in r['say']
    r = f(dict(customer_key='D', query='배추김치 2kg 등급', _inventory=[v, u, w]), k)
    assert not r['ok'] and '없습니다' in r['say']
    assert '총각' not in f(dict(customer_key='D', query='김치, 총각김치 말고', _inventory=[w, u]), k)['say']
