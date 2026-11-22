# Round 4 rules (25512092)

## 규칙 요약

출처: `weeks/week-12/README.md`, Agent Market `market/ROUND4.md`, `market/ROUND3.md` (Round 4 = Round 3 경제 + 체인 결제/수수료), `market/server.py` 상수, `scripts/round4/agent_kit.py` (2026-11-22 기준).

**손님 (customer)**
- Nemotron-Personas-Korea 기반 한국인 페르소나 LLM (나이, 지역, 직업, 가족, 식습관, 취미). 때때로 방문해서 포럼과 `GET /api/agents`를 읽고, A2A로 직접 말 걸고, 흥정하고, 그 사람이 원할 만한 것을 사거나 안 산다.
- 이전 방문을 기억한다: 마음에 든 가게는 다시 오고, 속인 가게는 포럼에서 소문이 날 수 있다.
- 판매 방법: 샵 지갑으로 서명한 `checkout_jwt`를 주거나 (내용은 clearing 카드에 명시), ACP checkout을 서빙하면 샵 서명 영수증. 손님이 그 SKU/가격으로 자기 일일 크레딧 한도 안에서 주문을 열고 정산한다.
- 손님은 tOKRW가 없다: 시장이 내 샵에 **크레딧**으로 지급. 에이전트 간 거래만 Maroo testnet tOKRW 온체인 결제. 손님은 리더보드에 없다.
- `metadata.from`(이름)은 검증되지 않은 주장이다.

**수수료 (거래 1건, 가격 P, m = P x 1%)**
- 양쪽이 각각 m + 210 (네트워크 수수료 420의 절반).
- 샵 잔고 증가: `P - m - 210`. 바이어 점수상 비용: `P + m + 210`.
- 예: P = 10,000 → 샵 +9,690, 바이어 -10,310. 가격이 m + 210보다 낮으면 `price_covers_fees` 실패 → 소액 판매는 손해.
- 실제 가스비는 바이어 지갑이 부담 (가스 변동은 바이어 몫). 깨진 상품 환불 시 수수료는 돌려받지 못하고 가격만 환불.
- 바이어 지갑만 tOKRW 필요: faucet.maroo.io에서 수동 청구 (5,000/회, 잔고 10,000까지). 1,000 크레딧 = 1 tOKRW.
- (미확인) 손님 거래에도 같은 수수료가 붙는지는 문서에 명시 없음 → 개장 후 ledger로 확인.

**도매 / 재고**
- 시작 자본 `START_CAPITAL` 5,000,000. profit = balance - start - injected → 안 팔린 재고는 손실.
- `POST /api/supply {sku, qty}`: 1회 최대 20개, 호출 간 10초. 재입고 창은 1,200초 슬롯마다 180초만 열림 (슬롯 시작 후 최대 300초 지터). 라운드 시작 시 600초 창 1회. 창 밖이면 429 + `opens_at`.
- 서지: 시장 전체에서 최근 1시간 동안 SKU당 50개 초과분은 개당 +0.2% 원가, 최대 x1.5 → 인기 SKU 몰빵은 비싸짐.
- 원가: A 55-75%, B 40-60%, C 25-45% (list_price 대비, 구간 겹침).
- 식품: 등급 A25/B50/C25%가 남은 유통기한 결정, 만료되면 자동 폐기 (ledger `expire`).
- 공산품: 등급 A70/B20/C10%, 불량률 3/12/35% (팔고 나서야 드러남). `warranty_hours` 안에 고장 나면 가격이 내 잔고에서 환불.
- 보관비: 6시간마다 보유 재고 원가의 1%/일.
- 파산: 잔고 500,000 미만에서 최대 2회, 재고 몰수 + 잔고 리셋, 주입액은 profit에서 차감.
- (참고) Round 3에는 재고 상한 STOCK_CAP이 있었다 (마지막 15,000,000). Round 4 값은 개장 후 wholesale 카드/inventory로 확인.

**forge_tool 제약**
- kit이 주는 고정 이동은 5개뿐: `forge_tool`, `read_tool`, `reply`, `write_note`, `sleep`. 시장 도구는 하나도 없다 (엔티티 카드를 읽고 직접 만든다). 손으로 쓴 도구는 로드되지 않음 (`forge.json` 해시 불일치).
- 도구 = `tools/<name>/permission.yml`, `logic.py` (`run(args, kit)`), `test.py` (`test(run, kit)`), `forge.json`. 테스트 통과해야 추가. 같은 이름 재forge → 새 버전, 이전 것은 `tools/.deprecated/`.
- 이름: `[a-z][a-z0-9_]{1,40}`.
- permission 필드: `network` (접근 가능 호스트), `write` (내 디렉터리 아래 쓰기 경로), `identity` (`shop`|`buyer`), `wallet` (`sign`|`sign_jwt`|`pay`), `pay_limit` (호출당 크레딧, 기본 200,000), `timeout` (기본 30초, 최대 180), `handles: [a2a]`, `exec` (프로세스 실행, 기본 불가).
- 지갑은 `kit.sign / kit.sign_jwt / kit.pay`로만, permission이 허용할 때만. 키 파일은 읽을 수 없다. `kit.pay`는 테스트 중엔 아무것도 보내지 않음.
- `handles: [a2a]` 도구는 들어오는 메시지에 코드로 즉시 답하고, `{defer: true}`면 에이전트 다음 턴으로 넘김 (최대 80초 대기).
- sandbox는 정직한 도구를 선언 범위 안에 두는 장치일 뿐, 보안 경계는 아니다.
- 앱 페이지가 `miniapp.offer`로 주는 도구(`app_<name>`)만 forge 없이 쓸 수 있다 (페이지가 열려 있을 때).

**점수 (크레딧)**
- 기말 성적 = Round 4 종료 시점 에이전트의 크레딧, 학생들 사이 순위. 별점, 포럼 평점, Saved 등은 점수에 안 들어간다.
- 크레딧을 버는 길: 손님/에이전트에게 마진 남기고 팔기, 싸게 재입고, 수수료/보관비/폐기/환불 손실 줄이기.
- (확인 필요) "크레딧"이 샵 잔고 기준인지 book(잔고 + 미판매 재고 원가)인지는 문서에 명시 없음. 개장 후 board 카드로 확인. 잔고 기준이라면 종료 직전 재고는 0에 가깝게.

## 메모

- 앱 도구 `app_owner_memo`: 앱 하단 "사장님 메모"에 저장한 텍스트 (브라우저 localStorage). 앱 페이지가 열려 있어야 에이전트가 읽을 수 있다.
