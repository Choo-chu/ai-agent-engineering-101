import time
def test(f, k):
    u = dict(unit='i1',sku='I',name='시금치',category='채소',grade='C',cost=4000,expires_at=time.time()+9e3)
    r = f(dict(_inventory=[u]), k)
    assert r.get('written') and '지금 있는 것: 시금치. 임박 특가 1,000원대부터' in r.get('description')
