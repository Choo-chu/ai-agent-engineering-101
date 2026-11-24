# Round 4 rules (25512092)

## 19:00 개장 체크리스트

순서대로. 자세한 명령은 아래 "## 운영".

1. [ ] **터미널 1 shim** 실행 → `curl.exe -s http://127.0.0.1:8900/health` 가 `{"ok": true, ...}`
2. [ ] **터미널 2 DailyMart** 실행 → `receipt public key ... T9CZzNR9eJPf6ewkQU7LDZtUICMqrTDZHEZb4zy+ZcQ=` (키트보다 먼저)
3. [ ] **터미널 3 키트** 실행: `--name choo-chu`, `--owner`는 클레임 코드를 직접 입력 (파일에 쓰지 않는다)
4. [ ] **터미널 4 콘솔 보기** (`Get-Content -Wait`)
5. [ ] `[maroo]` 줄 주소 확인: shop `0x943805646864aa174e90c330b795019b16E1D262`, buyer `0x632Bf1A13842FedF35A39E0c5324D4eF0bFFa2c0` (11/23 만든 지갑. 다르면 키 파일이 바뀐 것 → 멈추고 확인)
6. [ ] `[tunnel] ...`, `[market] shop joined as choo-chu`, `[kit] the agent is awake`. MeshKit 경고(`did not list its tools`)가 없는지
7. [ ] **shop 지갑 시작금 5,000,000** 들어왔는지 ("## 운영 > 확인할 것" 2번)
8. [ ] 앱 열기 (`[app] open` 링크, PC는 `127.0.0.1:8800`) → "사장님 메모"에 **owner_memo v1.4** 본문 붙여넣고 저장
9. [ ] 인사 (F1): 앱에서 말을 걸고 답이 오는지
10. [ ] 폰 설치 (M3): `https://....trycloudflare.com/?k=...` 링크 → Android Chrome "앱 설치" / iOS Safari 공유 → 홈 화면에 추가. 폰은 주소가 달라 메모가 비어 있으니 필요하면 폰에서도 붙여넣기
11. [ ] DailyMart 우유 주문 (M4): "## 운영 > MeshKit (DailyMart) > 개장 후 테스트"
12. [ ] 사용량 확인 (`five_hour` / `seven_day`)

## 규칙 요약

출처: `weeks/week-12/README.md`, Agent Market `market/ROUND4.md`, `market/ROUND3.md` (Round 4 = Round 3 경제 + 체인 결제/수수료), `market/server.py` 상수, `scripts/round4/agent_kit.py` (2026-11-22 작성, 2026-11-24 kit v5.1 / agent-market 최신으로 갱신).

**손님 (customer)**
- Nemotron-Personas-Korea 기반 한국인 페르소나 LLM (나이, 지역, 직업, 가족, 식습관, 취미). 때때로 방문해서 포럼과 `GET /api/agents`를 읽고, A2A로 직접 말 걸고, 흥정하고, 그 사람이 원할 만한 것을 사거나 안 산다.
- 이전 방문을 기억한다: 마음에 든 가게는 다시 오고, 속인 가게는 포럼에서 소문이 날 수 있다.
- 판매 방법: 샵 지갑으로 서명한 `checkout_jwt`를 주거나 (내용은 clearing 카드에 명시), ACP checkout을 서빙하면 샵 서명 영수증. 손님이 그 SKU/가격으로 자기 일일 크레딧 한도 안에서 주문을 열고 정산한다.
- 손님도 자기 지갑에서 **tOKRW로 온체인 결제**한다 (마을 금고가 지갑을 채움). 수수료도 에이전트 거래와 같다 (`server.py` L106 `PERSONA_ON_CHAIN`=1, L856, L932; `house/customer.py` L415-417). 손님 일일 한도 300,000 크레딧은 그대로. 손님은 샵 순위에 없다.
- 손님은 6개 동네 500가구의 마을. 정해진 주기가 아니라 생활(필요, 행사, 월 예산)이 시켜서 장에 온다. 동시에 약 100명이 마을에 나와 있다 (`GET /api/village`: 요일, 시간대, 날씨, 장날, 월급날, `in_town`).
- `metadata.from`(이름)은 검증되지 않은 주장이다.

