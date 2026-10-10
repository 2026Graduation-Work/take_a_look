# 뉴스·재무 Supabase 적재와 종목 화면 연결 설계

## 목적

BigKinds 과거 뉴스, NewsAPI.ai 최근 뉴스, DART 재무 분석 결과를 네 종목에 대해
Supabase에 반복 가능하게 적재하고, 종목 화면은 Supabase 데이터를 우선 사용하되
외부 장애나 미설정 환경에서는 현재 정적 JSON으로 안전하게 폴백한다.

대상 종목은 삼성전자(`005930`), 현대차(`005380`), 카카오(`035720`),
셀트리온(`068270`)으로 고정한다.

## 성공 기준

- 평일 오전 9시(KST)에 GitHub Actions가 종목별 NewsAPI.ai 검색을 한 번씩 실행한다.
- 한 종목의 최신 기사 후보를 최대 100건 받고, 중복·관련성 필터를 통과한 기사
  전체를 KR-FinBERT로 분석한다.
- 같은 실행을 반복해도 뉴스·재무 행이 중복되지 않는다.
- NewsAPI.ai 결과가 100건 한도를 넘으면 `partial` 상태와 커버리지 근거를 남긴다.
- 종목 화면은 Supabase의 live 뉴스, historical 그래프, 대표 기사 3건, 최신 DART
  지표를 사용한다.
- Supabase가 없거나 조회에 실패하면 기존 정적 데이터로 화면을 유지하고 출처를
  픽스처로 표시한다.
- API 키나 Supabase Secret Key는 저장소나 프론트 번들에 포함하지 않는다.

## 범위

### 포함

- Python Supabase REST 적재 어댑터
- 뉴스·재무 JSON을 테이블 행으로 바꾸는 결정론적 매핑
- 기존 4종목 BigKinds/DART JSON backfill 명령
- 종목별 NewsAPI.ai 호출과 KR-FinBERT 배치 추론
- 평일 09:00 KST GitHub Actions와 수동 실행
- 프론트 Supabase 우선 조회 및 정적 JSON 폴백
- 단위 테스트, 통합 계약 테스트, 실행 문서

### 제외

- 한국 거래소 휴장일 판별
- NewsAPI.ai 두 번째 페이지 이후 수집
- DART 자동 정기 스케줄
- 기사 본문·요약의 장기 저장
- 매매 추천이나 자동 주문

## 데이터 흐름

### 최근 뉴스

1. GitHub Actions가 `cron: "0 0 * * 1-5"` 또는 `workflow_dispatch`로 실행된다.
2. 네 종목을 한 OR 검색으로 묶지 않고 종목별로 각각 검색한다.
3. 직전 24시간을 포함하도록 API 날짜 범위를 넓게 요청하고, 발행시각으로 정확한
   24시간 범위를 로컬에서 결정론적으로 자른다.
4. 종목 관련성 규칙과 `news_id` 중복 제거를 적용한다.
5. 관련 기사 전체(공급자 상한 내)를 KR-FinBERT 배치 추론한다.
6. 요약, 날짜별 값, 분석 근거 기사 메타데이터를 부모-자식 순서로 upsert한다.
7. 화면에는 최신 대표 기사 3건만 표시하되, 감성값은 관련 기사 전체로 계산한다.

### 과거 뉴스와 재무

- BigKinds historical JSON의 요약·timeline·article 메타데이터를 동일한 뉴스 테이블에
  `track='historical'`로 backfill한다.
- 기존 4종목 DART JSON을 `financial_snapshots`에 upsert하고 반환된 UUID를 이용해
  `financial_metrics`를 upsert한다.
- backfill은 자동 cron에 포함하지 않고 명시적인 CLI 명령으로 실행한다.

## 적재 어댑터

추가 Python 패키지를 늘리지 않고 기존 `requests`로 Supabase PostgREST를 호출한다.
어댑터는 HTTP 세부사항과 도메인 매핑을 분리한다.

- `SupabaseRestClient`: 인증 헤더, timeout, upsert, select, 오류 변환
- 뉴스 매퍼: NewsTrack JSON → `news_sentiment_tracks`, `news_sentiment_daily`,
  `news_articles`
- 재무 매퍼: FinancialTrack JSON → `financial_snapshots`, `financial_metrics`
- orchestration 명령: live sync와 파일 backfill

