# value_pipeline 출력 검증 기준

> **대상**: 이 파이프라인을 수정하거나 출력을 데이터셋에 넣으려는 사람/에이전트.
> **상위 규칙**: `AGENTS.md` (아키텍처 원칙). 이 문서는 그 원칙을 value_pipeline에
> 적용한 **검증 절차**이며, 규칙 본문을 중복 정의하지 않는다.

행 하나라도 이 기준을 어기면 **데이터셋에 넣지 않는다.** 오염된 행 하나가 없는 것보다 나쁘다 —
없으면 결측으로 처리되지만, 오염된 행은 모델이 학습해버린다.

---

## 1. 실행

```bash
cd backend/analysis/text
python -m value_pipeline.run --ticker 005930 --name 삼성전자 --date 2022-06-15
```

**필수 `.env` 키**

| 키 | 필수 | 용도 |
|---|---|---|
| `DART_API_KEY` | **필수** | 재무제표. 없으면 exit 2 (재무 없이 시그널을 만들지 않음) |
| `GEMINI_API_KEY` | 선택 | 핵심 이벤트 추출·근거 문장 **(설명 텍스트 전용)**. 없으면 규칙 폴백 |

> `GEMINI_API_KEY` 유무는 **어떤 숫자도 바꾸지 않는다.** 바뀌면 그건 버그다
> (회귀 테스트: `test_scores_identical_with_and_without_llm`).

**환경변수**

| 변수 | 기본 | 의미 |
|---|---|---|
| `USE_FINBERT` | `1` | `0`이면 39단어 사전 폴백 — **데이터셋 구축 시 절대 금지** |
| `LLM_REPLAY_ONLY` | `0` | `1`이면 LLM 캐시 미스가 에러 — **백테스트 재생 시 반드시 `1`** |
| `SHARES_ASOF_YEAR` | `2025` | 발행주식수 스냅샷 기준연도(재현성 고정). 새 액면분할·대규모 증자 시 올리고 **데이터셋 재생성** — 낡으면 warning |

**종료 코드**

| 코드 | 의미 |
|---|---|
| 0 | 정상 + 검증 통과 |
| 2 | 재무 확보 실패 → 시그널 생성 거부 (`FinancialsUnavailableError`) |
| 3 | 실행은 됐으나 **검증 실패** → 이 행을 쓰지 말 것 |

출력: `out/{ticker}_{date}.json` (cwd 기준 `out/` 하위 — 저장소 트리에 산출물이
섞이지 않게 하며, `out/`은 .gitignore로 무시된다). `--out`으로 변경 가능.

### 1.1 기간 모드 (`--period`)

```bash
python -m value_pipeline.run --ticker 005930 --name 삼성전자 --period 2022-01   # 월
python -m value_pipeline.run --ticker 005930 --name 삼성전자 --period 2022      # 년
```

기간 전체를 요약한 `PeriodValueSignal` **1건**을 낸다 (`{ticker}_{period}.json`).
일별 행과 피처 축·점수 공식은 동일하고 집계 단위만 다르다.

| 축 | 규칙 |
|---|---|
| 뉴스 | 기간 내 날짜 순회, **빅카인즈 엑셀 전용**(네이버 폴백 없음). 관련성 필터 후 기사 단위 가중 집계 |
| 재무 | **기간 종료일 기준 point-in-time** — `collect_financials(ticker, period_end)` 재사용 |
| LLM | **아예 호출 안 함** — 핵심 이벤트도 규칙(감성 절댓값 상위). 기간 경로는 100% 결정론 |
| 감사 | `daily_metrics`(일별 행)만으로 기간 집계 재계산 가능. `days_covered`=워크북 커버 일수(결측 지시자) |

종료 코드·검증 규칙은 일별과 동일(재무 실패 exit 2, 검증 실패 exit 3).
확인: `test_period_pipeline.py` (`test_period_financials_use_period_end`,
`test_period_aggregates_are_article_weighted`, `test_period_signal_field_contract` 등)

### 1.2 대량 생성 (`value_pipeline.batch`) — 학습 데이터셋용

```bash
python -m value_pipeline.batch --ticker 005930 --name 삼성전자 \
    --start 2016-01-01 --end 2025-12-31 --out-dir out/005930
```

날짜 루프를 **한 프로세스**에서 돌린다(FinBERT 로드 1회, 워크북 파싱 캐시,
DART는 (종목, 사업연도)당 1콜·FDR은 종목당 1콜). **LLM은 강제 OFF** — 대량 생성이
무료 한도를 태우는 실수를 구조적으로 차단하며 숫자는 LLM 유무와 무관하다.
하루 실패는 기록 후 계속 진행하고, 요약은 `_manifest_*.json`에 남는다.
중단된 배치는 `--skip-existing`으로 재개. 단, 기존 산출물의 생성 조건(`_provenance.json`: 코드 버전·FinBERT 모델·설정)이
현재와 다르면 섞지 않도록 재개를 거부한다 — 새 디렉터리에 생성하거나 기존 파일을 지우고 다시 실행.

