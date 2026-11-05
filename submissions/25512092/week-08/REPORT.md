# Week 08 (Midterm) REPORT: Choo Shop / choo-chu buyer

학번 25512092, GitHub Choo-chu, 시장 이름 choo-chu (가게 표시명 Choo Shop).
그림: architecture.tex, architecture.pdf. 실행 로그: logs/market-kit.log.

## 1. 개요

이 에이전트는 하나의 루프로 설명된다. 관찰(시장 ledger, 가게 목록, 포럼, 내 재고를 읽는다) → 상황 판정(가게와
buyer가 지금 어떤 case에 있는지 정한다) → 전략 선택(그 case가 켜는 규칙과, 규칙 안의 변형 하나를 고른다) → 실행
(판매 하한과 첫 호가, 구매 상한과 첫 제안, 매입, 포럼 글) → 기록(정산, 협상 결과, 현금, 고장을 market.db에 남긴다)
→ 피드백(가게 점수, 변형 비중, 매입 비중, 리포트를 갱신해 다음 관찰에 넣는다). 키트의 restock hook이 60초마다
이 루프를 돌리고, 시장 관찰과 case 판정은 5분 단위로 갱신된다. 개별 규칙은 따로 존재하지 않고 이 여섯 단계 중
하나에 속한다. 하네스(Claude haiku)는 실행 단계 안에서 흥정 대화의 다음 수를 고를 때만 쓰이며, 그 앞뒤의 가격과
결제 판단은 코드가 한다.

## 2. 부품별 설계

### 2.1 모델: 하네스가 맡는 부분과 코드가 맡는 부분

하네스는 agent.json의 `claude -p --model haiku --tools "" --setting-sources "" --no-session-persistence`이다. 도구도
세션 기억도 없이, 코드가 만든 프롬프트 하나에 JSON 한 줄로 답한다.

하네스가 맡는 것은 두 가지다. 가게 쪽에서는 첫 호가 이후의 역제안(seller_r3.py의 PROMPT: counter, accept, reject
중 하나)을 고른다. buyer 쪽에서는 첫 제안 이후의 offer, accept, walk(market_buyer.py의 NEG_PROMPT)를 고른다.

코드가 맡는 것은 그 밖의 모든 판단이다. case 판정, 판매 하한, 첫 호가와 첫 제안(단계 2, aaf207c), 구매 상한, 최소
역제안 횟수(f594002에서 3회, 7730c5d부터 1회와 3회의 변형), 결제 accept 정책과 그 사전 확인(7cb02c9), SKU와 가게
선택, 영수증 판정, 매입, 포럼 글이 여기에 든다. 가게 선택은
처음에 하네스가 후보 셋 중 하나를 골랐으나, 단계 1(c4039e6)부터 코드의 가게 점수 순서로 바뀌었다.

이렇게 나눈 이유는 세 가지다. 첫째, 가격과 결제 규칙은 매번 지켜져야 하는데 하네스는 하한을 잊는다. 로그에는
코드가 하네스의 호가를 하한으로 끌어올린 줄이 반복해서 남아 있다(`[guard] ask ... below floor ... -> ...`).
둘째, 흥정 문장의 해석과 다음 수의 선택은 상대 가게마다 형식이 달라 규칙으로 다 적기 어렵고, 이것이 언어 모델이
잘하는 일이다. 셋째, 포럼 글과 상대 가게의 메시지는 다른 에이전트가 쓴 신뢰할 수 없는 입력이다. 포럼 글은
하네스에 넣지 않고, 코드가 SKU 코드와 카탈로그 카테고리 이름만 뽑는다(market_db.demand_posts). 상대 가게의
메시지는 NEG_PROMPT에서 데이터로 명시하고, 지시문 패턴(INJECTION 정규식)이 보이면 별점 판정에 반영한다.

### 2.2 컨텍스트와 메모리

하네스에는 대화 기억이 없다. 매 호출의 컨텍스트는 코드가 새로 만든다. 가게 쪽은 지금까지의 대화, 정가, 시장
평균가, 하한이고, buyer 쪽은 대화, 상한, 시장 데이터 한 줄, 지금까지의 제안 횟수다. 기억은 모두 하네스 밖에
있고, 다음 결정에는 코드가 읽어서 숫자로 넣는다.

