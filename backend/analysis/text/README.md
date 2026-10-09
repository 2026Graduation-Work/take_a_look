# 🟢 Analysis · Text — 뉴스/재무제표

담당: 서환

## 역할

뉴스 감성과 재무제표(가치투자 펀더멘털)를 분석하여
시장 외부 정보를 정량화한다.
(SNS/소셜 심리는 데이터 확보 난이도로 파이프라인에서 제외됨 → News + Financial 2-에이전트.)

## 입력 데이터

- 과거 뉴스 — 빅카인즈 수동 다운로드 엑셀(`data/<종목코드>/{회사명}_{YYYYMMDD}-{YYYYMMDD}.xlsx`)
- 최근 뉴스 — NewsAPI.ai 한국어 기사(`NEWSAPI_AI_KEY` 필수). 종목별 최대 100건을 각각 조회
- 재무제표 — DART OpenAPI (`DART_API_KEY` 필수)
- profiling 블록의 사용자 컨텍스트 JSON

## 핵심 원칙: 할루시네이션 = 즉사

- 정량 데이터(PER 등 수치)는 DB/API에서 직접 조회
- **점수 산출은 100% 결정론.** 뉴스 관련성 판정까지 규칙으로 한다 — 어떤 기사를 채점할지
  LLM이 정하면 그건 곧 점수를 LLM이 정하는 것이다
- LLM은 핵심 이벤트 추출·근거 문장만 담당. `GEMINI_API_KEY` 유무로 숫자가 바뀌면 버그
- LLM 출력은 content-hash로 캐시되어 설명 텍스트까지 재현 가능

## 코드

- `value_pipeline/` — 가치투자 피처 전처리 파이프라인 (빅카인즈 뉴스 감성 + DART 재무제표 → 구조화 JSON).
  LangGraph 오케스트레이션:
  `START → ingest → {news_agent ‖ financial_agent} → validation_agent → synthesis_agent → END`.
  뉴스 수집은 `preprocess.load_daily_news()`(빅카인즈 point-in-time 로더)를 우선 사용한다.
  실행: `backend/analysis/text/`에서 `python -m value_pipeline.run` (일별 1행).
  기간 요약은 `--period 2022-01`(월)·`--period 2022`(년) — 재무는 기간 종료일 기준
  point-in-time, 뉴스는 기간 전체 기사 가중 집계 1건. `--no-llm`으로 키가 있어도
  LLM 호출 차단(숫자 불변). 학습 데이터셋 대량 생성은 `python -m value_pipeline.batch`
  (LLM 강제 OFF + 수집 캐시), 모델 입력 변환은 `python -m value_pipeline.features`
  (피처 선택 규칙의 SSOT).
  **검증 기준: [VALUE_PIPELINE_VALIDATION.md](VALUE_PIPELINE_VALIDATION.md)** — 출력을 데이터셋에
  넣기 전에 반드시 이 문서의 PASS/FAIL 기준을 따를 것.
- `preprocess.py` — 빅카인즈 수동 다운로드 엑셀을 병합·정제하여 FinBERT 입력 CSV 생성.
  `load_daily_news()`는 value_pipeline이 쓰는 하루치 point-in-time 로더.

## 뉴스 심리지수 2-track

두 트랙은 소스와 시간 창만 다르고, 관련성 필터와 `sentiment.score_texts()`
(KR-FinBERT 우선, 없으면 사전 폴백)를 공유한다. 이는 매수·매도 지시가 아니라
사용자가 현재 판단을 재점검하는 근거이다.

- `historical`: BigKinds 과거 기사 → 일별 평균 감성·의견 분산·기사 수 추이
- `live`: NewsAPI.ai → KST 기준 직전 24시간 감성·최신 기사 시각·지연 분

삼성전자(`005930`)는 NewsAPI.ai의 한국어 붙임말 색인에서
`삼성전자`를 0건으로 반환하므로 `삼성`으로 수집한 뒤, 제목·본문에
`삼성전자`가 명시된 기사만 관련 기사로 남긴다. 삼성생명·삼성 라이온즈 등
다른 계열·동일명 기사는 감성 분석에 넣지 않는다.

`.env`:

```dotenv
NEWSAPI_AI_KEY=
SUPABASE_URL=
SUPABASE_SECRET_KEY=
```

과거 트랙 생성:

