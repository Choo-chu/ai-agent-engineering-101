import json
def test(f,k):
 a=dict(claimed_from='A',_inventory=[dict(unit='u',sku='G',cost=1000)])
 o=dict(sku='G',price=2500,ts=9e9)
 json.dump(dict(offers=dict(A=o)),open('test_state.json','w'))
 assert f(dict(a,text='안 살게'),k)['defer']
 assert f(dict(a,text='살게'),k)['data']['checkout_jwt']