**학습용 피처 추출** — 모델(LightGBM)은 JSON을 직접 읽지 않고 `features.py`를 거친다.
무엇을 모델에 넣고 빼는지의 SSOT이며, 일별(ValueSignal)·기간(PeriodValueSignal)
모두 지원한다(혼입은 거부). 규칙은 네 가지다:

- `composite_score`·`value_investment_signal`·`confidence`는 **입력에서 제외**
  (다른 피처들의 고정 공식 조합 = 정보량 0. 화면 표시용으로만)
- **오염 행은 제외**: 회계 항등식 위배·룩어헤드·단위 오류·워크북 미커버 등
- **결측 행은 유지**: 실패 사유가 '관련 기사 0건'뿐이면 감성 파생 피처
  (`news_sentiment`·`news_impact_score`·`news_sentiment_std`·`news_staleness`)만
  NaN으로 두고 행은 살린다. 재무 피처는 유효하고, 기사 수는 0이 사실이다.
  → 조용한 날이 많은 소형주가 데이터셋에서 사라져 **대형주 편향**이 생기는 것을 막는다
  (실측: 에코프로비엠 2,467일 중 1,888일이 이 사유. 행을 버리면 579행만 남는다)
- 결측(None)은 NaN 유지 — 0 대치 금지 (LightGBM native 처리)

> '뉴스가 없었다'(결측, 유지)와 '보지 않았다'(워크북 미커버 = 수집 실패, 폐기)는
> 다르다. 후자는 무데이터인지 아닌지조차 알 수 없으므로 살리지 않는다.

```bash
python -m value_pipeline.features out/005930/*.json --out features_daily.csv
```

---

## 2. PASS/FAIL 기준

### 2.1 스키마 계약

최상위 키가 **정확히** 다음 21개여야 한다. 추가도 누락도 FAIL.

```
ticker, date, company_name,
news_sentiment, news_impact_score, news_sentiment_std, news_staleness,
key_events, article_count, article_count_raw,
financial_health_score, valuation_score, financial_metrics, financial_fiscal_year,
composite_score, value_investment_signal, confidence, reasoning,
news_source, financial_source, validation
```

**되살아나면 안 되는 필드**: `data_quality`, `sentiment_backend`, `llm_used`, `social_*`, `sentiment_divergence`

확인: `test_value_signal_field_contract`

### 2.2 결정론 — 가장 중요

**같은 입력을 두 번 돌리면 `reasoning`·`key_events`를 뺀 모든 값이 같아야 한다.**

```bash
python -m value_pipeline.run --ticker 005930 --name 삼성전자 --date 2022-06-15 --out /tmp/a.json
python -m value_pipeline.run --ticker 005930 --name 삼성전자 --date 2022-06-15 --out /tmp/b.json
diff <(jq 'del(.reasoning)' /tmp/a.json) <(jq 'del(.reasoning)' /tmp/b.json)   # 차이 없어야 함
```

> ⚠️ **반드시 `.env`에 `GEMINI_API_KEY`가 있는 상태로 확인할 것.**
> 키가 없으면 LLM 경로 자체가 안 돌아 검증이 무의미하다. 실제로 이 함정에 빠진 적이 있다 —
> `test_run_pipeline_is_deterministic`이 CI에서만 초록이었고(`.env` 없음), 로컬에선 계속 실패했다.
> 테스트는 `agents.structured`를 patch해서 헤르메틱하게 만들었다. 환경변수 patch로는 안 된다:
> `config.load_dotenv()`가 import 시점에 `.env`를 주입하고, `SETTINGS`는 frozen dataclass,
> `get_llm()`은 `lru_cache`라 무력하다.

확인: `test_llm_text_cannot_change_any_score`, `test_run_pipeline_is_deterministic`

### 2.3 Point-in-time (룩어헤드 없음)

| 검사 | 기준 |
|---|---|
| `financial_fiscal_year` | `collectors.select_fiscal_year(date)`와 일치. `date`가 4/1 이후면 `date.year - 1`, 이전이면 `date.year - 2` |
| 뉴스 날짜 | 모든 기사가 기준일 당일 (`validation_agent`가 자동 검사) |
| staleness 비교군 | 기준일 **이전** 기사만 (`collect_prior_news`) |

근거: 사업보고서 법정 제출기한은 사업연도 종료(12/31) 후 90일 → 익년 3/31. 따라서 4/1부터
직전 사업연도 보고서가 공시돼 있다.

**실제로 났던 사고**: `_fetch_dart_financials`가 `date`를 무시하고 `dt.date.today().year - 1`을
써서, 2022-06-15 요청에 **FY2025 재무 + 2022년 주가**를 섞었다(4년 룩어헤드). `roe: 0.1036`이
삼성전자 FY2022 실제값(≈0.157)이 아닌 것이 증거였다. 수정 후 `roe: 0.1309` = FY2021 실제값.

