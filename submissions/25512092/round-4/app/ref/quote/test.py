import time
def test(f, k):
    v = dict(unit='q1', sku='Q', name='사과 2kg', grade='A', cost=1000, list_price=3000)
    u = dict(v, unit='q2', grade='C', expires_at=time.time() + 9e3)
    w = dict(v, unit='q3', sku='R', name='총각김치 소비기한 7일')
    x = dict(v, unit='q4', sku='G', name='잘구워진 구운계란')
    b = dict(customer_key='D', _voc='삼겹살', _inventory=[v, u, w, x])
    r = f(dict(b, query='사과'), k)
    assert r['price'] == 300 and '바로 결제서' in r['say']
    assert f(dict(b, query='A등급 사과'), k)['grade'] == 'A'
    assert f(dict(b, query='사과, 임박 말고'), k)['grade'] == 'A'
    assert not f(dict(b, query='사과 25시간 이하 제외', _inventory=[u]), k)['ok']
    for q in ['소비기한 알려주세요', '구워 먹을 삼겹살']:
        assert not f(dict(b, query=q), k)['ok']
    r = f(dict(b, query='배추김치 2kg 등급'), k)
    assert not r['ok'] and '없습니다' in r['say']
    assert '총각' not in f(dict(b, query='김치, 총각김치 말고', _inventory=[w, u]), k)['say']