환경변수는 `SUPABASE_URL`, `SUPABASE_SECRET_KEY`를 사용한다. 이전 환경과의 호환이
필요하면 `SUPABASE_SERVICE_ROLE_KEY`를 폴백으로 읽되 문서에서는 Secret Key를
정본으로 안내한다.

## upsert와 일관성 규칙

- 뉴스 부모 키: `(stock_code, track)`
- 뉴스 일별 키: `(stock_code, track, sentiment_date)`
- 기사 키: `(stock_code, track, news_id)`
- 재무 스냅샷 키: `(stock_code, as_of, fiscal_year)`
- 재무 지표 키: `(snapshot_id, metric_key)`
- 부모 upsert가 성공한 뒤 자식을 적재한다.
- 기사 0건, FinBERT 미사용, 공급자 인증·쿼터 오류인 결과는 기존 정상 track을
  덮어쓰지 않는다.
- 종목 하나가 실패해도 나머지는 처리하되 전체 명령은 비정상 종료해 Actions에서
  실패를 알린다.

## 감성 분석 실행 규칙

- GitHub Actions에서는 KR-FinBERT 사용을 강제한다.
- 모델 로드 또는 추론 실패 시 사전 기반 결과를 Supabase에 섞지 않고 실패한다.
- `transformers` pipeline에 문자열 목록과 batch size를 전달해 순차 1건 호출을
  배치 추론으로 바꾼다.
- Hugging Face 모델 캐시를 Actions cache에 보존한다.
- 감성 평균과 의견 분산은 현재 결정론적 집계 함수를 그대로 사용한다.

## 오류 처리

- 일시적 네트워크 오류와 5xx만 지수 백오프로 최대 3회 재시도한다.
- 인증 실패, 잘못된 요청, 쿼터 소진은 즉시 중단한다.
- Supabase 쓰기 실패는 응답 본문에서 비밀값을 제거한 도메인 오류로 변환한다.
- 실패 실행은 이전 정상 행을 삭제하거나 빈 값으로 갱신하지 않는다.
- workflow 동시 실행은 `concurrency`로 한 개만 허용한다.

## 프론트 조회와 폴백

프론트 provider 인터페이스 뒤에 Supabase 조회 구현을 추가한다.

- historical 날짜별 데이터 → 과거 감성 그래프
- live track → 최근 24시간 뉴스 분위기와 기준시각
- live articles → 발행시각 최신순 대표 기사 3건
- 최신 financial snapshot + metrics → 회사 체력

`loadStockInsights`는 Supabase 결과가 완전할 때 이를 사용한다. 클라이언트 미설정,
조회 오류, 필수 데이터 없음이면 기존 provider를 사용한다. 데이터 출처에는
`NewsAPI.ai · KR-FinBERT`, `BigKinds · KR-FinBERT`, `DART 사업보고서` 또는
`픽스처`를 명시한다. `partial`은 데이터가 없는 것으로 숨기지 않고 수집 범위가
일부임을 화면에 표시한다.

## GitHub Actions

workflow는 다음 repository secrets를 읽는다.

- `NEWSAPI_AI_KEY`
- `SUPABASE_URL`
- `SUPABASE_SECRET_KEY`

Secrets가 필요한 코드와 workflow까지만 저장소에 구현한다. 실제 값은 저장소
관리자가 GitHub Actions Secrets에 직접 등록한다. workflow는 Python 3.12, CPU용
PyTorch, 텍스트 파이프라인 requirements를 사용한다.

## 테스트

- 종목별 4회 API 호출과 OR 검색 미사용
- 정확한 24시간 경계와 KST 날짜 그룹
- 관련 기사 전량이 점수 집계에 들어감
- FinBERT 배치 결과가 기존 단건 결과 계약과 동일함
- 뉴스·재무 JSON별 행 매핑 및 upsert conflict key
- 반복 적재의 멱등성
- 부분 성공 후 최종 비정상 종료
- Supabase 정상 조회와 각 실패 조건의 정적 fallback
- 대표 기사가 정확히 최대 3건이며 최신순임
- Python `ruff`·`pytest`, 프론트 테스트·lint·build

## 배포 순서

1. 코드와 테스트를 PR로 머지한다.
2. GitHub repository secrets 세 값을 관리자가 등록한다.
3. 수동 workflow 실행으로 네 종목 live 적재를 확인한다.
4. backfill 명령으로 historical 뉴스와 DART 데이터를 적재한다.
5. Supabase Table Editor와 종목 화면을 확인한다.
6. 수동 검증 후 평일 오전 9시 cron을 유지한다.
