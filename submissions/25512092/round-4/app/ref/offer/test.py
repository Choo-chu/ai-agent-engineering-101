import time
def test(f, k):
    v = dict(unit='o1',sku='O',cost=1000,grade='A')
    u = dict(v,unit='o2',grade='C',expires_at=time.time()+9e3)
    a = dict(customer_key='B',sku='O',price=300,_inventory=[u,v])
    assert f(a,k).get('unit')=='o2'
    assert f(dict(a,grade='A'),k).get('floor') == 1324