확인: `test_select_fiscal_year_is_point_in_time`, `test_select_fiscal_year_does_not_depend_on_today`,
`test_fetch_dart_financials_uses_point_in_time_fiscal_year`, `test_validation_catches_lookahead_fiscal_year`

### 2.4 자기감사 (화이트박스)

**행 안의 모든 숫자를 그 행만 보고 재계산할 수 있어야 한다.** 이게 화이트박스 원칙의 구체적 형태다.

```
composite  = clip(valuation_score*0.6 + financial_health_score*0.4
                  + news_sentiment*(news_impact_score/10)*2, 0, 10)
signal     = band(composite)   # 8.0↑ STRONG_BUY, 6.5↑ BUY, 4.5↑ HOLD, 3.0↑ SELL, 그 외 STRONG_SELL
confidence = clip(0.5 + 0.125*real_sources - 0.15*news_sentiment_std
                  + 0.2*|composite-5|/5, 0.2, 0.95)
             # real_sources = news_source, financial_source 중 'sample'이 아닌 개수
```

계산값과 출력이 다르면 FAIL. `news_impact_score`·`article_count`를 출력에 남기는 이유가 이것이다 —
빼면 재계산이 불가능해진다.

확인: `test_row_is_self_auditing`

### 2.5 출처 (HITL: 근거·출처 항상 표시)

| 필드 | 기대값 | 아니면 |
|---|---|---|
| `news_source` | `bigkinds` | `naver*`는 과거 날짜 조회가 불안정하고 `news_id`가 없어 그라운딩이 안 된다 → 백테스트엔 부적합 |
| `financial_source` | `dart` | `sample`이면 **FAIL** — `sample_data/`는 존재하지 않으므로 이 값이 나오면 코드가 거짓말을 하는 것 |
| `key_events[].news_ids` | 비어있지 않음 | 비면 출처 없는 이벤트 = 환각 의심 (`validation.warnings`에 기록됨) |