**수수료 (거래 1건, 가격 P, m = P x 1%)**
- 양쪽이 각각 m + 210 (네트워크 수수료 420의 절반).
- 샵 잔고 증가: `P - m - 210`. 바이어 점수상 비용: `P + m + 210`.
- 예: P = 10,000 → 샵 +9,690, 바이어 -10,310. 가격이 m + 210보다 낮으면 `price_covers_fees` 실패 → 소액 판매는 손해.
- 손님·에이전트 거래 모두 같은 수수료. 최저가 = `ceil((원가 × 1.1 + 210) / 0.99)`.
- 실제 가스비는 사는 쪽 지갑이 부담. 1,000 크레딧 = 1 tOKRW.
- kit v5.1은 기본이 **shop only** (`--with-buyer`를 줘야 buyer로도 참가). 우리는 buyer를 안 쓰므로 **faucet 불필요**. 재입고·환불은 shop 지갑의 시작금으로 낸다.

**도매 / 재고**
- **지갑이 곧 돈**: 시장은 샵 잔고를 따로 갖지 않는다. 처음 참가하면 시장이 shop 지갑에 5,000,000 크레딧어치 tOKRW를 보낸다 (`START_CAPITAL`). GitHub 계정당 샵 1개.
- 재입고 결제: `POST /api/supply {sku, qty}` → **402 견적** (`total` = 상품 + 밀린 보관비 + 포럼 비추천 비용, `pay {to, wei, data}`, 단위별 등급·유통기한 표시). shop 지갑에서 `kit.pay`로 정확히 그 금액을 보내고 `POST /api/supply {quote, tx_hash}`. 견적은 120초 유효. 도구 `pay_limit`이 견적 총액보다 커야 한다 (기본 200,000).
- `POST /api/supply {sku, qty}`: 1회 최대 20개, 호출 간 10초. 재입고 창은 1,200초 슬롯마다 180초만 열림 (슬롯 시작 후 최대 300초 지터). 라운드 시작 시 600초 창 1회. 창 밖이면 429 + `opens_at`.
- 서지: 시장 전체에서 최근 1시간 동안 SKU당 50개 초과분은 개당 +0.2% 원가, 최대 x1.5 → 인기 SKU 몰빵은 비싸짐.
- 원가: A 55-75%, B 40-60%, C 25-45% (list_price 대비, 구간 겹침).
- 식품: 등급 A25/B50/C25%가 남은 유통기한 결정, 만료되면 자동 폐기 (ledger `expire`).
- 공산품: 등급 A70/B20/C10%, 불량률 3/12/35% (팔고 나서야 드러남). **48시간마다 한 등급씩 하락** (A→B→C), 낮아진 등급의 불량률로 깨진다. 등급을 말할 땐 지금 등급 (`/api/inventory`).
- 보관비: **공산품만, 원가의 0.5%/시간 (하루 12%)**. 다음 재입고 견적에 더해진다 (`server.py` L114, `storage_due` L1186). 식품은 보관비가 없고 만료 시 전손.
- **환불은 가게 송금**: 고장 나면 시장은 ledger에 `broken`만 남기고 아무것도 돌려주지 않는다. 손님이 와서 요구하면 환불은 가게가 `kit.pay`로 직접 보낸다 (`coin()` L258). 손님은 기억하고, 이웃과 이야기하고, 포럼에 쓴다.
- 포럼: 샵의 비추천은 시간당 3개를 넘으면 비용이 붙는다 (다음 견적의 `forum_fees`).
- 파산: 지갑 500,000 미만에서 최대 2회, 재고 몰수 + 시작금까지 모자란 만큼 시장이 송금.
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

**점수 (순위)**
- board는 **순위와 이름만** 공개한다 (`ranked_view` L2174). 순서는 운영자의 scorer 파일(`MARKET_SCORER`, 비공개)이 정한다. scorer가 없을 때의 기본값(`RESERVE` 기준 profit)은 Round 4 상품에선 0이라 의미 없음.
- 힌트: 문서는 "가게 돈 = 지갑 잔고", starter goal은 "end each day with more money in the shop's wallet, and have customers come back". → **지갑 잔고를 목표로** 하고, 종료 직전 재고는 0에 가깝게.
- 돈을 버는 길: 마진 남기고 팔기, 싸게 재입고, 수수료/보관비/폐기/환불 손실 줄이기.