```bash
cd backend/analysis/text
python -m value_pipeline.news_run historical \
  --target 005930:삼성전자 --start 2022-01-01 --end 2022-12-31
```

최근 뉴스를 파일로 즉시 1회 수집(종목별 API 1회):

```bash
python -m value_pipeline.news_run live \
  --target 005930:삼성전자 --target 035720:카카오
```

Supabase에 네 종목 최근 뉴스를 수집·분석·적재(KR-FinBERT 필수):

```bash
python -m value_pipeline.supabase_sync live
```

특정 종목만 시험하려면 `--target 005930:삼성전자`를 반복해서 지정한다. `live`는
보도 시각과 API 색인 지연이 있는 **일 단위 뉴스 분석**이지 틱 단위 실시간은 아니다.
산출 JSON과 DB는 기사 본문을 저장하지 않고 `news_id`, 제목,
언론사, URL, 시각, 사건 ID, 감성 결과만 보존한다. 기본 출력 위치는
`out/news_tracks/`이다.

각 종목 검색은 호출당 최신 100건까지만 받는다. 전체 검색 결과가 이를 넘으면
`status=partial`, `coverage.provider_truncated=true`와 공급자 전체·반환 건수를 함께
기록한다. 따라서 이 값은 수집 범위를 숨긴 완전한 시장 전수조사가 아니라, 표시된
커버리지 안에서의 뉴스 분위기이다.

과거 뉴스와 DART JSON을 Supabase에 최초 적재하거나 다시 upsert할 때:

```bash
python -m value_pipeline.supabase_sync backfill-news \
  ../../../frontend/lib/providers/sentiment-005380.json
python -m value_pipeline.supabase_sync backfill-financial \
  value_pipeline/output_sample/financial_tracks/*_financial.json
```

동일 파일을 다시 실행해도 migration 0005의 고유키로 upsert되어 중복 행이 생기지
않는다. 한 종목/파일이 실패해도 나머지는 처리하지만 명령은 종료 코드 1을 반환한다.
오류 실행이나 관련 기사 0건은 기존 정상 뉴스 track을 덮어쓰지 않는다. 관련 기사
0건은 `skipped (no_relevant_news)`로 기록하고 정상 종료하며, API·DB 오류는
비밀값이 없는 오류 코드를 남기고 종료 코드 1을 반환한다.

### GitHub Actions 자동 적재

저장소 관리자가 GitHub의 **Settings → Secrets and variables → Actions**에서 다음
Repository secret을 직접 등록한다. 값은 채팅·이슈·커밋에 남기지 않는다.

- `NEWSAPI_AI_KEY`
- `SUPABASE_URL`
- `SUPABASE_SECRET_KEY`
- `DART_API_KEY` (공시·재무, 2026-10-07 등록)

workflow 이름은 `News Supabase Sync`다.

- 평일 09:13 KST: `live --dynamic`으로 **기본 6종목 + 전체 사용자의 보유 ∪ 활성 관심 종목**의 직전 24시간 뉴스를 적재한다. 하루 호출 상한 20회(`NEWSAPI_DAILY_CALLS`). 첫 페이지(최신 100건)가 꽉 차고 잘린 종목은 상한 안에서 2페이지(그다음 100건)를 더 받는다. 넘으면 절반은 최근 등록 순, 나머지는 날마다 순환. 실행 전후 NewsAPI.ai 남은 횟수를 로그(`newsapi_targets`·`newsapi_usage`)에 남긴다.
- 같은 실행에서 `disclosures`: DART 하루 전체 공시(최근 3일)를 종목 마스터에 맞춰 적재(제목·날짜·유형만, 유형표 `docs/disclosure-kinds.md`).
- 매주 월 07:30 KST: `financial-latest`로 같은 대상의 **최신 정기보고서**(분기·반기·사업) 재무를 접수번호가 바뀐 종목만 갱신.

Actions 화면의 **Run workflow**에서는 다음 모드를 선택한다.

- `live`: NewsAPI.ai 수집 → KR-FinBERT 분석 → 최신 뉴스 upsert(+ 공시)
- `financial`: 최신 정기보고서 재무 갱신
- `live-samsung`: 삼성전자(`005930`) 한 종목만 재실행. 적재 실패 진단·복구에 사용
- `reset-live`: 대상 종목(동적 목록)의 새 Live 수집·검증이 성공한 경우에만 그 종목의 이전 Live 행을 교체
- `backfill`: 저장소의 4종목 BigKinds 과거 JSON과 DART 재무 JSON upsert