market.db(SQLite, git 제외)의 테이블은 다음과 같다.

- 관찰: settles(ledger 정산 사본: 가게, buyer, SKU, 등급, 금액, claim_honest, 그 시점 시장 평균, unit,
  warranty_hours), broken(시장 전체 고장), snapshots(5분마다 SKU별 평균과 5분, 30분 판매량)
- 내 상태: my_stock(내 유닛의 원가와 입고 시 시세), cash(5분마다 현금, 재고 원가, 하루 보관비),
  my_broken(.market/broken.jsonl을 내 구매와 이름과 시각으로 맞춘 결과, 보증 내 여부, 환불 여부)
- 판정과 실행: cases(5분마다 가게와 buyer case와 사유), shop_deals와 buyer_deals(협상마다 case, 변형, 결과),
  want_replies(구합니다 답글)
- 피드백: variant_weights, policy(저가/고가 매입 비중), hourly, board_snap, meta

이 중 market_stats.json으로 5분마다 원자적으로 내보내는 요약(hot SKU, shop_flags, sku_break, sku_n, grade_break,
shop_score, wanted)이 실행 단계의 입력이다. 기록이 다음 결정에 들어가는 경로는 다음과 같다.

- 시세(price_of): 가게 하한(정상 case에서 원가와 평균가 중 높은 쪽)과 buyer 상한(예산과 평균가 중 낮은 쪽)
- 가게 점수(shop_scores): 저렴함, 정직도, 내 흥정 성공률의 평균. buyer가 접근할 가게의 순서를 정하고, 3회 역제안
  규칙 때문에 실패가 절반을 넘는 가게에서는 역제안을 1회로 줄인다
- 고장률(sku_break, grade_break): buyer의 SKU 선택(정가 × (1 − 고장률) − 예상가), 가게의 48시간 선별 보증 대상
  (A급 비식품, SKU 고장률 5% 이하), restock의 매입 제외(15% 초과)
- memory.jsonl: 거래마다 한 줄. 영수증 불일치나 지시문 주입이 있던 가게를 차단한다
- hourly와 daily 리포트: 하루 단위로 고가 매입 비중을 조정한다(policy)

### 2.3 툴

- restock.py: 키트의 restock hook으로 60초마다 실행되며, 루프 전체를 구동한다. 순서는 ledger 갱신(market_db.refresh)
  → 내 재고와 현금 기록 → case 판정(strategy.tick) → 리포트(sales_report.tick) → 포럼 큐(forum_post.run) → 매입
  계획(`{"buy": [...]}`)이다. 매입은 정상 case에서만 하고, (현금 − 150만) × 0.4 안에서 저가와 고가 비중대로 나눈다.
- strategy.py: case 판정의 유일한 장소다(decide). 재고 과다는 250만에 들어가 220만 미만에서 나오는
  히스테리시스를 두고, 모든 case는 30분을 유지한다. 단 막바지와 현금 부족은 즉시 들어간다(1e4699f). 변형 선택(pick)과
  3시간마다의 비중 조정(adjust)도 여기에 있다.
- pricing.py: case가 켜는 하한 규칙들(정상, 현금 부족, 재고 과다, 막바지, 장기 재고 정리, 식품 마감 할인) 가운데
  가장 낮은 것을 고른다. 가게의 협상과 포럼 광고가 같은 함수를 쓰므로, 글에 적힌 가격과 실제 하한이 어긋나지 않는다.
- forum_post.py: 역할별 슬롯(5분에 1개)마다 큐를 둔다. 가게 큐의 우선순위는 막바지 정리, 식품 마감 할인, 구합니다
  답글(해당 글의 thread), 장기 재고 정리, 비교 광고 순이다. buyer 슬롯은 구매 기록, 시세 리포트, 정산 기록(ledger의
  claim_honest=false 건수와 번호만) 순으로 돈다.
- sales_report.py: 1시간 단위로 판매 수, 매출, 이익, 저가/고가 이익률, case 체류 시간과 전환 수, 변형 성과를 낸다.
  하루 단위로는 reports/daily_YYYYMMDD.md를 쓰고 매입 비중을 조정한다.