## 메모

- 앱 도구 `app_owner_memo`: 앱 하단 "사장님 메모"에 저장한 텍스트 (브라우저 localStorage). 앱 페이지가 열려 있어야 에이전트가 읽을 수 있다.

## 운영

개장 당일 (2026-11-24 19:00 KST) 실행 절차. PowerShell 기준, 터미널 4개: shim → DailyMart → 키트 → 콘솔 보기 순서로 띄운다.

**콘솔 저장 위치에 주의.** 키트 콘솔에는 `[app] open ...?k=<접근 코드>` 링크가 찍힌다 (키트는 이 코드를 로그 파일에는 안 쓰고 터미널에만 찍는다). 콘솔을 `logs/`에 저장하면 제출물에 섞여 커밋될 수 있으니, gitignore된 `.kit/` 아래에 저장한다. shim 콘솔은 gitignore된 `shim/logs/`.

공통 준비 (각 터미널에서 한 번): 한글 깨짐 방지

```powershell
[Console]::OutputEncoding = [Text.Encoding]::UTF8
$env:PYTHONIOENCODING = "utf-8"; $env:PYTHONUNBUFFERED = "1"
```

### 터미널 1: shim

```powershell
cd C:\Users\108\Desktop\AX\ai-agent-engineering-101\submissions\25512092\round-4
$env:SHIM_MODEL = "sonnet"        # 바꾸려면 Ctrl-C 후 "haiku"로 다시 실행 (키트는 그대로 둬도 됨)
cmd /c "python shim\claude_shim.py 2>&1" | Out-File -Encoding utf8 "shim\logs\shim-console-$(Get-Date -Format MMdd-HHmm).txt"
```

- 요청별 기록은 `shim\logs\shim.log`에 따로 남는다. 시작 확인: 다른 창에서 `curl.exe -s http://127.0.0.1:8900/health` → `{"ok": true, ...}`
- `cmd /c "... 2>&1"`: PowerShell 5.1에서 `2>&1`을 직접 쓰면 stderr 줄마다 NativeCommandError가 붙으므로 cmd에서 합친다.

### 터미널 2: DailyMart (키트보다 먼저)

```powershell
cd C:\Users\108\Desktop\AX\meshkit\meshkit-py
python examples\miniapp_server.py
```

- 시작 출력: `mini-app app.dailymart on 127.0.0.1:8765`, `receipt public key (for the registry manifest): T9CZzNR9eJPf6ewkQU7LDZtUICMqrTDZHEZb4zy+ZcQ=` (meshkit.json의 `receipt_pubkey`와 같아야 함, 11/23 확인).
- 브라우저로 GET 하면 501이 정상 (POST JSON-RPC만 받음). 자세한 내용은 아래 "### MeshKit (DailyMart)".

### 터미널 3: 키트

```powershell
cd C:\Users\108\Desktop\AX\ai-agent-engineering-101
$env:SHIM_KEY = "dummy"           # shim은 Authorization 헤더를 읽지 않는다. 진짜 키를 넣지 말 것
Remove-Item Env:AGENT_LLM_BASE, Env:AGENT_LLM_MODEL, Env:AGENT_LLM_KEY -ErrorAction SilentlyContinue   # 있으면 agent.json llm을 덮어씀
New-Item -ItemType Directory -Force submissions\25512092\round-4\.kit | Out-Null
cmd /c "python scripts\round4\agent_kit.py run --dir submissions\25512092\round-4 --market https://market.ourolabs.ai --name choo-chu --owner <claim code> --tunnel --app 8800 --app-tunnel 2>&1" | Out-File -Encoding utf8 "submissions\25512092\round-4\.kit\console-$(Get-Date -Format MMdd-HHmm).txt"
```

`<claim code>`는 실행할 때 직접 입력한다 (파일에 쓰지 않는다).

### 터미널 4: 콘솔 보기

콘솔이 파일로만 가므로, 네 번째 창에서 따라 읽는다:

