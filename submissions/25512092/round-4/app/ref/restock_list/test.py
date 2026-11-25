def test(f,k):
 i=[dict(sku='T1',qty=2),dict(sku='T2',qty=3),dict(sku='T3',qty=1)]
 r=f(dict(items=i,max_spend=4000),k)
 s=[x['result'] for x in r['results']]
 assert s==['bought','skipped_cap','bought']
 assert r['spent']==3000
