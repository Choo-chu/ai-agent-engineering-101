import json
import time
import httpx


class Fake:
    def __init__(self, code, body):
        self.status_code = code
        self.body = body
        self.text = json.dumps(body)

    def json(self):
        return self.body


def run(a, k):
    t0 = time.time()
    cap = int(a.get('max_spend') or 200000)
    url = k.market.rstrip('/')
    head = {'authorization': 'Bearer ' + k.token('shop')}
    win = {'open': True, 'closes_at': t0 + 180}
    if not k.testing:
        win = httpx.get(url + '/api/restock', timeout=15).json()
    if not win.get('open'):
        return {'ok': False, 'error': 'window closed', 'window': win}
    last = [0.0]

    def post(body):
        gap = time.time() - last[0]
        if gap < 11 and not k.testing:
            time.sleep(11 - gap)
        last[0] = time.time()
        if k.testing and 'quote' in body:
            return Fake(200, {'ok': True})
        if k.testing:
            pay = {'to': '0x' + '0' * 40, 'wei': '1000', 'data': '0x'}
            return Fake(402, {'quote': 'q-t', 'total': 1000 * body['qty'], 'pay': pay})
        return httpx.post(url + '/api/supply', json=body, headers=head, timeout=30)

    def supply(body):
        r = post(body)
        tries = 0
        while r.status_code == 429 and tries < 2:
            try:
                wait = float(r.json().get('wait') or 0)
            except Exception:
                wait = 0
            time.sleep(wait + 1)
            tries += 1
            r = post(body)
        return r

    out = []
    spent = 0
    for it in a.get('items') or []:
        rec = {'sku': it.get('sku'), 'qty': int(it.get('qty') or 1), 'spent': 0}
        out.append(rec)
        if float(win.get('closes_at') or 0) - time.time() < 30 or time.time() - t0 > 140:
            rec['result'] = 'skipped_time'
            continue
        if spent >= cap:
            rec['result'] = 'skipped_cap'
            continue
        r = supply({'sku': rec['sku'], 'qty': rec['qty']})
        if r.status_code != 402:
            rec['result'] = 'failed_quote'
            rec['body'] = r.text[:150]
            continue
        b = r.json()
        rec['total'] = int(b.get('total') or 0)
        if spent + rec['total'] > cap:
            rec['result'] = 'skipped_cap'
            continue
        pay = b.get('pay') or {}
        rec['tx_hash'] = k.pay(pay['to'], int(pay['wei']), pay.get('data', '0x'), 'shop')
        c = supply({'quote': b.get('quote'), 'tx_hash': rec['tx_hash']})
        rec['result'] = 'failed_confirm'
        if c.status_code in (200, 201):
            rec['result'] = 'bought'
            rec['spent'] = rec['total']
            spent += rec['total']
    if not k.testing:
        with open('restock_log.jsonl', 'a', encoding='utf-8') as f:
            for rec in out:
                f.write(json.dumps(dict(rec, ts=int(time.time())), ensure_ascii=False) + '\n')
    return {'ok': True, 'spent': spent, 'results': out}
