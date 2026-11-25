import time
def test(f, k):
    v = dict(unit='q1',sku='Q',name='사과',grade='A',cost=1000,list_price=3000)
    u = dict(v,unit='q2',grade='C',expires_at=time.time()+9e3)
    r = f(dict(customer_key='D',query='사과',_inventory=[v,u]),k)
    assert r.get('price')==300 and '살게요' in r.get('say')