Secret 등록 후 운영 전에 수동 `backfill`과 `live`를 각각 한 번 실행한다. 로그와
Supabase 행을 확인한 뒤 평일 자동 실행을 유지한다.
적재 실패 로그는 응답 본문과 인증값을 출력하지 않고,
실패한 테이블·HTTP 상태 또는 내부 검증 항목만 표시한다.

### 2026 BigKinds 과거 뉴스 적재

`data/`는 GitHub Actions에 올리지 않는 로컬 원본이므로, 2026-01-01부터 2026-10-04까지의
BigKinds 적재는 해당 파일이 있는 개발 환경에서 한 번 실행한다. 이 명령은 6종목의
`historical` track을 upsert하며, `live` track을 지우지 않는다.

```bash
cd backend/analysis/text
python -m value_pipeline.supabase_sync backfill-historical \
  --start 2026-01-01 --end 2026-10-04
```

실행 전 Supabase의 `stocks`에 `035420`(네이버)과 `247540`(에코프로비엠)이 있어야 한다.
새 환경이면 `supabase/seed.sql`을 먼저 적용한다. 과거 적재가 끝난 뒤 Actions에서
`reset-live`를 한 번 실행하면, 과거와 중복되지 않는 새 Live 행부터 자동 수집을 이어간다.

## DART 재무 적재용 JSON

Supabase 테이블 합의 전에는 SQL 스키마를 고정하지 않고, 종목별 재무 스냅샷을
`financial` track JSON으로 내보낸다. 원시 DART 계정 전체는 저장하지 않으며 화면에서
설명하는 6개 지표와 계산 근거, 공시 식별자, 검증 결과만 보존한다.

```bash
cd backend
python -m analysis.text.value_pipeline.financial_run \
  --target 005930:삼성전자 --target 005380:현대차 \
  --target 035720:카카오 --target 068270:셀트리온 \
  --as-of 2025-12-30
```

기본 출력은 `backend/out/financial_tracks/<종목코드>_financial.json`이다.
스냅샷 upsert 후보 키는 `(ticker, as_of, fiscal_year)`, 지표 행 upsert 후보 키는
`(ticker, as_of, fiscal_year, metric_key)`다. `status=invalid`인 출력은 적재 전에
검토하고, `value=null`은 0으로 바꾸지 않는다. 적자 기업의 PER처럼 계산 자체가
성립하지 않는 값은 `note=negative_earnings`로 구분한다.

## 빅카인즈 뉴스 전처리

1. 종목별로 저장소 루트 `data/<6자리 종목코드>/` 디렉터리를 만들고 그 종목의 빅카인즈 원본
   엑셀을 둔다. 예: 삼성전자는 `data/005930/삼성전자_20220101-20221231.xlsx`.
   이 `data/`는 value_pipeline의 point-in-time 로더(`load_daily_news`)와 **공유하는 기준
   디렉터리**(`preprocess.DEFAULT_NEWS_DIR`)이며, 두 소비자 모두 `<기준>/<종목코드>/`를 먼저
   해석하므로 다른 종목 뉴스가 섞이지 않는다. 파일명은 `{회사명}_{YYYYMMDD}-{YYYYMMDD}.xlsx`
   (신규 `{종목코드}_{회사명}_{기간}`·레거시 `NewsResult_*.xlsx`도 인식), 종목 폴더 안은 재귀
   탐색하며 파일명에 적힌 기간은 커버리지 계산에 쓰지 않는다. 종목 폴더가 하나도 없으면
   기준 디렉터리 평면 구조로 폴백한다(구버전 호환).
2. `pip install -r analysis/text/requirements.txt`로 의존성을 설치한다.
3. 저장소의 `backend/` 디렉터리에서 실행한다.

```bash
python -m analysis.text.preprocess --ticker 005930 --out news_corpus.csv
```

`--ticker`와 같은 이름의 종목 디렉터리가 있으면 그 폴더만 읽어 한 CSV에 다른 종목이 섞이지
않는다. 종목 디렉터리가 하나도 없으면 기존처럼 기준 디렉터리 평면 구조를 읽는다(단일 종목).

상대 `--out` 경로는 `backend/analysis/text/data/processed/`를 기준으로 해석한다. 결과 CSV는
`news_id,date,title,body,press,ticker` 컬럼으로 고정되며, 실제 수록 기간과 뉴스가 0건인 날짜는
표준 출력 리포트에서 확인할 수 있다.

