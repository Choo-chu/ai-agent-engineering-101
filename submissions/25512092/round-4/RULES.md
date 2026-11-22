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

## 운영

개장 당일 (2026-11-24 19:00 KST) 실행 절차. PowerShell 기준, 터미널 2개.

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

### 터미널 2: 키트

```powershell
cd C:\Users\108\Desktop\AX\ai-agent-engineering-101
$env:SHIM_KEY = "dummy"           # shim은 Authorization 헤더를 읽지 않는다. 진짜 키를 넣지 말 것
Remove-Item Env:AGENT_LLM_BASE, Env:AGENT_LLM_MODEL, Env:AGENT_LLM_KEY -ErrorAction SilentlyContinue   # 있으면 agent.json llm을 덮어씀
New-Item -ItemType Directory -Force submissions\25512092\round-4\.kit | Out-Null
cmd /c "python scripts\round4\agent_kit.py run --dir submissions\25512092\round-4 --market https://market.ourolabs.ai --name <nickname> --owner <claim code> --tunnel --app 8800 --app-tunnel 2>&1" | Out-File -Encoding utf8 "submissions\25512092\round-4\.kit\console-$(Get-Date -Format MMdd-HHmm).txt"
```

콘솔이 파일로만 가므로, 세 번째 창에서 따라 읽는다:

```powershell
cd C:\Users\108\Desktop\AX\ai-agent-engineering-101\submissions\25512092\round-4
Get-Content -Wait -Encoding utf8 (Get-ChildItem .kit\console-*.txt | Sort-Object LastWriteTime | Select-Object -Last 1).FullName
```

### 확인할 것

1. **buyer 지갑 → faucet**: `[maroo] shop wallet 0x..., buyer wallet 0x...` 줄의 **buyer** 주소를 https://faucet.maroo.io 에서 수동 청구 (캡차, 5,000/회, 10,000까지). 에이전트 간 거래 결제에 쓰인다.
2. **[app] open 링크**: `http://127.0.0.1:8800/?k=...` (이 PC), `https://....trycloudflare.com/?k=...` (휴대폰). 링크는 남에게 주지 말 것 (`k=`가 접근 코드). 앱 하단 "사장님 메모"를 열어 둬야 `app_owner_memo`가 동작한다.
3. `[tunnel] ...`, `[market] shop joined as <nickname>`, `[kit] the agent is awake` 가 나오는지.
4. **사용량 (shim.log)**: 매 요청 줄의 `rate_limit`에 5시간/주간 사용률이 있다. 마지막 값 보기:

```powershell
$l = Get-Content shim\logs\shim.log -Encoding utf8 | Select-String 'five_hour' | Select-Object -Last 1
if ($l -match '"five_hour":\{"utilization":([\d.]+).*"seven_day":\{"utilization":([\d.]+)') { "5h=$($Matches[1])  7d=$($Matches[2])" }
(Get-Content shim\logs\shim.log -Encoding utf8 | Select-String ' ok=False').Count   # 실패(거절 포함) 수 (앞 공백: json_ok=False 제외)
(Get-Content shim\logs\shim.log -Encoding utf8 | Select-String 'json_ok=False').Count   # 형식 어긋난 답 (키트가 대개 그래도 파싱함)
```

### 주간 사용량이 빠르게 오르면

- **모델 낮추기**: 터미널 1에서 Ctrl-C → `$env:SHIM_MODEL = "haiku"` → shim 다시 실행. 키트는 재시작 불필요 (shim이 멈춘 동안 키트는 3-8초마다 재시도). agent.json의 `model` 값은 표시용이고 실제 모델은 `SHIM_MODEL`이 정한다.
- **max_steps 줄이기**: `agent.json`의 `max_steps` (기본 40)를 줄인다. 키트는 agent.json을 시작할 때 한 번만 읽으므로 **키트 재시작이 필요**하다 (터미널 2에서 Ctrl-C 후 같은 명령).
- 참고 (11/22 측정): 호출 약 45번에 5시간 사용률 0.05 → 0.06, 주간 0.04 그대로. 이 세션 같은 Claude Code 사용도 같은 한도를 쓴다. 초과 사용(overage)은 꺼져 있어서 한도에 닿으면 호출이 실패하고 에이전트가 멈춘다.
