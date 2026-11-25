import json
def test(f,k):
 u=dict(unit='h1',sku='H',cost=9)
 v=dict(u,unit='h2',expires_at=9e11)
 s='test_state.json'
 json.dump({'offers':{'C':{'sku':'H','price':300,'ts':9e9,'unit':'h1'}}},open(s,'w'))
 f(dict(claimed_from='C',text='구매하겠습니다',_inventory=[u,v]),k)
 assert 'h1' in open(s).read()