## 참고

- [BigKinds 뉴스 수집 방식 결정](../../../docs/decisions/bigkinds-acquisition.md)
- HuggingFace FinBERT (사전학습 금융 감성 모델)

### 2016~2026 전체 기간 추가 적재·재시작·검증

PR #186 이후 전체 기간은 아래 추가 적재 명령을 쓴다. 이미 준비된 6종목의
`historical` 부모 트랙(BigKinds/KR-FinBERT)이 필요하다. 부모 트랙이 없으면
placeholder를 생성하지 않고 해당 종목을 실패로 표시한다. 초기 트랙 등록은 위의 기존 2026 `backfill-historical` 명령 또는 검증된
`historical` JSON을 `backfill-news`로 적재하는 초기화 절차를 사용한다.
전체 기간 명령은 기존 부모의 **최근 정상 수집 창 요약**을 그대로 보존한다.
전체 기간의 시작·종료일과 연도별 행 수는 일별 테이블을 재조회한 `coverage.json`이 정본이다.

```bash
# 저장소 루트에서 .env의 Supabase 환경변수를 주입한 환경으로 실행
PYTHONPATH=backend .venv/bin/python -m analysis.text.value_pipeline.historical_backfill \
  --start 2016-01-01 --end 2026-10-04 --cache-dir backend/out/historical_backfill

# 적재 없이 실제 DB와 원본 범위만 재검증
PYTHONPATH=backend .venv/bin/python -m analysis.text.value_pipeline.historical_backfill \
  --start 2016-01-01 --end 2026-10-04 --cache-dir backend/out/historical_backfill --audit-only
```

동일한 명령을 재실행하면 DB의 완료 날짜와 월별 분석 캐시를 재사용한다.
`supabase_sync backfill-historical`는 신규 트랙 초기화용 기존 수집·upsert 동작을 유지한다.
기존 값 보존·재시작이 필요한 전체 기간 추가 적재에는 위 `historical_backfill` 명령을 쓴다.
로그는 종목/연도/월별 시작·성공·실패를 즉시 출력한다. 과거 추가 계산은
배치 크기 32를 고정한다(기존 트랙 수집 기본 16 유지). 분석 캐시는 원본 내용과
기존 CSV·모델명을 fingerprint로 확인하며, 기사 본문은 저장하지 않는다.
고유키 `(stock_code,track,sentiment_date)`·`(stock_code,track,news_id)`에
`ignore-duplicates`로 500행씩 추가한다. articles를 먼저 저장한 뒤 daily 행을
완료 표식으로 저장하고 DB에서 확인하므로 네트워크 실패 후에도 이어서 실행한다.
기존 historical 값·Live 전체는 덮어쓰거나 삭제하지 않는다.

재사용 순서는 DB 완료 날짜 → 기존 `data/processed/news_sentiment_daily*.csv`의
KR-FinBERT 일별 점수 → 없는 날짜만 기존 관련성 규칙과 KR-FinBERT로 계산이다.
기존 CSV는 2025년 말 일부만 있으며 당시의 관련 기사 수·평균을 그대로 쓴다.
CSV에 없는 표준편차는 null, 언론사 수는 0(기존 파일에 정보 없음)이며 임의로 추정하지 않는다.
CSV 재사용 날짜는 월별 캐시의 `reused_csv_dates`에 기록한다.

`coverage.json`은 아래를 분리한다.

- `source_missing_dates`: 파일명 다운로드 범위 밖. 원본 누락이지 0기사라고 판단하지 않는다.
- `database_missing_dates`: 원본 범위 안인데 DB 일별 행이 없음. 실제 적재 누락이다.
- `no_relevant_article_dates`: DB 일별 행이 있고 관련 기사 0건. 평균은 null이며 0점으로 만들지 않는다.
- `scored_days`·`article_count`: 점수 있는 날짜 수·채점 관련 기사 수. 원본 전체 기사 수가 아니다.

원본 범위는 파일명 규약으로 판정하므로 공급자 다운로드가 실제로 전수인지 보장하지 않는다.
삼성전자 2022년 파일은 `data/005930/삼성전자_20220101-20221231.xlsx` 위치에
추가하고 같은 명령을 재실행하면 된다. 2026년 현재 원본 종료일은 10월 4일이다.
