def test(f, k):
    u = dict(unit='h3',sku='H',name='사과',grade='B',cost=900,list_price=3000)
    a = dict(claimed_from='E', _inventory=[u])
    assert f(dict(a, text='사과 있어요?'), k).get('data').get('checkout_jwt')
    assert f(dict(a, text='우유 있어요?'), k).get('defer')
