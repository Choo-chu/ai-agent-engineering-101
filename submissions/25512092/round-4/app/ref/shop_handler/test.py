def test(f, k):
    u = dict(unit='h3', sku='H', name='사과', grade='B', cost=900, list_price=3000)
    v = dict(u, unit='h4', sku='K', name='총각김치')
    a = dict(claimed_from='E', _inventory=[u, v, dict(v, unit='h5', sku='J', name='배추김치')])
    j = f(dict(a, text='사과 있어요?'), k)['data']['checkout_jwt']
    assert f(dict(a, text='사과 주세요'), k)['data']['checkout_jwt'] == j
    assert '배추김치' in f(dict(a, text='김치 주세요? 총각김치 말고'), k)['reply']
    assert f(dict(a, text='우유 있어요?'), k).get('defer')