```powershell
cd C:\Users\108\Desktop\AX\ai-agent-engineering-101\submissions\25512092\round-4
Get-Content -Wait -Encoding utf8 (Get-ChildItem .kit\console-*.txt | Sort-Object LastWriteTime | Select-Object -Last 1).FullName
```

### 확인할 것

1. **[maroo] 주소**: `[maroo] shop wallet 0x..., buyer wallet 0x...` 가 shop `0x943805646864aa174e90c330b795019b16E1D262`, buyer `0x632Bf1A13842FedF35A39E0c5324D4eF0bFFa2c0` 인지. **faucet은 불필요** (kit v5.1은 shop only, `--with-buyer`를 쓰지 않는다. 재입고·환불은 shop 지갑 시작금으로).
2. **shop 지갑 시작금 5,000,000**: 참가 직후 시장이 보낸다 (한 번에 한 건씩 보내므로 조금 늦을 수 있음). 저장소 루트에서 (읽기만 함):

```powershell
python -c "import sys; sys.path.insert(0, 'scripts/round4'); import maroo; print(maroo.balance('0x943805646864aa174e90c330b795019b16E1D262') // maroo.CREDIT_WEI, 'credits')"
```

3. **[app] open 링크**: `http://127.0.0.1:8800/?k=...` (이 PC), `https://....trycloudflare.com/?k=...` (휴대폰). 링크는 남에게 주지 말 것 (`k=`가 접근 코드). 앱 하단 "사장님 메모"를 열어 둬야 `app_owner_memo`가 동작한다.
4. `[tunnel] ...`, `[market] shop joined as choo-chu`, `[kit] the agent is awake` 가 나오는지.
5. **사용량 (shim.log)**: 매 요청 줄의 `rate_limit`에 5시간/주간 사용률이 있다. 마지막 값 보기:

```powershell
$l = Get-Content shim\logs\shim.log -Encoding utf8 | Select-String 'five_hour' | Select-Object -Last 1
if ($l -match '"five_hour":\{"utilization":([\d.]+).*"seven_day":\{"utilization":([\d.]+)') { "5h=$($Matches[1])  7d=$($Matches[2])" }
(Get-Content shim\logs\shim.log -Encoding utf8 | Select-String ' ok=False').Count   # 실패(거절 포함) 수 (앞 공백: json_ok=False 제외)
(Get-Content shim\logs\shim.log -Encoding utf8 | Select-String 'json_ok=False').Count   # 형식 어긋난 답 (키트가 대개 그래도 파싱함)
```

### 주간 사용량이 빠르게 오르면

- **모델 낮추기**: 터미널 1에서 Ctrl-C → `$env:SHIM_MODEL = "haiku"` → shim 다시 실행. 키트는 재시작 불필요 (shim이 멈춘 동안 키트는 3-8초마다 재시도). agent.json의 `model` 값은 표시용이고 실제 모델은 `SHIM_MODEL`이 정한다.
- **max_steps 줄이기**: `agent.json`의 `max_steps` (기본 40)를 줄인다. 키트는 agent.json을 시작할 때 한 번만 읽으므로 **키트 재시작이 필요**하다 (터미널 3에서 Ctrl-C 후 같은 명령).
- **한도에 걸리면**: `agent.json`의 `llm.base`를 `"market"`으로 바꾸고 키트 재시작 (시장 model desk: 무료, 모델 선택 불가, 클래스 명단에 있고 시장에서 에이전트가 살아 있어야 함. 거절 사유 `not_on_class_list` / `agent_not_alive` / `not_the_kit`는 키트 로그에 찍힌다). 이때 `AGENT_LLM_BASE` 환경 변수가 없어야 한다.
- 참고 (11/22 측정): 호출 약 45번에 5시간 사용률 0.05 → 0.06, 주간 0.04 그대로. 이 세션 같은 Claude Code 사용도 같은 한도를 쓴다. 초과 사용(overage)은 꺼져 있어서 한도에 닿으면 호출이 실패하고 에이전트가 멈춘다.

### MeshKit (DailyMart)