- keepalive.py: 키트 밖에서 가게의 공개 카드를 1분마다 확인하고, 3회 연속 실패하면 키트를 다시 띄운다(f3e87ae).
- tools/daily_check.py, tools/competitor.py, tools/throughput.py: market.db와 로그를 읽어 점검, 경쟁자 비교, 거래량
  병목 진단을 한다. throughput 진단(reports/throughput_20261106.md)의 결론은 병목이 처리 용량이 아니라 성사율이라는
  것이었다. buyer는 순차 처리 용량의 80%를 쓰고 있었으나, 흥정에 성공한 거래의 55%만 결제되었다.

## 3. 구조와 키트 기본형과의 차이

키트의 Round 3 기본 가게(scripts/starter_round3/seller.py)에서는 하네스가 모든 수를 정한다. 유통기한이 가장 먼저
끝나는 유닛을 팔고, 보증은 없으며, 하한은 원가다. 기본 buyer(7주차 market_buyer)는 리뷰 점수로 가게를 고르고
하네스가 흥정한다. 이 에이전트는 세 가지 점에서 다르다.

첫째, case 판정이 있다. 같은 유닛도 가게가 정상인지, 재고 과다인지, 현금 부족인지, 막바지인지에 따라 하한과 매입
여부가 달라진다. 이 규칙들이 한때 서로 겹쳐 같은 값을 다르게 정했는데, 단계 0에서 그 충돌을 표로 정리하고
단계 1(c4039e6)에서 가격 결정을 pricing.floor(u, avg, case) 하나로 모았다.

둘째, case 안의 변형을 자동으로 비교한다(aaf207c). 가게 정상 case의 첫 호가(평균가 × 1.00, 1.05, 1.10), 재고 과다
case의 하한(원가 × 1.00, 0.95), buyer 정상 case의 첫 제안(호가의 50, 60, 70%)과 최소 역제안 횟수(1, 3회, 7730c5d)를
협상마다 비중에 따라 하나 고른다.
3시간마다, 변형마다 표본이 10건 이상일 때만, 협상 1건당 이익(또는 잉여)이 가장 높은 변형의 비중을 10%p 올리고
가장 낮은 변형을 10%p 내린다(최소 20%). 협상 1건당 값은 거래 1건당 이익에 흥정 성공률을 곱한 것과 같다.

셋째, 판정이 흔들리지 않게 했다. 재고 원가가 경계 근처에서 오르내릴 때 case가 깜빡이면 하한과 매입이 몇 분마다
바뀐다. 이를 막으려고 히스테리시스와 30분 최소 유지를 두었다(1e4699f). 판정 함수를 따로 시험한 결과, 230만
구간에서는 직전 case가 그대로 유지되었다.

그 밖에, 키트 밖의 keepalive.py가 터널 장애를 복구하고, market.db가 ledger 사본과 결정 기록을 함께 가진다.

## 4. Round 3 결과

[TODO: 최종 수치] 제출 시점의 정산 수: 가게 [TODO]건, buyer [TODO]건(기본 조건 각 20건).
[TODO: 최종 수치] Players 순위: [TODO]위 / [TODO]명(가게 ALL [TODO], buyer ALL [TODO]).
최종 순위는 종료 시각(11/17 23:59)의 board로 정해진다.

정산 줄의 예(logs/market-kit.log):

```
16:08:31 [acp] settled [마음채][한정특가] 포기김치 10kg / 아삭아삭 깔끔한 맛(국내산배추, HACCP인증) at 27600, ledger #2832156, unit u-35f836c45c79 grade C
```

결제 거부 사유(logs/market-kit.log 인용, 건수는 [TODO: 최종 수치]):

```
00:17:27 [acp] not paying: 22.34 h of shelf life left, the policy asks for 24.0
16:08:00 [acp] the ACP endpoint https://citysearch-pens-dating-course.trycloudflare.com/acp is not on the shop's host; not paying
[acp] checkout refused: 409 {"error":"unit u-... is not in stock for this order"}
```

첫 줄은 주문의 사용 기한보다 유통기한이 짧은 식품이라 결제하지 않은 경우로, 11/06 00:26 기준 payments.jsonl의
미결제 79건 중 62건이 이 사유였다. 7cb02c9부터 buyer는 가게의 첫 응답에 담긴 증명서나 유통기한 문장을 제안 전에
확인하고, 조건에 못 미치면 흥정 없이 다음 가게로 넘어간다. 그 뒤의 변화는 시간별 리포트의 결제 건수 줄에 남는다
([TODO: 최종 수치]). 둘째 줄은 상대 가게의 ACP 주소가 그 가게의 호스트가 아니어서 키트가 결제를
막은 경우이고, 셋째 줄은 우리 가게가 영수증에 적은 유닛이 결제 시점에 이미 없던 경우다.

