import time
def test(f, k):
    v = dict(unit='s6',sku='S',name='면',grade='A',cost=1000,list_price=3000)
    u = dict(v, unit='s5', expires_at=time.time()+9e3)
    r = f(dict(_inventory=[u, v]), k).get('stock').splitlines()
    assert 'S|면|A|1|2.5|300' in r
    assert 'S|면|A|1|1324|3000|1390' in r