`round-4/meshkit.json`은 강의 데모 값 그대로 (caller `app.hermes-chat`, target `app.dailymart` @ `127.0.0.1:8765`). seed가 들어 있어 gitignore됨 (`git check-ignore -v meshkit.json` → `.gitignore:4`). meshkit 레포는 `C:\Users\108\Desktop\AX\meshkit`에 클론, `meshkit-py`는 `pip install -e .` 완료 (11/23).

**순서: DailyMart(터미널 2)를 키트(터미널 3)보다 먼저 띄운다.** 키트는 시작할 때 한 번만 `tools/list`를 부른다 (`scripts/round4/miniapp.py` `load_meshkit`). DailyMart가 꺼져 있으면 `[kit] MeshKit target http://127.0.0.1:8765 did not list its tools` 가 찍히고 `mesh_` 도구 없이 돈다. 그러면 DailyMart를 띄운 뒤 키트를 재시작한다.

#### 개장 후 테스트

1. 앱(`[app] open` 링크)에서 보낸다: `DailyMart 앱 도구로 우유를 budget_krw 100으로 주문해 줘`
2. 앱에 뜨는 동의 시트에서 **허용(Allow)** 을 누른다 (180초 안에).
3. **성공 기준**: 에이전트 답에 **주문 번호**와 **영수증 번호(receipt id)** 가 둘 다 있다. 키트는 DailyMart가 서명한 영수증이 검증될 때만 결과를 넘기므로, 둘이 나오면 서명 검증까지 통과한 것.

### owner_memo v1 (11/24 개장)

```text
[Phase 1 운영 지시 - 11/24 개장]
- 목표: 이익보다 거래 수와 단골. 같은 손님에게는 같은 가격 원칙.
- 최저가 = 원가 + 수수료(가격의 1% + 210) + 원가의 10%. 이 아래로는 절대 팔지 않는다.
- 흥정: 정가의 90% → 80% → 최저가 순서로 3단계까지만 내려간다.
- 재입고: 수요 상위 카테고리의 중간 가격대 SKU를 여러 종류, 종류당 3~5개씩. 한 SKU에 몰지 않는다.
- 식품은 유통기한 짧은(C등급) 건 사지 않는다. 임박한 재고는 최저가로 먼저 판다.
- 다른 에이전트에게서 사지 않는다.
- 모든 문의와 거래를 기록한다.
```

### owner_memo v1.1 (11/24 개장)

- v1 대비 변경 1: floor 식을 판매가 기준으로 풀이 (수수료 1%가 판매가에 붙으므로 `ceil((원가 × 1.1 + 210) / 0.99)`).
- v1 대비 변경 2: 흥정 단계마다 `max(그 단계 가격, floor)` (원가가 높아 floor가 정가의 80%보다 클 때 floor 밑으로 내려가지 않게).

```text
[Phase 1 운영 지시 - 11/24 개장]
- 목표: 이익보다 거래 수와 단골. 같은 손님에게는 같은 가격 원칙.
- 최저가(floor) = ceil((원가 × 1.1 + 210) / 0.99). 수수료 1%는 판매가 기준이라 이 식으로 푼다. 예: 원가 5,000 → floor 5,768. 이 아래로는 절대 팔지 않는다.
- 흥정: 정가의 90% → 80% → floor 순서로 3단계까지만. 각 단계 가격은 max(그 단계 가격, floor).
- 재입고: 수요 상위 카테고리의 중간 가격대 SKU를 여러 종류, 종류당 3~5개씩. 한 SKU에 몰지 않는다.
- 식품은 유통기한 짧은(C등급) 건 사지 않는다. 임박한 재고는 floor로 먼저 판다.
- 다른 에이전트에게서 사지 않는다.
- 모든 문의와 거래를 기록한다.
```

### owner_memo v1.2 (11/24 개장)

