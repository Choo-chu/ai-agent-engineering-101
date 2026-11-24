def test(run, kit):
    inv = [dict(sku='G1', cost=1000)]
    a = dict(customer_key='A', sku='G1', _inventory=inv)
    assert run(dict(a, price=1000), kit)['floor'] == 1324
    assert run(dict(a, price=3000), kit)['ok']
