# 이슈 492 구현 점검 기록

목표는 가격 변동일과 그 날짜의 공시·코스피를 정확히 연결하고, 없는 자료와 조회 실패를 구분하는 것이다. 뉴스의 실제 제공, 운영 보존 설정 전환, 대량 백필은 확인 조건이 충족되기 전까지 실행하지 않는다.

## PR 분리와 최신 main 반영

2026-11-26 PR 준비에서 최신 main `25a484b`의 백테스트 실험실 변경을 충돌 없이 rebase했다. 저장소의 블록별 PR 규칙에 따라 차트·공시 수집·화면을 순서대로 나눈다. 차트 PR은 선택형 서빙 계약과 프론트 소비 타입·검증을 함께 맞춘다. 후속 PR은 선행 브랜치를 base로 사용하며 선행 PR 머지 후 main으로 변경한다.

| 검증한 브랜치 | 기준과 결과 |
|---|---|
| `feat/issue-492-chart-basis`의 `e2dd9a4` | 최신 main 위 차트 변경. chart 전체 504 passed, 기존 3 skipped와 Ruff 통과. 프론트 단위 191 passed와 기본 Turbopack production build 통과 |
| `feat/issue-492-disclosure-collection`의 `b571cbc` | 차트 브랜치 위 공시 변경. text 전체 275 passed, 기존 경고 2개와 Ruff 통과 |
| `feat/issue-492-price-context`의 `76d67a0` | 전체 기능. 프론트 단위 203 passed와 기본 production build 재확인. [오류 처리 최종 Chromium 35개 검증](issue-492-error-states.md#검증-결과) 때와 프론트 소스 바이트가 같다 |

위 검증 명령은 아래 기존 기록과 같고 실행 로그는 검증 폴더의 `issue492-pr-{chart,text,web}-*.log`다. chart 전체 495개라는 이전 기록은 최신 main의 실험실 테스트 추가 전 결과다. rebase로 원래 차트 `ab0c166`은 `e2dd9a4`, 공시 `e12545e`는 `b571cbc`, 오류 처리 `4adb482`는 `03367c5`가 됐다. 아래 이전 검증 시점과 명령은 당시 기록으로 유지한다.

PR 게시 중 main에 #502의 백테스트 화면 `97ec720`이 추가되어 차트 `a20c9df`, 공시 `95f6fa0`, 화면 `6ec33e6` 순서로 통합했다. 차트·공시 변경 내용은 유지됐고 화면의 `copy-rules.test.ts`는 두 기능의 검사를 모두 보존했다. 차트 단독 웹 단위 191개와 기본 build를 재확인했다. 최종 통합 화면에서는 단위 203개·변경 파일 ESLint·기본 production build 25개 정적 페이지·Chromium 35개를 다시 통과했다. E2E 재시도는 0회다. 로그는 `issue492-pr-{chart,web}-main502-*.log`에 보관했다. build에는 main #502 백테스트 API의 동적 파일 추적 경고 2개가 남아 있다. 이슈492가 그 파일을 수정하거나 경고를 숨기지는 않는다.

## 작업 기준

- 구현 시작점은 `origin/main`의 `551a7be2860fef2856cf36c5007cd273faba268f`다.
- 작업 브랜치는 `feat/issue-492-price-context`다. 기존 체크아웃의 사용자 변경과 별도 관리한다.
- [구현 계획](issue-492-implementation-plan.md)과 [이슈492의 결정 근거](https://github.com/2026Graduation-Work/take_a_look/issues/492#결정-근거와-수치-기준-2026-11-25)를 따른다.

## 공개 DB 읽기 점검

2026-11-25에 운영 앱이 공개한 익명 읽기 설정으로 GET 요청만 실행했다. 계정·보유 표, 기사 본문은 조회하지 않았고 공급자 API 호출이나 DB 쓰기는 하지 않았다. 인증값은 기록에 포함하지 않는다.

대상4종목의 최신 공개가격과 기존 변동성 기준일은 모두2026-11-23으로 같았다. 공개가격은60개이므로 직전가격 없는 첫날을 빼면 비교 가능한 등락은59개다.

| 종목 | 공시 행 수 | 저장된 공시 최초일 | 저장된 공시 최신일 | 저장된 기사 최초일 | 저장된 기사 최신일 |
|---|---:|---|---|---|---|
| 005930 | 39 | 2026-10-08 | 2026-11-18 | 2026-08-26 | 2026-11-25 |
| 005380 | 19 | 2026-10-22 | 2026-11-24 | 2026-08-26 | 2026-11-25 |
| 068270 | 11 | 2026-10-12 | 2026-11-16 | 2026-08-27 | 2026-11-25 |
| 035720 | 19 | 2026-10-08 | 2026-11-25 | 2026-08-26 | 2026-11-25 |

최초일·최신일과 행 수는 중간 날짜의 완전 수집을 증명하지 않는다. 기존 공개차트의60개 날짜 중27개에서 KOSPI 자료를 읽지 못했다. 그날은 근처 날짜나0%로 바꾸지 않고 비교 자료 미제공으로 보여야 한다.

`budget_usage`의 공개GET은HTTP401이었다. 따라서 공개 자료의 날짜·건수는 확인했지만 실제 DB 용량은 확인하지 못했다. 120일 운영 전환의 용량 게이트는 아직 통과하지 않았다.

## 임계값 예비 비교

동일한59개 일간 등락과 동일 제외 규칙으로1.5배·2배·3배의 후보 수를 셌다. 아래 숫자는 최대3개로 자르기 전 후보 수다. 운영DB의 기존 반올림 연환산 변동성을 하루 기준으로 바꿔 사용했으므로 새로 구현하는 동일입력250수익률 기준의 최종 검증과 다르다.

| 종목 | 1.5배 | 2배 | 3배 |
|---|---:|---:|---:|
| 005930 | 2 | 0 | 0 |
| 005380 | 0 | 0 | 0 |
| 068270 | 4 | 2 | 0 |
| 035720 | 2 | 2 | 1 |

2배에서 선정된 날짜는068270의2026-10-16·11-05와035720의2026-11-05·11-23이다. 0건인 종목도 정상 결과로 인정하며 표시 개수를 맞추려고 기준을 낮추지 않는다.

구현의 초기 기본값은 기존 계획의2배를 유지한다. 이번 비교는 민감도 차이를 보여주지만2배가 최적이라는 증거, 가격 변동 원인의 정답, 사용자 효과의 검증은 아니다. 실제 신규 기준 객체와 전체 입력을 재현한 검증 및 사용자 미리보기 검토 결과가 달라지면 이슈에 대체 이유를 남기고 변경한다.

## 구현 결과

`prices.history`는 기존 60개를 유지한다. 같은 검증된 수정가격에서 직전 가격과 최근 최대 250개 로그수익률의 변동 기준을 계산해 선택 필드 `prices.event_basis`에 묶었다. 실제 표본 수와 시작일·종료일·입력 해시를 함께 제공한다. 기준이 없거나 손상된 옛 응답은 일반 차트를 유지한다.

프론트는 통신 없는 판정 함수, 공개 DB 응답 검증, 요청 상태 관리, 화면을 분리했다. 최근 60거래일에서 기준을 넘는 최대 3일을 고르고 날짜별 공시와 같은 날 코스피를 보여준다. 성공 0건·자료 미제공·불량 응답·조회 실패·갱신 실패는 서로 다른 상태다. 늦게 도착한 다른 종목이나 이전 시도의 응답은 버린다. 실제 뉴스 조회는 활성화하지 않았다.

공시 수집은 KST 최근 7달력일을 겹쳐 읽는다. 명시한 날짜 범위와 dry-run도 지원한다. 날짜의 모든 페이지를 검증하고 모든 upsert가 끝난 뒤 그 날짜를 성공으로 기록한다. 보존 CLI는 기본 90일을 유지하며 `--article-days 120`과 GET 전용 `--dry-run`을 준비했다. 운영 설정은 바꾸지 않았다.

### 재현 결함과 수정 이유

| 재현한 문제 | 수정과 검증 |
|---|---|
| 예전 parquet 캐시의 수정 기준이 섞인 긴 구간으로 변동성 산출 | 새로 받아 검증한 구간의 시작일을 parquet 속성에 보존한다. 속성 없는 캐시와 겹치는 값이 바뀐 캐시는 새 수집 구간부터 신뢰한다. 이틀 연속 수집을 DataFrame 복사의 모의 저장소로 재현했다 |
| 수정계수 나눗셈·곱셈 오차로 정확히 2배인 날이 후보로 포함 | 등락을 `(close - previous) / previous`로 계산하고 가격 단위에서 비교한다. 고정 소수 자릿수 대신 `Number.EPSILON`으로 입력과 산술의 반올림 오차를 전파한다. 오차 범위의 동률은 최신순으로 고른다 |
| 양쪽 모델에 같은 중간 행이 빠진 59가격 응답에서 이틀 등락을 하루로 연결 | 공개 parser가 정확히 60가격인 경우에만 추가 판정 기준을 수용한다. 일반 차트는 유지하고 변동일과 자료 조회를 제외한다 |
| 요청 밖 코스피 날짜나 타종목·기간 밖 공시를 정상 빈 결과로 오인 | 응답 경계에서 요청 날짜·종목·기간을 검증한다. 정상 대응이 있는 날짜는 보존하고 불량·부분 불량을 구분한다 |
| DART 응답 본문이 끊기면 제한 재시도와 완료일 결과를 우회 | `IncompleteRead`와 `RemoteDisconnected`를 포함한 전송 오류도 제한 재시도한다. 실패 후에도 이전 완료일을 보존하며 키와 응답 본문은 출력하지 않는다 |

수정주가의 실제 재구성 예시 `raw 290 → 319`, `adjusted 1000 → 1100`에서 첫 가격은 `999.9999999999999`가 된다. 이 예시는 단위 회귀로 검증했다. 별도로 원가격 10~150·다음 가격에 29를 더한 조합, 5개 가격 크기·상하 방향으로 2,820개 smoke 검사를 실행했다. 정확한 경계는 제외하고 오차를 넘는 초과는 포함했다. 이 오차 처리는 통계 임계값 2배를 느슨하게 바꾸는 제품 정책이 아니다. 입력 재구성 방법이 바뀌면 오차 전파와 대조 예시를 다시 검증한다.

독립 검토자가 별도 `issue492-cache-parquet-smoke.py`도 실행했다. 모의 전송으로 실제 `SupabaseStore.save_price_history/load_price_history`의 parquet 바이트 저장·재읽기를 재현했다. 연속 두 거래일 2025-01-31·02-03에서 신뢰 시작일 2024-06-05가 유지됐고 실제 172·173개 수익률과 sigma 동등성을 확인했다. 운영 Storage에는 요청하지 않았다. 스크립트와 로그는 검증 폴더에 남겼다. 재실행할 때는 chart 폴더에서 검증 폴더 경로를 지정한 뒤 실행한다.

```sh
verification_dir='/Users/cracker/.codex/visualizations/2026/11/25/01a212ca-b615-7c40-934d-9500301242ff'
PYTHONPATH=. PYTHONDONTWRITEBYTECODE=1 /private/tmp/serving-adjustment-venv/bin/python "$verification_dir/issue492-cache-parquet-smoke.py"
```

## 실행한 검증

| 대상 | 실행 명령 | 결과 |
|---|---|---|
| chart 전체 | 아래 chart 전체 명령 | 495 passed, 3 skipped. 같은 조건의 기준 커밋은 485 passed, 3 skipped |
| chart CI 범위 | 아래 격리 shared·serving 명령 | 154 passed |
| chart lint | chart 폴더에서 `ruff check --no-cache .` | 통과 |
| text 전체 | 아래 text 명령 | 275 passed, 기존 경고 2개 |
| text lint | text 폴더에서 `ruff check --no-cache .` | 통과 |
| web 단위 | frontend 폴더에서 `pnpm test:unit` | 196 passed |
| web production | frontend 폴더에서 `pnpm build` | TypeScript와 23개 정적 페이지 생성 통과 |
| web E2E | `PLAYWRIGHT_BROWSERS_PATH=/private/tmp/market-tip-playwright pnpm exec playwright test tests/e2e/price-events.spec.ts --project=chromium` | Chromium 7 passed. 별도 production 서버에서도 아래 브라우저 비교를 실행했다 |
| web lint | 변경한 TS·TSX 파일을 대상으로 `pnpm exec eslint` | 통과 |
| 공개 자료 감사 CLI | text 폴더에서 `python -m value_pipeline.price_context_audit --date 2026-10-16 --date 2026-11-05 --date 2026-11-23 --radius 3` | 실제 GET만 실행. 세 출처 status `ok`, coverage `unverified`, 종료 0 |
| 계약 연결 | Python 생성 payload를 실제 TS parser와 판정 함수에 입력 | H5/H20 모두 파싱·기준일·직전 가격 검증 통과 |
| 독립 검토 | 구현에 참여하지 않은 `gpt-6.2-sol`이 결함 직접 재현 및 변경 관련 단위 17건 실행 | 위 경계·59행·날짜 오염·출처 문구 지적을 닫음 |

chart 전체는 기준 커밋과 변경본을 각각 `/private/tmp/issue492-chart-check-head/backend/analysis/chart`와 `/private/tmp/issue492-chart-check-feature/backend/analysis/chart`에 복사해 같은 명령으로 실행했다. 전체 테스트가 만드는 작업 폴더를 쓸 수 있게 격리한 것이며 검사 소스는 작업 트리와 같다. CI 픽스처 `.github/workflows`도 포함했다. 권한 오류를 테스트 통과로 세지 않았다.

```sh
OMP_NUM_THREADS=1 PYTHONDONTWRITEBYTECODE=1 /private/tmp/takealook-alpha158-venv/bin/python -m pytest -q --tb=short -W ignore::DeprecationWarning -W ignore::FutureWarning -p no:cacheprovider
```

격리 shared·serving 검사는 `/private/tmp/issue492-chart-check-serving`에서 다음 명령으로 실행했다. 전체 검사의 기존 경고 필터와 별도로 CI의 NumPy timedelta 경고 정책을 확인했다.

```sh
OMP_NUM_THREADS=1 PYTHONDONTWRITEBYTECODE=1 /private/tmp/serving-adjustment-venv/bin/python -m pytest -q --tb=short -p no:cacheprovider shared/tests serving/tests -W "error:The 'generic' unit for NumPy timedelta is deprecated:DeprecationWarning" -W "ignore:The 'generic' unit for NumPy timedelta is deprecated:DeprecationWarning:exchange_calendars.exchange_calendar" -W "ignore:The 'generic' unit for NumPy timedelta is deprecated:DeprecationWarning:exchange_calendars.utils.pandas_utils"
```

text는 작업 트리의 `backend/analysis/text`에서 다음 명령으로 실행했다. chart와 text의 lint 실행 파일은 각 명령에 사용한 가상 환경의 `bin/ruff`다.

```sh
OMP_NUM_THREADS=1 PYTHONDONTWRITEBYTECODE=1 /private/tmp/news-policy-docs-venv/bin/python -m pytest -q -p no:cacheprovider
```

web은 `pnpm@10.33.0`, `Next 16.4.5`, `React 19.3.0`, `Playwright 1.63.0`을 lockfile대로 설치했다. 원래 체크아웃의 다른 Next 버전은 사용하지 않았다. 검증 사본 `/private/tmp/issue492-web-verify/frontend`에서 단위·빌드·E2E를 실행했고 변경 파일은 작업 트리와 바이트가 같다. `pnpm`은 `npm exec --yes --package=pnpm@10.33.0 -- pnpm …`으로 준비한 실행 파일을 사용했다. `NEXT_TELEMETRY_DISABLED=1`을 설정했다. 빌드와 E2E의 Supabase 주소는 로컬 모의 서버이며 운영 DB 쓰기를 하지 않는다. 작업 트리 자체에서도 같은 버전의 production build를 실행했다.

최종 web lint는 작업 트리의 frontend 폴더에서 아래 명령으로 실행했다. 출력 없이 종료 0이었다.

```sh
pnpm exec eslint app/components/chart-preview.tsx app/components/price-history-chart.tsx app/components/stock-detail.tsx app/components/price-event-panel.tsx lib/chart-public.test.ts lib/chart-public.ts lib/copy-rules.test.ts lib/copy-rules.ts lib/use-public-charts.ts lib/price-events.test.ts lib/price-events.ts lib/providers/price-event-context.test.ts lib/providers/price-event-context.ts lib/use-price-events.ts tests/e2e/price-events.spec.ts tests/e2e/price-events-fixture.mjs tests/e2e/supabase-stub.mjs
```

E2E는 키보드·터치 선택, 4개 화면 폭, 공시 더 보기, 실제 코스피 0%, 성공 0건·출처별 실패·부분 불량, 재시도·갱신 실패, 같은 키와 다른 종목의 응답 역전, 옛 payload, 새 batch의 선택 유지·초기화, 양쪽 모델의 동일 59행 누락을 포함한다.

## 화면과 조회·성능 비교

동일한 가상 가격·공시·코스피를 사용하는 로컬 production 서버에서 기준 커밋과 구현본을 비교했다. 실제 계좌와 보유 수치는 사용하지 않았다. 대상 4종목을 1280px·390px에서 각각 캡처해 전후 16개 이미지를 남겼다. 데스크톱·모바일 이미지를 직접 확인했고 320px·1024px의 문서 가로 넘침도 E2E로 검사했다.

측정 환경은 Node 26.13.1, Next 16.4.5, Playwright 1.63.0, Chrome 158.0.8127.38, 논리 CPU 10개다. 005930 페이지에서 각 서버를 한 번 예열한 뒤 새 브라우저 컨텍스트로 5회씩 번갈아 측정했다. 크기는 1280×1000이며 네트워크 제한은 없다. LCP는 브라우저 PerformanceObserver로 읽었다. 가격 DOM 준비는 별도의 DOM 관측값이며 화면에 그려진 시간으로 해석하지 않는다.

| 측정 | 기준 커밋 | 구현본 |
|---|---:|---:|
| 가격 DOM 준비 중앙값 | 152.6ms | 153.3ms |
| 가격 DOM 준비 p95 | 170.4ms | 174.4ms |
| 페이지 LCP 중앙값 | 168ms | 168ms |
| 페이지 LCP p95 | 184ms | 192ms |
| 기능의 최초 추가 DB 읽기 | 0 | 4 |
| 변동일 선택의 추가 읽기 | 해당 기능 없음 | 0 |
| 페이지 예외·HTTP 400 이상 응답·문서 가로 넘침 | 0 | 0 |

표본 5개에서 p95는 사실상 최댓값이다. 추가 8ms는 제안한 100ms 허용폭 이내였지만 이 측정은 페이지 LCP이며 가격만의 paint 지표가 아니다. 운영 가격 LCP의 회귀 통과나 속도 개선을 입증하지 않는다. 실제 DB 지연·캐시·기기별 측정은 남아 있다. 가격 표시가 문맥 자료 응답을 기다리지 않는지는 소스 구조와 출처 지연 E2E로 별도 검증했다.

하나의 합성 payload는 3,923→4,239 bytes로 316 bytes 늘었다. 합성 parquet는 60→61행에서 4,888→4,911 bytes로 23 bytes 늘었고 manifest의 기준 기록은 599 bytes였다. 동일 입력의 단일 예시이며 운영 전체 전송량·압축률·처리량을 대표하지 않는다. 전체 250일 가격을 브라우저에 새로 보내거나 공급자 API를 추가 호출하지 않는다.

고정 모의 저장소의 보존 비교는 90일·120일 모두 HTTP 9회, 기사·공시 DELETE 2회였다. 2026-11-25의 cutoff만 08-27→07-28로 바뀌었다. dry-run은 한 페이지씩이면 GET 2회이며 페이지가 많으면 늘어난다. 실제 DB의 실행계획·인덱스 비용·안정 용량은 측정하지 않았다.

## 검증 자료

이 채팅에 연결된 로컬 검증 폴더에 다음 자료를 남겼다. 저장소에는 인증값·기사 본문·실제 계좌·보유 캡처를 넣지 않는다.

- `issue492-live-audit.json`, `issue492-public-snapshots.json`, `issue492-audit-cli-result.json`
- `issue492-browser-verification.json`
- `issue492-before-{종목코드}-{1280 또는 390}.png`, `issue492-after-{종목코드}-{1280 또는 390}.png`
- `issue-492-decisions.tsv`
- chart·text·web의 최종 검증 로그
- `issue492-rounding-smoke.mjs`, `issue492-rounding-smoke.log`, `issue492-cache-parquet-smoke.py`, `issue492-cache-parquet-smoke.log`

## 적용 원칙

| 원칙 | 바꾼 선택 |
|---|---|
| Model the Domain | 출처별 성공 0건과 실패·미제공·갱신 실패를 결과 타입에 담았다 |
| Boundary Discipline | 외부 응답의 날짜·종목·URL 검증을 로더에 두고 판정 함수에는 통신을 넣지 않았다 |
| Prove It Works | 단위 테스트 뒤 실제 Python→TS payload와 production 브라우저 화면·선택을 확인했다 |
| Explain the Number | 2배의 예비 비교와 신규 기준의 최종 검증을 구분하고 소표본 LCP를 운영 성능 보장으로 해석하지 않았다 |
| Separate Before Serializing Shared State | 기존 사용자 체크아웃과 분리한 작업 트리에서 구현하고 소유 파일을 나눴다 |
| Sequence Work into Verifiable Units | 차트 계약, 수집기, 화면, 결과 문서를 별도 검증·커밋 범위로 나눴다 |
| Experience First | 원인 추정 문장보다 날짜가 맞는 공시·시장 비교를 먼저 보이게 했다 |
| Encode Lessons in Structure | 누락 가격·경계값·응답 역전·전송 단절을 회귀 테스트로 남겼다 |

## 운영에 남는 확인

- 실제 DB 용량과120일 예측 용량, 취득 자료의 보관 권한은 미확인이다.
- 공개payload 계약 추가는 로컬 구현 검토안이며 팀 확인 전 운영에 적용하지 않는다.
- 뉴스의 행별 출처와 공개 제공 권한은 미확인이므로 새 기능에서 실제 뉴스 조회를 활성화하지 않는다.
- 보존120일 옵션과 dry-run을 구현하더라도 운영 명령·정기 실행 전환은 별도 확인 뒤 진행한다. 이번 작업에서 실제 보존 기간을 늘렸다고 보고하지 않는다.
- 기존 공시 workflow는 인자 없이 CLI를 실행하므로 코드가 적용되면 다음 실행부터 3→7일 조회·upsert로 바뀐다. YAML을 수정하지 않았어도 담당자와 DART 잔여 예산을 확인한 뒤 적용해야 한다.
- main 대비 독립 보안 검토에서 새 권한 확대·비밀 출력·외부 입력 기반 서버 요청·브라우저 쓰기는 발견하지 못했다. 로컬 모의 검증 47건을 통과했으며 운영 호출·쓰기 검증을 대신하지 않는다.

## 2026-11-26 커밋 후 재검증

사용자의 추가 검증 요청으로 `c252589b4f5520be1c84876fdfc897ba4ba6bc96`의 실제 작업 트리에서 다시 실행했다. 시작 시 작업 트리는 깨끗했으며 기능 코드는 바꾸지 않았다. 이번에는 production build를 만든 뒤 같은 빌드에서 Chromium 검증을 실행했다.

| 검사 | 결과 |
|---|---|
| chart 전체, 앞서 기록한 전체 명령 | 495 passed, 기존 3 skipped |
| text 전체, 앞서 기록한 text 명령 | 275 passed, 기존 경고 2개 |
| web `node --test 'lib/**/*.test.ts'` | 196 passed |
| web `pnpm build` | Next 16.4.5 production build·TypeScript·23개 정적 페이지 생성 통과 |
| production Chromium, 아래 명령 | 7 passed, 재시도 0 |
| chart·text Ruff와 변경 web 파일 ESLint | 통과 |
| 수정주가 오차 smoke·parquet 바이트 왕복 | 2,820개 검사와 두 거래일 저장·재읽기 통과 |

web 빌드는 `NEXT_PUBLIC_SUPABASE_URL=http://127.0.0.1:54321`, `NEXT_PUBLIC_SUPABASE_ANON_KEY=e2e-anon-key`, `NEXT_PUBLIC_CHART_LOCAL_PREVIEW=0`, `NEXT_TELEMETRY_DISABLED=1`로 실행했다. pinned pnpm 10.33.0을 사용했다. 빌드용 로컬 모의 서버를 종료한 뒤 E2E가 모의 DB와 production 서버를 직접 시작·정리했다. `CI=1`이면 `playwright.config.ts`가 `pnpm start --port 3101`을 실행한다. 로컬 모의 자료의 production 빌드 검증이며 운영 환경 E2E는 아니다. ESLint는 위에 기록한 변경 17파일 명령과 같으며 출력 없이 종료 코드 0이었다.

```sh
CI=1 NEXT_TELEMETRY_DISABLED=1 PLAYWRIGHT_BROWSERS_PATH=/private/tmp/market-tip-playwright pnpm exec playwright test tests/e2e/price-events.spec.ts --project=chromium --retries=0
```

로그는 앞서 설명한 검증 폴더의 `issue492-recheck-{chart,text,web-unit,web-build,web-e2e-production,chart-ruff,text-ruff,web-eslint,rounding,parquet}.log`다. 원래 있던 chart 제외 3개는 샘플 processed 패널이 없는 경우다. 테스트를 통과시키기 위해 제외 조건이나 경고 정책을 바꾸지 않았다. 운영 DB 쓰기·외부 공급자 수집·보존 설정 전환·배포는 실행하지 않았다.

Prove It Works 원칙에 따라 production 브라우저에서 동작을 다시 확인했다. 공시·코스피 1차 기능의 로컬 구현과 검증은 끝났으며, 위 운영 확인과 신규 기준의 실데이터 전체 입력 대조·사용자 검토·뉴스 제공 조건은 남아 있다.
