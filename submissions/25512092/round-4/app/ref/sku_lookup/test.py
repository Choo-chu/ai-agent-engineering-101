def test(f, k):
    assert 'sku_lookup 사용 금지' in f({}, k).get('error')
