import json
def test(f, k):
    u = dict(unit='h3', sku='H', name='사과', grade='B', cost=900, list_price=3000)
    v = dict(u, unit='h4', sku='K', name='총각김치')
    w = dict(u, unit='h6', sku='S', name='국내산 시금치 소비기한 3일', grade='C', cost=500)
    e = [dict(u, unit='h8', sku='E', name='잘구워진 구운계란'), dict(u, unit='h9', sku='F', name='무항생제 유정란'), dict(u, unit='h1', sku='B', name='국내산 부추 1kg/ 아삭한')]
    a = dict(claimed_from='E', _voc='삼겹살 앞다리살 찌개 반찬', _inventory=[u, v, dict(v, unit='h5', sku='J', name='배추김치'), w, dict(w, unit='h7', grade='A')] + e)
    assert f(dict(a, text='소비기한 알려주세요'), k).get('defer')
    r = f(dict(a, text='사과 있어요?'), k)
    assert r['reply'].startswith('사과 ')
    assert json.loads(open('test_ledger.jsonl').read().splitlines()[-1])['jwt'] == r['data']['checkout_jwt']
    assert f(dict(a, text='사과 주세요. 확인 전에는 결제하지 않겠습니다'), k)['data'] == r['data']
    assert f(dict(a, text='이건 안 살게요'), k).get('defer')
    st = json.load(open('test_state.json', encoding='utf-8'))
    assert 'E' not in [x.get('ck') for x in st['reserved'].values()]
    assert 'A등급' in f(dict(a, text='A등급 시금치'), k)['reply']
    assert f(dict(a, text='사과 A등급 있어요?'), k).get('defer')
    assert '배추김치' in f(dict(a, text='김치 주세요? 총각김치 말고'), k)['reply']
    for s in ['우유 있어요?', '구워 먹을 삼겹살', '무항생제 앞다리살']:
        assert f(dict(a, text=s), k).get('defer')
    assert '부추' in f(dict(a, text='찌개와 반찬에 쓸 부추 1kg'), k)['reply']