- v1.1 대비 변경 1: 손님/에이전트 최저가 분리. 손님(시장 customer) 거래는 수수료가 없다: `credits_only` 주문은 `on_chain=False`라 샵 잔고에 가격 전액이 들어간다 (agent-market `market/server.py` L817, L895). 손님 최저가는 `ceil(원가 × 1.1)`, 에이전트 최저가는 v1.1 식 그대로.
- v1.1 대비 변경 2: 찾는 상품이 없으면 같은 카테고리 재고 중 가격이 가까운 대체품 제안 (손님은 카탈로그 단어 검색으로 SKU를 정한 뒤 가게에 묻는다, `house/customer.py` `catalog()`/`talk()`).
- v1.1 대비 변경 3: 빠른 응답 (손님 방문은 240초, 동시 3명뿐, `customer.py` L35, L298).
- v1.1 대비 변경 4: 재입고 우선 카테고리를 장류·찌개, 커피/차, 국수, 해조류, 과자로 지정, 신선육은 소량 (`analysis/customers.md` 3장 상위 10, 유통기한).

```text
[Phase 1 운영 지시 - 11/24 개장]
- 목표: 이익보다 거래 수와 단골. 같은 손님에게는 같은 가격 원칙.
- 손님(시장 customer) 최저가 = ceil(원가 × 1.1). 손님 거래는 수수료가 없다.
- 에이전트 최저가 = ceil((원가 × 1.1 + 210) / 0.99). 수수료 1%는 판매가 기준.
- 흥정: 정가의 90% → 80% → 최저가 순서로 3단계까지만. 각 단계 가격은 max(그 단계 가격, 최저가).
- 손님이 찾는 게 없으면 같은 카테고리 재고 중 가격이 가까운 대체품을 바로 제안한다.
- 답은 빠르게. 손님 방문은 짧고 귀하다.
- 재입고: 장류·찌개, 커피/차, 국수, 해조류, 과자 같은 오래 가는 식품을 우선, 중간 가격대 여러 종류를 종류당 3~5개씩. 신선육은 소량만. 한 SKU에 몰지 않는다.
- 식품은 유통기한 짧은(C등급) 건 사지 않는다. 임박한 재고는 최저가로 먼저 판다.
- 다른 에이전트에게서 사지 않는다.
- 모든 문의와 거래를 기록한다.
```

### owner_memo v1.3 (11/24 개장)

- v1.2 대비 변경 1: 최저가 하나로 통일. 손님 거래도 온체인 결제라 수수료(1% + 210)가 붙는다 (agent-market `market/server.py` L106 `PERSONA_ON_CHAIN` 기본 1, L856, L932; `house/customer.py` L415-417). v1.2의 "손님 거래는 수수료가 없다"는 틀렸다.
- v1.2 대비 변경 2: 목표를 "가게 지갑 잔고"로. 순위는 운영자 scorer(비공개)가 정하고, 문서는 가게 돈 = 지갑 잔고라고 한다 (`ROUND4.md` One money, `server.py` `ranked_view` L2174).
- v1.2 대비 변경 3: 공산품 보관비 0.5%/시간(하루 12%, 식품은 없음), 48시간마다 등급 하락 (`server.py` L114, L120, `storage_due` L1186). 지금 등급은 `/api/inventory`.
- v1.2 대비 변경 4: 환불은 시장이 하지 않고 가게가 직접 송금 (`server.py` `coin()` L258). 고장은 ledger `broken`에 주문·손님과 함께 남으므로 확인 후 환불. 비추천 수수료는 시간당 3개 초과부터 (`ROUND4.md`).
- v1.2 대비 변경 5: 환불은 전액(P). 가게가 받은 돈은 P − 1% − 210이라 환불 1건은 그만큼 더 든다. 환불 도구 `pay_limit` 300000.
- 확인한 점: 재입고 견적(402)에 단위별 등급·유통기한이 나오므로 결제 전에 C등급 식품을 거를 수 있다 (`quote_view` L1126).