**워크북 경로 규약** — `build_news_corpus`(CSV 코퍼스)와 `load_daily_news`(하루치)가 **같은
디렉터리·같은 파일명 규약**을 본다. 규약이 갈리면 한쪽만 파일을 못 찾고 조용히 네이버로
폴백해 오염된 행이 나온다(PR #22 블로커1).

```
<repo>/data/{종목코드}_{회사명}_{YYYYMMDD}-{YYYYMMDD}.xlsx   ← 정본
<repo>/data/{회사명}_{YYYYMMDD}-{YYYYMMDD}.xlsx              ← 구버전(호환)
NewsResult_*.xlsx                                            ← 레거시(종목 필터 불가)
```

워크북을 **찾았는데** 그날 기사가 0건이면 그것이 사실이므로 네이버로 폴백하지 않는다.
워크북 자체가 없을 때만 폴백하며, 이때 경고가 뜬다 — 백테스트 중 이 경고가 보이면 FAIL이다.

### 2.6 값 범위

| 필드 | 범위 |
|---|---|
| `news_sentiment` | [-1, 1] |
| `news_impact_score` | [1, 10] 정수 |
| `news_sentiment_std` | ≥ 0 |
| `news_staleness` | [0, 1] |
| `financial_health_score`, `valuation_score`, `composite_score` | [0, 10] |
| `confidence` | [0.2, 0.95] |
| `value_investment_signal` | STRONG_BUY / BUY / HOLD / SELL / STRONG_SELL |
| `article_count` | > 0 (0이면 FAIL — 2.8 참조) |

### 2.7 감성 백엔드 — 런 간 혼용 금지

**KR-FinBERT와 39단어 사전 폴백은 점수 스케일이 비교 불가능하다.** 여러 런을 모아 데이터셋을
만들 때 섞이면 조용한 regime break가 생긴다. 출력에 백엔드가 안 남으므로(피처로 무의미해서 뺐다)
**런 단위로 고정하고 기록할 것.**

```python
from value_pipeline.sentiment import score_texts
_, backend = score_texts(["삼성전자 실적 개선"])
assert backend == "kr-finbert"   # 데이터셋 구축 전 필수 확인
```

`torch`/`transformers` 미설치 시 조용히 lexicon으로 폴백한다. `requirements.txt`에 필수로 넣은 이유다.

### 2.8 결측 vs 0 구분

`news_sentiment == 0.0`은 **'중립'과 '기사 없음' 둘 다**를 의미한다 — `aggregate([])`가 `(0.0, 0.0)`을
반환하기 때문이고, `news_sentiment_std`도 양쪽 0.0이다. `article_count`만이 둘을 구분한다.

- `article_count == 0` → **FAIL.** `news_sentiment=0.0`은 관측이 아니라 날조다.
- 재무 지표 전부 결측 → **FAIL.** 점수가 기본값으로 채워진 것이다.

**관련성 필터가 전부 걸러도 전량 복원하지 않는다.** 복원하면 '무관 기사로 만든 감성'이 정상
행처럼 보인다 — 이 문서가 금지하는 바로 그 패턴이다(PR #22 블로커3). `article_count=0`으로
두고 검증에서 실패시킨다. 이 경우 `article_count_raw`가 0인지 확인할 것: 0이면 그날 기사가
없는 것이고, 0이 아니면 **회사명 키워드가 잘못된 것**이다.

**실제로 났던 사고**: 재무 결측 시 `valuation_score`가 3.0(결측을 적자로 오인) · `health_score`가
5.0 → composite 3.8 → **confidence 0.548의 `SELL`과 그걸 정당화하는 유창한 LLM 근거문**이 나왔다.
중립 HOLD가 아니라 그럴듯한 가짜 매도 신호였다.

확인: `test_validation_catches_zero_articles`, `test_valuation_missing_data_is_not_treated_as_loss`,
`test_zero_relevant_articles_fails_validation_not_restored`

### 2.9 validation 블록

`validation.ok == false`면 **행을 쓰지 말 것** (run.py가 exit 3). `validation.warnings`는 치명적이진
않지만 확인 후 넘어갈 것.

`validation_agent`가 검사하는 것:

| # | 검사 | 잡는 버그 |
|---|---|---|
| 1 | 회계 항등식 `자산 ≈ 부채 + 자본` (허용오차 0.5%) | `_DART_MAP`이 first-wins라 **연결(CFS)/별도(OFS) 재무제표 혼입** 가능 — 이걸 잡는 유일한 검사 |
| 2 | 시가총액 상식 범위 (1e9~1e16원) | 발행주식수·주가 단위 오류. `per×eps≈price` 같은 검사는 **동어반복**이라 쓰지 말 것 — `compute_metrics`가 `per=price/eps`로 계산하므로 항상 참이다 |
| 3 | 지표 상식 범위 | `_band`가 **조용히 saturate**한다 — PER 300만이 나와도 최저 점수만 줄 뿐 거부하지 않는다. **하한도 중요**: 발행주식수 과소 → EPS 폭증 → PER이 0에 수렴 |
| 4 | 파생 정합성 (유동자산 ≤ 자산총계 등) | `_altman_z`가 결측을 `0.0`으로 강제(`or 0.0`)해 Z를 조용히 과소평가 |
| 5 | 뉴스 날짜 정렬 | point-in-time 위반 |
| 6 | 회계연도 vs 기준일 | 룩어헤드 |
| 7 | 결측 vs 0 | 2.8 |
| 8 | 이벤트 그라운딩 | LLM 환각 (warning) |
| 9 | 과대 필터 (10% 미만 잔존) | 관련성 필터 오작동 (warning) |
| 10 | 상한 유실 | 관련 기사가 임의로 버려짐 (warning) |

---

## 3. 금지 패턴

이 코드베이스에서 아래를 발견하면 **고치고 회귀 테스트를 추가할 것.**

### 3.1 LLM이 점수 경로에 개입

AGENTS.md: *"점수 산출은 100% 결정론(같은 입력→같은 출력). LLM은 설명 텍스트 생성에만."*

원칙 문제만이 아니다. **LLM은 이미 그 뉴스를 읽었고 그 다음에 주가가 어떻게 됐는지도 안다.**
Gao·Jiang·Yan (2025)은 LLM 예측의 룩어헤드를 Lookahead Propensity로 측정했는데, 블룸버그
헤드라인 → 익일 수익률에서 **명백한 알파의 약 37%가 암기(memorization)**였다. 학습 컷오프 이후
구간에선 그 효과가 통계적으로 사라졌다(플라시보 테스트). 삼성전자는 한국 대형주라 LAP가 최대다.

**그리고 캐싱·그라운딩·NLI 어느 것도 이걸 못 막는다.** 캐시는 유출된 예측을 완벽히 재현
가능하게 만들 뿐이고, 그라운딩은 유출된 추론이 실제 문장을 인용한다고 확인해줄 뿐이다.
**재현 가능한 것과 타당한 것은 다르다.** 환각은 잡음이라 백테스트를 나쁘게 만들지만, 암기는
in-sample에만 존재하는 신호라 백테스트를 좋아 보이게 만들고 실전에서 사라진다.

**"라벨은 점수가 아니다"는 궤변이다.** 어떤 기사를 채점할지 LLM이 정하면 점수가 LLM에
의존한다. 실측으로 확인됐다: 같은 날 같은 기사에서 필터만 바꿔 감성이 +0.0429 → −0.046으로
바뀌었다. 이 프로젝트는 그래서 관련성도 규칙으로 판정한다(§4.1).

**구조적 방어**: `_NewsExtract`·`_Reason` 어느 스키마에도 **점수 필드도, '어떤 기사를 쓸지
고르는 필드'도 두지 말 것.** LLM 출력 계약에 그런 필드가 없으면 실수로 다시 연결할 수 없다.
확인: `test_llm_schemas_have_no_score_or_selection_field`, `test_scores_identical_with_and_without_llm`

### 3.1.1 LLM 설명이 행동을 제안

`reasoning`은 수치와 핵심 이벤트의 관계만 번역한다. 매수·매도·보유·관망·진입·청산,
비중 조절, 손절·익절을 권하거나 제안하면 HITL 원칙 위반이다. 프롬프트 금지에만 의존하지 않고
`_contains_behavior_advice`가 명시 패턴을 검출하면 결정적 수치 템플릿으로 대체한다. 기사 사실인
"외국인 매도 압력"처럼 사용자의 행동을 제안하지 않는 문장은 허용한다.

확인: `test_synthesis_rejects_behavior_advice`, `test_synthesis_allows_factual_action_word`

### 3.2 `today()` 기반 회계연도

`dt.date.today()`가 재무·뉴스 선택에 등장하면 룩어헤드다. 기준일 `date`에서 파생할 것.

### 3.3 결측을 값으로 취급

`per is None`을 적자로 단정하기, `else 5.0` 기본값으로 조용히 메우기, `or 0.0`으로 결측을 0으로
강제하기. 결측은 결측으로 전파하고 검증에서 잡아라.

### 3.4 예외 조용히 삼키기

`except Exception: pass` / `data = None`. 최소한 `warnings.warn`. DART 실패가 완전히 보이지 않아
가짜 SELL이 나온 원인이었다.

### 3.5 LLM 크리틱으로 검증

**검증자를 LLM으로 만들지 말 것.** Huang et al. (ICLR 2024): 외부 피드백 없는 자기교정은
모든 벤치마크에서 성능을 떨어뜨렸다 — GSM8K 75.9→74.7, **CommonSenseQA 75.8→41.8**.
멀티에이전트 토론(83.2%)이 단순 self-consistency(85.3%)보다 못했다. LLM 판사는 자기 출력에
유리한 건 94.5%, 불리한 건 42.5%만 맞힌다. 원인은 **저perplexity(친숙한) 텍스트 선호**라
매끄러운 보도자료를 어색하지만 진짜 새로운 기사보다 높게 친다 — 원하는 신호의 정반대다.

자기교정이 실제로 작동하는 경우는 **외부 피드백**(도구·규칙·검증기)뿐이다. 그래서
`validation_agent`는 100% 규칙 기반이다.

### 3.6 벡터 DB / RAG를 같은 날 기사에

**실측**: 최악의 날(2022-10-27, 182건)이 본문 포함 **58k 토큰**. `gemini-2.5-flash` 컨텍스트는
**1M** — 6%다. 한 달 전체(1,798건 ≈ 620k)도 들어간다. 빅카인즈가 본문을 200자로 잘라줘서
청킹 문제조차 없다. 벡터 DB는 `torch`+임베딩 모델+faiss/chromadb를 끌고 와서 **컨텍스트에
통째로 들어가는 걸 골라낸다.** 오버엔지니어링이다.

시간축 검색(직전 기사 대비 신선도)은 다르며, 그건 `staleness.py`가 TF-IDF 없이 단어 중복률로 한다.

---

## 4. 설계 근거 — 왜 이렇게 돼 있나

측정으로 결판난 것들이라, 바꾸려면 재측정부터 할 것.

### 4.1 관련성 필터는 필요하지만, LLM이면 안 된다

빅카인즈 키워드 검색이라 무관 기사가 섞이고, **그게 감성 부호를 뒤집는다.**
2022-06-15(삼성전자 52주 신저가일) 실측:

| | 건수 | 감성 |
|---|---|---|
| 필터 없음 | 73 | **+0.0191** ← 긍정 (틀림) |
| `'삼성' in 제목+본문` | 37 | **−0.0189** ← 부정 (맞음) |

범인은 `구미대-희망디딤돌 업무협약`(+1.000), `제일기획 NFT`(+0.995), `두산 반도체 투자`(+0.985),
`미래에셋 ELW 상장`(+0.976), `[공개] 오늘 아침 "폭등 예정" 종목 공개합니다` 리딩방 스팸.
FinBERT 판정은 **전부 맞다** — 삼성전자 기사가 아닐 뿐이다.

**그런데 필터가 LLM일 필요는 없다.** 2022년 6일 표본:

| 비교 | 평균 절대차 |
|---|---|
| 필터없음 vs LLM | **0.1160** |
| **규칙 vs LLM** | **0.0337** (상관 **0.9901**, Jaccard 0.87, 부호 불일치 **0/6일**) |

필터 유무는 3.4배 더 중요하고, 어떤 필터냐는 거의 차이가 없다. **라벨이 채점 대상을 정하면
그건 곧 점수를 정하는 것**이므로(PR #22 블로커), 관련성은 결정론 규칙으로 하고 LLM은 점수
경로에서 완전히 뺐다. 캐시로 재현성을 보장한다는 건 첫 출력의 재현일 뿐, 환경이 바뀌거나
캐시가 재생성되면 피처가 통째로 흔들린다.

**키워드는 `삼성전자`가 아니라 `삼성`이다**(`relevance_key`가 법인격 접미사를 뗀다).
제목에 `삼성전자`를 그대로 박는 기사는 폭락일엔 대부분 주가 기사라, 그것만 남기면 10건에
감성 **−0.80**으로 편향된다. ASML·롤러블폰 기사는 `삼성`이라고만 쓴다. 게다가 주가 기사로
감성을 만들면 **이미 일어난 주가 움직임의 메아리**를 피처로 쓰는 순환이 된다.

반면 **본문 200자 중간 절단은 감성에 영향이 없다**: 2022 전수 19,549건 중 82.4%가 문장 중간에
끊기지만, FinBERT raw vs 완전문장-트리밍 **상관 0.9995**, 평균 절대차 0.0047. 제목+본문 최대
324자로 FinBERT 창(512토큰≈340자)에 **100% 들어간다**(초과 0건). 그래서 LLM 요약은 하지 않는다 —
231자를 압축하는 게 아니라 버리는 것이고, 잘린 서술어는 LLM도 모르므로 극성을 **지어낼**
(=메모리제이션 오염) 위험만 있다.

### 4.1.1 그래서 LLM은 지금 뭘 하나

`_extract_events` (하루치 배치 1콜) + `_Reason` (근거 문장 1콜). **둘 다 사람이 읽는 텍스트이며
어떤 숫자에도 안 쓰인다.** LLM이 사는 값은 같은 사건 기사들을 묶는 것이다 — 2022-06-15에
ASML 관련 기사 8건이 `'이재용 부회장, 네덜란드 총리 및 ASML 경영진 만나 반도체 장비 공급 협력
논의'` 한 줄이 된다. 규칙 폴백은 중복 헤드라인 5개를 줄 뿐이다.

`key_events`는 `list[KeyEvent]`라 LightGBM이 못 먹는다. **모델용 피처가 아니라 HITL 근거**다
(각 이벤트에 출처 `news_id`가 붙어 사용자가 원문을 확인할 수 있다).

### 4.1.2 6종목 실시간 관련성 검증 (`live-context-v3-subject-industry-market`)

삼성전자·현대차·카카오·네이버·셀트리온·에코프로비엠 NewsAPI.ai 실시간 트랙은
`news_relevance.classify_live_relevance`의 명시 규칙을 적용한다. 과거 BigKinds
필터와 6종목 이외의 실시간 필터는 유지한다. 적용 범위는
`CONTEXTUAL_LIVE_COMPANIES`에 기록한다. 회귀 테스트는 동작 검증이며
실제 기사에서의 정확도·재현율 검증을 대체하지 않는다. 스키마·Supabase 계약은 변경하지 않는다.

| 분류 | 집계 | 판정 근거 |
|---|---|---|
| `direct` | 포함 | 대상 기업의 구체적 사업·서비스·대응이 주요 주제 |
| `indirect` | 포함 | 대상 기업이 참여하는 공급 계약·파업·공동사업 등 인과 근거 |
| `industry` | 포함 | 대상 산업 전반의 업황·수요·정책·규제 변화가 주요 주제 |
| `market` | 포함 | 시장 전체의 지수·금리·환율·수급 변화가 주요 주제 |
| `irrelevant` | 제외 | 타사 개별 소식·계열사만의 소식·판매처 단순 언급·명백한 무관 주제 |
| `review` | 집계 보류 | 본문 누락·짧은 발췌·미등록 주체·주제 근거 불충분 |

같은 산업의 경쟁사 개별 뉴스는 제외한다. 다른 회사가 함께 등장해도 대상 기업의
구체적 대응·계약이 주요 내용이면 유지한다. 키워드 단독 일치나 회사명 나열만으로
통과시키지 않는다. 명시 규칙으로 확정하지 못하면 무관 판정 대신 보류한다.
운영 INFO 로그에는 정책 버전과 기업별 판정 건수, 포함 분류별 기사 수·감성 평균을 남긴다.
분류별 통계는 내부 검증용이며 종합 평균 산식이나 결과 track 필드를 바꾸지 않는다. DB 스키마는 바꾸지 않는다.

`현대차증권`은 `현대차` 이름 충돌로 인정하지 않는다. 관련기사 위젯 이후
본문은 관련성 입증에 쓰지 않는다. 제목에 현대차가 없어도 실제 신차·판매·공장
내용이 있으면 유지하며, 소수점·날짜의 마침표로 사업 근거가 끊기지 않게 한다.
관련 기사 0건을 무관 기사로 복원하거나 중립 관측으로 저장하지 않는다.

검토 도구: `python -m value_pipeline.relevance_review --help`.
Supabase 메타데이터와 공급자 기사 상세 입력을 같은 ID로 연결하여 기존·신규
규칙의 포함 여부를 비교한다. 별도 JSON·Markdown에 정책 버전, 통과/제외 규칙,
본문 입력 해시, 사람 확인 빈칸을 남기고 본문은 저장하지 않는다. 본문 누락·제목
변경·중복 ID·잘못된 점수·불완전 라벨은 검토 실행 실패로 처리한다.

평가 시 반드시 구분할 것:

- 저장 감성점수 재집계는 필터의 **민감도 분석**이며 KR-FinBERT 재추론이 아니다.
- 본문 재조회는 원래 수집 시점 입력과 다를 수 있다. 재조회 시각과 해시를 기록한다.
- 에이전트 잠정 라벨은 사람 정답이 아니다. 이를 감성 정확도·사람 일치율로 보고하지 않는다.
- 이미 통과한 86건만으로 기존 필터가 놓친 뉴스까지 포함한 전체 재현율을 계산할 수 없다.
- 규칙 기반 기업 활동 판정도 완전하지 않다. 특히 `indirect`의 전체 기사 감성은
  다른 기업의 평가가 섞일 수 있으므로 직접·간접 분류를 사람이 함께 검토한다.

회귀 테스트: `tests/test_live_news_relevance.py`, `tests/test_relevance_review.py`.
오늘 표본과 같은 날에 규칙을 조정했으므로 다른 날짜·종목의 별도 표본 검증 전
일반화 성능이 확보됐다고 주장하지 않는다.

### 4.2 결정론은 모델이 아니라 인터페이스 경계에서 확보한다

`temperature=0`으로도 LLM은 결정론이 아니다 — 서버가 함께 배치하는 요청 수에 따라 커널 결과가
달라지고(batch invariance) 이건 통제 밖이다. 그래서 `llm.structured`가 content-hash로 출력을
동결한다. 캐시 키에 프롬프트·모델·스키마·파라미터를 **전부** 넣어야 한다 — 프롬프트가 빠지면
프롬프트를 고쳐도 옛 답이 나오는 조용한 staleness가 생긴다.

프롬프트를 수정하면 `llm.PROMPT_VERSION`을 올릴 것.

**재생 중 캐시 미스는 하드 에러여야 한다**(`LLM_REPLAY_ONLY=1`). 캐시를 '속도 최적화'로 취급해
미스 시 조용히 LLM을 부르면 재생은 더 이상 결정론이 아니다.

부수 효과: 독점 모델은 은퇴하고, 은퇴한 모델의 출력은 복구 불가능하다. 몇 달 뒤 심사에서
방어해야 하는 산출물엔 캐시가 최적화가 아니라 **생존 조건**이다.

### 4.3 staleness는 Tetlock을 근사하는 게 아니라 그대로 구현한 것

Tetlock (2011), RFS 24(5): staleness = **직전 10건 기사와의 단어 중복률**. 주가는 stale news에
덜 반응하지만, stale news 당일 수익률이 **다음 주 수익률을 음(-)으로 예측**한다(반전). 개인투자자가
stale news에 더 공격적으로 거래하고, 개인 비중이 높은 종목일수록 반전이 크다.

행동재무학 논지에 직결된다 — 개인의 과잉반응이 일시적 가격 왜곡을 만든다는 게 결론이다.
임베딩을 안 쓰는 이유: 단어 중복률은 비전공자에게 두 기사를 나란히 보여주며 "이 뉴스의 82%가
3일 전 기사와 겹칩니다"라고 설명할 수 있다. 임베딩 코사인 0.87로는 못 한다.

---

## 5. 회귀 테스트 대응표

`pytest backend/analysis/text/ -v` (repo root). **`.env`가 있는 상태에서도 초록이어야 한다** —
CI엔 `.env`가 없어 헤르메틱성을 못 잡는다.

| 기준 | 테스트 |
|---|---|
| 2.1 스키마 계약 | `test_value_signal_field_contract` |
| 2.2 결정론 | `test_llm_text_cannot_change_any_score`, `test_scores_identical_with_and_without_llm`, `test_run_pipeline_is_deterministic`, `test_relevance_is_deterministic_without_llm` |
| 2.3 point-in-time | `test_select_fiscal_year_is_point_in_time`, `test_select_fiscal_year_does_not_depend_on_today`, `test_fetch_dart_financials_uses_point_in_time_fiscal_year`, `test_validation_catches_lookahead_fiscal_year`, `test_validation_catches_misaligned_news_date` |
| 2.4 자기감사 | `test_row_is_self_auditing` |
| 2.5 출처 | `test_key_events_carry_source_news_ids`, `test_grounding_requires_two_token_overlap`, `test_load_daily_news_emits_news_id_for_grounding`, `test_validation_warns_on_ungrounded_event`, `test_corpus_and_daily_loader_share_path_contract`, `test_corpus_workbooks_filter_by_ticker` |
| 2.8 결측 vs 0 | `test_validation_catches_zero_articles`, `test_zero_relevant_articles_fails_validation_not_restored`, `test_valuation_missing_data_is_not_treated_as_loss`, `test_collect_financials_raises_when_no_data` |
| 2.9 validation | `test_validation_passes_on_consistent_data`, `test_validation_catches_accounting_identity_violation`, `test_validation_catches_implausible_metric`, `test_validation_result_reaches_output` |
| 3.1 LLM 점수·행동 개입 | `test_llm_schemas_have_no_score_or_selection_field`, `test_scores_identical_with_and_without_llm`, `test_synthesis_rejects_behavior_advice`, `test_synthesis_allows_factual_action_word` |
| 4.1 관련성 필터 | `test_relevance_key_strips_corporate_suffix`, `test_relevance_filter_excludes_unrelated_articles`, `test_relevance_filter_matches_body_not_just_title`, `test_relevance_filter_keeps_all_when_company_unknown` |
| 4.3 staleness | `test_staleness_identical_article_is_fully_stale`, `test_staleness_new_article_is_fresh`, `test_staleness_is_deterministic`, `test_published_at_sorts_by_time_not_press_code`, `test_collect_prior_news_returns_latest_first` |

---

## 6. 알려진 한계 (문서화만, 미해결)

발표·리뷰에서 먼저 밝힐 것. 숨기면 신뢰를 잃고, 밝히면 오히려 점수를 얻는다.

1. **빅카인즈 20,000행 export 상한.** 삼성전자는 연 20,000건을 넘는 해가 많아 1년 단위로
   받으면 **최신순 정렬 때문에 연초가 잘린다.** 2022 파일(19,549건)만 우연히 온전하다.
   6개월 단위로 나눠 받을 것. `find_news_workbook`은 **파일명만** 보고 판단하므로
   잘린 파일도 커버한다고 주장한다 — 파일을 새로 받으면 실제 최소/최대 일자를 직접 확인할 것.
2. **DART 정정공시.** DART는 해당 사업연도의 *최신 정정본*을 반환하므로, 기준일 이후 제출된
   정정공시는 여전히 새어든다. `select_fiscal_year`는 보고서 **연도**만 통제한다(2차 오차).
3. **LLM 메모리제이션.** 3.1 참조. 점수 경로에서 LLM을 완전히 뺐으므로 **피처에는 노출이
   없다.** 다만 `key_events`·`reasoning`은 여전히 LLM 산출이라, 발표에서 그 텍스트를 인용할 때
   "모델이 결과를 알고 쓴 문장"일 수 있음을 감안할 것. **모델 학습 컷오프와 백테스트 구간을
   함께 명시할 것.**

6. **관련성 규칙의 한계.** `'삼성' in 제목+본문`은 계열사 기사(제일기획 등)와 '삼성'이 스쳐
   지나가는 시황 기사를 걸러내지 못한다(실측 LLM 대비 Jaccard 0.87). 감성 영향은 평균 0.034로
   작지만, 종목을 늘릴 때 키워드가 흔한 단어면(예: 'CJ', 'GS') 오탐이 커질 수 있다.
   `relevance_key`를 종목별로 검증할 것.
4. **`_DART_MAP` 미매핑 항목.** `operating_cashflow`, `interest_expense`, `cash`, `ebitda`가
   매핑에 없어 `interest_coverage`는 DART 경로에서 **항상 결측**이고 `ev_ebitda`는 영업이익으로
   근사한다(둘 다 `FinancialMetrics`에서 제외되므로 출력엔 영향 없음).
5. **업종 평균 PER/PBR 부재.** `sector_per`/`sector_pbr`은 `sample_data/`에서 오는데 그 디렉터리가
   없어 항상 `None` → `valuation_score`가 절대 기준 밴드로 계산된다. 동종업계 대비가 아니다.
7. **발행주식수는 스냅샷 기준연도(`SHARES_ASOF_YEAR`, 기본 2025) 공시 기준.**
   FDR 주가가 액면분할 소급수정(adjusted)이라, 보고서 연도의 주식수(분할 전 단위)를
   곱하면 시총이 분할 배수만큼 왜곡된다(실사고: 삼성 50:1 → 2017년 행 per 0.28,
   검증 통과). 그래서 주식수만은 스냅샷 연도 공시 값을 쓴다 — 수정주가와 같은 분할
   기준이고, 주식수는 시그널이 아니라 단위 환산자다. 기준연도를 today()가 아니라
   고정값으로 두는 이유는 재현성이다(실행 연도가 바뀌어도 같은 출력) — 사업연도는
   point-in-time을 지키면서 주식수는 스냅샷을 쓰는 **의도된 비대칭**이며, 스냅샷
   연도가 낡으면 warning이 난다.
   **잔여 오차**: 이후 자사주 소각·증자분(삼성 2017~18 구간 per가 실제 대비 ±20% 수준).
   또한 FY2015 주식총수는 DART 응답에 값이 없어('-'), 과거엔 그 구간 per/pbr가 통째로
   결측이었다 — 최신 기준으로 바꾸며 함께 해소됐다.
