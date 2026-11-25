def test(f, k):
    assert 'checkout 사용 금지' in f({}, k).get('error')