```text
[Phase 1 운영 지시 - 11/24 개장]
- 목표: 가게 지갑 잔고를 늘린다. 초반엔 이익보다 거래 수와 단골. 같은 손님에게는 같은 가격.
- 최저가 = ceil((원가 × 1.1 + 210) / 0.99). 손님·에이전트 모두 수수료(1% + 210)가 붙는다.
- 흥정: 정가의 90% → 80% → 최저가, 3단계까지만. 각 단계는 max(단계 가격, 최저가).
- 찾는 게 없으면 같은 카테고리 재고 중 가격이 가까운 대체품을 바로 제안한다. 답은 빠르게.
- 재입고: 장류·찌개, 커피/차, 국수, 해조류, 과자 같은 오래 가는 식품 우선, 중간 가격대 여러 종류를 소량씩. 신선육은 아주 소량.
- 공산품은 보관비가 하루 12%이고 48시간마다 등급이 떨어진다. 하루 안에 팔 만큼만 산다.
- 식품 C등급은 사지 않는다. 임박한 재고는 최저가로 먼저 판다.
- 등급을 말할 땐 지금 등급(/api/inventory)으로 말한다.
- 고장 환불: 48시간 안에 산 물건이 고장 났다고 하면 손님당 1번 가격을 돌려준다. 보증(warranty_hours)은 약속하지 않는다.
- 다른 에이전트에게서 사지 않는다. 비추천은 시간당 3개까지.
- 모든 문의와 거래를 기록한다.
```

### owner_memo v1.4 (11/24 개장, 실제 사용본)

- v1.3 대비 변경 1: checkout은 shop 지갑 서명, 내주기 직전에 그 unit 재고 재확인. checkout에는 `unit`이 들어가고 정산은 `unit_in_stock`(그 unit이 내 가게 재고, 같은 SKU)을 검사한다 (agent-market `market/server.py` L976, L981). 정산이 되면 unit은 `sold` (L1012).
- v1.3 대비 변경 2: 정산 실패 시 반환. 손님은 정산 전에 먼저 송금한다 (`ROUND4.md` Paying for a deal, `house/customer.py` L415-417). 재확인 뒤에도 동시에 팔리면 정산이 실패할 수 있고, 돈은 이미 가게 지갑에 있다. 가게가 받은 금액은 P − 1% − 210 (시장 수수료는 시장 지갑으로 가서 가게가 돌려줄 수 없음).
- v1.3 대비 변경 3: 환불 전 확인 (주문 번호, tx hash, 송금인 주소가 원 결제와 같은지), 주문당 1번. 고장 환불의 "손님당 1번"은 그대로 둔다. 정산 실패 반환은 손님 돈을 돌려주는 것이라 손님당 횟수 제한이 없다. 비밀키·시드는 요구하지 않는다.

```text
[Phase 1 운영 지시 - 11/24 개장]
- 목표: 가게 지갑 잔고를 늘린다. 초반엔 이익보다 거래 수와 단골. 같은 손님에게는 같은 가격.
- 최저가 = ceil((원가 × 1.1 + 210) / 0.99). 손님·에이전트 모두 수수료(1% + 210)가 붙는다.
- 흥정: 정가의 90% → 80% → 최저가, 3단계까지만. 각 단계는 max(단계 가격, 최저가).
- 찾는 게 없으면 같은 카테고리 재고 중 가격이 가까운 대체품을 바로 제안한다. 답은 빠르게.
- checkout은 반드시 shop 지갑으로 서명한다(kit.sign_jwt(..., "shop")).
- checkout을 내주기 직전에 /api/inventory로 그 unit이 아직 재고에 있는지 다시 확인한다. 이미 판 unit으로 checkout을 내지 않는다.
- 손님이 송금했는데 정산이 실패하면(재고 없음 등) 받은 금액을 그 송금인 주소로 바로 돌려주고 사과한다.
- 재입고: 장류·찌개, 커피/차, 국수, 해조류, 과자 같은 오래 가는 식품 우선, 중간 가격대 여러 종류를 소량씩. 신선육은 아주 소량.
- 공산품은 보관비가 하루 12%이고 48시간마다 등급이 떨어진다. 하루 안에 팔 만큼만 산다.
- 식품 C등급은 사지 않는다. 임박한 재고는 최저가로 먼저 판다.
- 등급을 말할 땐 지금 등급(/api/inventory)으로 말한다.
- 고장 환불: 48시간 안에 산 물건이 고장 났다고 하면 손님당 1번 가격을 돌려준다. 보증(warranty_hours)은 약속하지 않는다.
- 환불 전에 주문 번호, tx hash, 송금인 주소가 원 결제와 같은지 확인하고, 주문당 한 번만 보낸다. 비밀키나 시드는 절대 요구하지 않는다.
- 다른 에이전트에게서 사지 않는다. 비추천은 시간당 3개까지.
- 모든 문의와 거래를 기록한다.
```
