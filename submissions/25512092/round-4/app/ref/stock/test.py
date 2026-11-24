def test(f,k):
 u=dict(unit='s',sku='G',name='새우 과자',grade='C',cost=1000,list_price=3000)
 r=f(dict(query='과자',_inventory=[u]),k)
 assert 'G|새우 과자' in r['stock']
 assert f(dict(query='쌀',_inventory=[u]),k)['count']==0
