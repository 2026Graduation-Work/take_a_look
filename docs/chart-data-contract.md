# 차트 데이터 규격 (화면이 읽는 것)

화면(`frontend/`)이 차트 서빙 결과에서 **실제로 읽는** 테이블·뷰·payload 경로만 정리했다. 모델을 바꿀 때(진세)와 서빙을 넘겨받을 때(성우) 이 표를 기준으로 쓴다. 모든 항목은 2026-10-14 `main` 코드에서 확인했다.

- payload 전체 규격: `backend/analysis/chart/serving/contracts/chart_signal_detail_v2.schema.json`(`contract: "chart_signal_detail_v2"`)
- 테이블·뷰 정의: `supabase/migrations/0007_chart_signal_detail_v2.sql`, `0013_supply_demand.sql`, `0014_stock_volatility.sql`
- 화면 쪽 검증: `frontend/lib/chart-public.ts`의 `parseChartSnapshot`. 하나라도 어긋나면 종목 상세는 오류 안내와 "다시 시도"를 띄운다

## 1. 읽는 곳 한눈에

| 테이블·뷰 | 화면에서 읽는 코드 | 화면 | 쓰는 곳(서빙) |
|---|---|---|---|
| `latest_chart_signal_snapshots`(뷰: 마지막 `published` 배치의 스냅샷) | `chart-public.ts` `loadPublicCharts` | 종목 상세 전체 | `serving/internal/storage.py` `publish`(→ `chart_signal_snapshots`) |
| 〃 (H20 경로만) | `strong-signals.ts` `loadStrongSignals` | 대시보드 "오늘 신호가 강한 종목" | 〃 |
| 〃 (H20 경로만) | `latest-closes.ts` `loadLatestCloses` | 보유 맵·관심 종목 신호, 평가금액 종가 | 〃 |
| 〃 (H20 경로만) | `providers/supabase-insights.ts` `loadSupabasePsychology` | 시장 분위기 탭 "가격 흐름 분위기" | 〃 |
| `chart_batches` + `chart_signal_snapshots` | `daily-changes.ts` `loadDailyChanges` | 대시보드 "어제와 달라진 근거" | `storage.py` `publish` |
| `market_status` | `market-status.ts` | 시장 바 | `serving/internal/market.py` `market_status_row` → `storage.py` `upsert_market_status` |
| `supply_demand` | `providers/supabase-insights.ts` `loadSupabaseSupply` | 사고판 주체 탭 | `serving/supply.py` |
| `stocks` | `strong-signals.ts`, `queries.ts`(`STOCK_COLUMNS`) | 강한 신호 거르기·위험도 | `serving/stock_master.py` |

## 2. `latest_chart_signal_snapshots` 행·payload

행 키: `batch_id`, `stock_code`(`^[0-9A-Z]{6}$`), `horizon`(5 또는 20), `payload`(jsonb).

