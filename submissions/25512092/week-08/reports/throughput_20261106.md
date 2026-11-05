# Throughput diagnosis 2026-11-06 00:35

Source: logs/market-kit.log (11-05 15:00 to 11-06 00:00), market.db. Averages over 8 full hours (shop: only hours it was reachable).

## Per hour

| hour | shop requests | shop settled | buyer orders | negotiations | deals | paid |
|---|---|---|---|---|---|---|
| 11-05 15:00 | 0 | 0 | 12 | 12 | 2 | 2 |
| 11-05 16:00 | 34 | 5 | 82 | 40 | 12 | 8 |
| 11-05 17:00 | 0 | 0 | 66 | 44 | 16 | 9 |
| 11-05 18:00 | 0 | 0 | 43 | 40 | 18 | 8 |
| 11-05 19:00 | 0 | 0 | 70 | 67 | 32 | 14 |
| 11-05 20:00 | 0 | 0 | 63 | 56 | 25 | 13 |
| 11-05 21:00 | 0 | 0 | 70 | 63 | 25 | 17 |
| 11-05 22:00 | 0 | 0 | 51 | 49 | 14 | 10 |
| 11-05 23:00 | 165 | 24 | 87 | 79 | 19 | 9 |
| 11-06 00:00 | 147 | 29 | 66 | 63 | 28 | 19 |

Average per full hour: shop requests 99.5, settled 14.5; buyer orders 66.5, negotiations 54.8, deals 20.1, paid 11.0.

## Shop: how negotiations ended (shop_deals, since 11/06 00:16)

- cancelled: 42
- open (buyer left without a word): 18
- receipt: 18
- receipt, not paid: 17

## Buyer: how negotiations ended (buyer_deals, since 11/06 00:14)

- deal: ok: 20
- fail: seller_ended: 19
- fail: walk: 2
- deal: receipt_mismatch: 1

## Buyer: time

- time per order (order line to result line): mean 44 s, median 23 s, n 544
- harness wait per call: mean 9.8 s, median 6.0 s, n 1700; about 30 s per order
- orders handled at once: 1 (market_kit.py takes the next order only after handle_order returns; the kit is outside submissions/ and is not changed)

## Conclusion

Bottleneck: conversion, not capacity. The buyer uses 80% of its one-at-a-time capacity (66 of about 83 orders/h) but only 55% of its deals get paid; the shop settles 15% of the 100 requests/h it gets while online.