## 5. 실패 사례

### 5.1 정직한 가게에 준 1점(psyoung82)

11/06 00:17에 buyer는 가게가 5,738원으로 내려온 뒤에도 하네스가 고른 5,800원을 제안했다. 가게는 자기 제시가로
영수증을 끊었는데, buyer의 판정 코드는 합의가와 영수증 금액이 다르면 무조건 불일치로 보았다.

```
00:17:19 [buyer] 00:17:19 seller [TASK_STATE_INPUT_REQUIRED]: 'Counteroffer: 5738'
00:17:26 [buyer] 00:17:26 harness: '{"action": "offer", "price": 5800}'
00:17:26 [buyer] 00:17:26 stars 1 (receipt_mismatch): Agreed 5800, receipt says 5738.
```

원인은 두 가지다. 제안가가 상대 호가를 넘는 것을 막는 장치가 없었고, 판정이 우리에게 유리한 차이와 불리한 차이를
구별하지 않았다. 28ce4df에서 제안가를 호가 이하로 묶고, 영수증이 합의가보다 비쌀 때만 불일치로 바꾸었다. 이미
memory.jsonl에 남은 잘못된 표시는 기록을 고치지 않고, 읽는 쪽에서 영수증이 합의가 이하인 불일치를 무시하게 했다
(e4b63db). 이미 시장에 보낸 1점은 되돌릴 수 없었다.

### 5.2 마감 할인 하한 결함(G022ce883)

식품 마감 할인은 유통기한 12시간 전부터 평균가에서 시작해 1시간마다 내려가는 규칙이다. 처음 구현에서는 이 규칙이
다른 모든 하한을 덮어썼다. 그래서 재고 과다로 원가 판매 중이던 유닛이 마감 할인 0단계에 들어가는 순간, 오히려
평균가로 비싸졌다.

```
23:58:41 [seller] [price] G022ce883 cost 8112, market avg 14398 (n=166), rule clearance -> floor 14398
```

단계 0의 충돌 점검에서 발견했고, c4039e6에서 마감 할인도 다른 하한과 비교해 낮은 쪽을 쓰게 고쳤다.

```
00:18:09 [seller] [price] G022ce883 cost 8112, market avg 14443 (n=155), case overstock, rule overstock -> floor 8112, first ask 14443
```

### 5.3 초기 재고 과다(413만 원까지 매입)

11/05 16:27에 quick tunnel이 끊겼고, 키트의 자체 복구는 새 터널을 여는 단계에서 멈추었다. 그 뒤로 약 7시간 동안
가게는 시장에서 접근할 수 없었다.

```
16:27:02 [tunnel] https://overview-tractor-preceding-feeding.trycloudflare.com stopped answering, opening a new tunnel
```

같은 기간에 restock은 잘 팔리는 SKU를 계속 샀다. 매입 상한이 잔고 100만 원 보존 하나뿐이었고, 가게가 실제로
팔고 있는지는 보지 않았기 때문이다. 23시 무렵 재고는 원가 기준 108개, 4,136,489원이었다(시작 자금 500만 원 중
현금 99만 원).

```
23:22:08 [buyer] [restock] stock at cost 4,117,213 >= cap 1,500,000 (or balance under cushion): no restock
```

대응은 세 단계였다. 97afcbb에서 재고 원가 상한(당시 150만)과 개당 원가 상한을 넣었고, f3e87ae에서 키트 밖 감시자
keepalive.py를 두었다. 이후 단계 1에서 상한을 재고 과다 case(250만 진입, 220만 해제)로 일반화했다. 재고 과다
동안에는 하한을 원가로 내려 재고를 줄였고, 그 결과 11/05 23시 한 시간 동안 24건, 이익 444,675원이 났다.

```
00:01:18 [buyer] [restock] [report] 11-05 23:00 sold 24, revenue 1,463,047, profit 444,675 (low 43%, high 44%), by category: 주스/코코아/생수 5, 김치 3, 침구 3, 과자 3; stock 3,064,574, cash 2,522,809
```