| 경로 | 타입 | 필수 | 없거나 어긋날 때 화면 | 만드는 곳 |
|---|---|---|---|---|
| `batch_id`(행) | text | 필수 | 여러 값이 섞이면 상세 오류("서로 다른 차트 배치") | `pipeline.py` `build_batch` |
| `horizon`(행) | 5·20 | 필수, 종목당 둘 다 | 하나라도 없으면 상세 오류("두 기간의 차트가 모두 준비되지 않았어요") | `build_batch` |
| `payload.contract` | `"chart_signal_detail_v2"` | 필수 | 상세 오류 | `serving/internal/snapshot.py` `build_snapshot` |
| `payload.stock_code` · `batch_id` · `horizon` | 행과 같은 값 | 필수 | 상세 오류 | `build_snapshot` |
| `payload.profile` | H5=`aggressive`, H20=`stable` | 필수 | 상세 오류 | `build_snapshot` |
| `payload.stock_name` | 빈 문자열 아님 | 필수 | 상세 오류. 강한 신호 목록은 없으면 종목코드로 표시 | `build_batch`(유니버스 이름) |
| `payload.data_asof` | `YYYY-MM-DD` | 필수, 모든 행 같은 날 | 섞이면 상세 오류. 보유 맵·강한 신호·출처 줄의 기준일 | `build_snapshot` |
| `payload.release_id` · `pack_id` | 빈 문자열 아님 | 필수 | 상세 오류. `pack_id`는 "어제와 달라진 근거"가 모델 교체 여부를 볼 때 씀 | `build_snapshot` |
| `payload.inference.status` | `available`·`unavailable` | 필수 | `unavailable`이면 신호 "미제공", 보유 맵에서 빠지고 강한 신호에서 빠짐 | `build_batch` / `unavailable_snapshot` |
| `payload.inference.scores` | `{down, neutral, up}` 0~1, 합 1(±1e-6) | `available`이면 필수 | 상세 오류. 가장 큰 값이 방향(`chart-detail.ts` `inferenceDirection`) | `inference.py` `infer_batch` |
| `payload.inference.contribution_space` | `class_0/1/2_raw_margin` | 필수 | 상세 오류. "모델이 본 이유"의 대상(하방·중립·상방) | `build_batch` |
| `payload.inference.features[]` | `{name, label_ko, meaning_ko, value(number\|null), contribution}` | 필수(빈 배열 허용) | 비면 "모델이 본 이유"에 "이 예측에 연결된 근거 데이터가 없어요" 안내. 화면 이름은 `featureLabels.ts`가 `name`으로 다시 붙임. `[0].label_ko`·`[0].name`은 강한 신호 "가장 크게 본 것" | `infer_batch`(\|기여\| 큰 순 상위 5개) |
| `payload.inference.contribution_abs_sum` | number ≥ 표시 피처 \|기여\| 합 | 선택 | 없으면 크기 말 대신 방향만 표시. 어긋나면 상세 오류 | `infer_batch` |
| `payload.inference.close` | number > 0 | 선택(H20) | 없으면 보유 평가금액이 매입금액 기준으로 바뀜(`latest-closes.ts`) | `build_batch` |
| `payload.distribution.status` | `available`·`no_cases`·`unavailable` | 필수 | `available`인데 `central_68`·기간·건수가 비면 상세 오류 | `serving/internal/distribution.py` `SampleIndex.distribution` |
| `payload.distribution.sample_count` · `stock_count` | 0 이상 정수 | 필수 | 상세 오류. `bins` 건수 합과 `sample_count`가 다르면 상세 오류 | 〃 |
| `payload.distribution.period_start` · `period_end` | `YYYY-MM-DD` 또는 null | 필수 키 | 상세 오류 | 〃 |
| `payload.distribution.histogram.bins[]` | `{left < right, count ≥ 0}` | 필수(빈 배열 허용) | 비면 분포 그림 생략 | 〃 |
| `payload.distribution.histogram.central_68` | `{low ≤ high}` 또는 null | `available`이면 필수 | null이면 "10번 중 7번 범위" 미제공 | 〃 |
| `payload.prices.basis` | `"adjusted_close"` | 필수 | 상세 오류 | `build_batch` |
| `payload.prices.source` | string | 필수 | 출처 줄에 표시 | `build_batch` |
| `payload.prices.history[]` | `{date, close > 0, volume ≥ 0}` 날짜 오름차순, `data_asof` 이하 | 필수(최근 60개) | 어긋나면 상세 오류. 2개 미만이면 가격 그림 생략, 60개 미만이면 가격 흐름 분위기 미제공 | `serving/internal/prices.py` `price_snapshot` |

화면이 읽지 않는 키(`score_event`, `sigma`, `barriers`, `distribution.policy_id`·`current`·`tolerances`, `sources`)는 규격 파일에는 있지만 이 표에서 뺐다.

## 3. 나머지 테이블

| 테이블 · 컬럼 | 타입 | 필수 | 없을 때 화면 | 만드는 곳 |
|---|---|---|---|---|
| `chart_batches.id` · `as_of` · `status` | text · date · `published` | 최근 2개 | 0개면 "어제와 달라진 근거" 숨김, 1개면 신호 변화 줄만 빠지고 뉴스·수급·공시 변화는 표시 | `storage.py` `publish` |
| `chart_signal_snapshots`(H20, 최근 2배치) `payload->>pack_id`, `inference->>status`, `inference->scores` | 위와 같음 | 선택 | 없는 종목은 신호 변화 줄을 만들지 않음 | 〃 |
| `market_status.status_date` · `condition` · `volatility_score` · `volume_score` · `index_quotes` | date · `stable`/`caution`/`high_volatility` · int · int · `{symbol,label,value,change,changePercent}[]` | 최신 1행 | 행이 없거나 읽기 실패면 호출한 쪽이 가진 스냅샷 값 유지 | `market.py` `market_status_row` |
| `supply_demand.trade_date` · `retail` · `foreign_investor` · `institution` | date · bigint(주) | 최근 20행 | 비면 사고판 주체 탭에 "사고판 기록이 아직 없어요" 안내 | `serving/supply.py` |
| `stocks.code` · `name` · `market` · `risk_grade` · `risk_flags` · `volatility_annual` · `volatility_percentile` · `risk_as_of` | text · text · `KOSPI`/`KOSDAQ` · 1~5 · text[] · number\|null · number\|null · date | `code`·`market` 필수 | `market`이 `KOSPI`가 아니면 강한 신호에서 빠짐. `risk_flags`가 회피 항목이면 "제외한 종목"으로 이동 | `serving/stock_master.py` |

## 3-1. 대시보드 '신호가 강한 종목' 선정 규칙 (2026-10-19 코드 확인, `frontend/lib/strong-signals.ts`)

| 항목 | 규칙 |
|---|---|
| 대상 | `latest_chart_signal_snapshots`에서 선택한 기간(`horizon` 20 = 앞으로 4주 기본, 5 = 1주)의 행. `inference.status = "available"`이고 `scores`가 있는 행만. 종목 마스터 `stocks.market = "KOSPI"`만 남긴다 |
| 방향 | `scores`(down·neutral·up) 중 가장 큰 쪽. **중립이 1위면 넣지 않는다** |
| 정렬 | 확신도 = 1위 점수 − 2위 점수, 큰 순. 같으면 종목 코드 오름차순 |
| 개수 | 방향마다 확신도 상위 30개를 후보로 종목 마스터를 조회한 뒤, KOSPI·제외 조건을 통과한 것 중 **상승 5 + 하락 5**. 화면은 한 목록(상승 먼저) |
| 제외 | 사용자가 직접 고른 회피 항목(하드 제약, 예: SPAC·관리종목)에 걸린 종목만 뺀다. 성향(소프트 틸트)으로는 거르거나 순서를 바꾸지 않는다. 제외는 **후보 30개 전체**에서 세어 "직접 고른 제외 항목 N개" 펼침에 보인다 — 그래서 상위 5개 밖(예: 6~30위)의 종목 때문에도 펼침이 생길 수 있다 |
| 그 밖 | 우선주·거래대금·위험등급으로 따로 거르지 않는다(필터 여부는 #208 팀 결정) |

## 4. 모델을 바꿀 때 지켜야 할 것

- [ ] `contract`·`profile`·`horizon` 값(5=aggressive, 20=stable)과 종목당 두 기간을 그대로 낸다. 바뀌면 `chart-public.ts`부터 고친다.
- [ ] `scores`는 `down·neutral·up` 세 키, 0~1, 합 1. 방향은 가장 큰 점수로 정한다.
- [ ] `features`는 \|기여\| 큰 순이고 새 피처 `name`은 `frontend/lib/featureLabels.ts`에 쉬운 이름을 같이 넣는다.
- [ ] `contribution_abs_sum`은 표시 피처 \|기여\| 합 이상이어야 한다(아니면 상세 오류).
- [ ] `prices.history`는 수정종가 60거래일 오름차순, `distribution` 건수 합 = `sample_count`.
