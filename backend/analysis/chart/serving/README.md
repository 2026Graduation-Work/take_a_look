# 차트 serving: 현재 동작과 데이터 계약

이 문서가 **현재 H5/H20 실행 경로의 정본**이다. 프론트 소스는 여기서 수정하지 않는다. 화면은 Supabase 공개 view의 `chart_signal_detail_v2` JSON을 읽도록 프론트 담당자가 연결해야 한다. 실제 화면 연결은 아직 완료되지 않았다.

## 한눈에 보는 흐름

```text
한 번: H5/H20 모델 + 2019~2025 walk-forward 예측 + 과거 수정종가
      └─ build_pack.py → data/packs/<pack-id>/{manifest.json,h5/,h20/}

매일: run_daily.py
      ├─ KRX 거래일·KOSPI 종목 → calendar.py / fetch_universe()
      ├─ KRX 최근 240일 수정·비수정 가격/거래대금 → prices.py
      │   └─ Supabase chart_prices (종목·거래일 upsert)
      ├─ 가격 → features.py (alpha158, Sigma) → 비공개 Storage chart-features
      ├─ 같은 피처 → inference.py (H5/H20 점수·최종 방향 기여도)
      ├─ pack 과거 표본 + 현재 상방 점수·Sigma → sample_distribution.py
      └─ snapshot.py → publish.py → Supabase latest_chart_signal_snapshots
                                              └─ 프론트가 H5/H20별 payload 조회
```

`build_pack.py`는 **pack 교체 때만** 실행한다. 과거 예측을 매일 다시 만들지 않는다. `local_preview.py`는 로컬에 저장된 실제 입력으로 확인하는 별도 경로이며 최신 KRX 수집은 하지 않는다.

## 입력과 계산

| 단계 | 입력과 계산 | 결과 |
|---|---|---|
| 가격 | KRX `Date`, 수정 `Open/High/Low/Close/Volume/Change`, 비수정 `RawClose/RawVolume/Amount`. 최근 240일 재조회. `AdjustmentFactor = Close / RawClose`, 수정 기준 `VWAP = Amount / RawVolume × AdjustmentFactor`. | `chart_prices`에 `(stock_code, trade_date)` 기준 upsert. |
| 피처 | KRX 개장일로 정렬하고 거래정지를 정규화한 뒤 alpha158 계열 지표를 계산. `Sigma =` 거래된 날의 일별 로그수익률에 대한 20행 rolling 표준편차(`min_periods=10`). 학습 입력용 배리어는 종가 × `(1+1.5 Sigma)` / `(1−1.2 Sigma)`. | Parquet을 비공개 Storage에 업로드. DB에 builder ID·입력 SHA·경로 기록. |
| 추론 | pack의 H5/H20 `model.txt`에 각 모델의 `feature_names` 순서대로 **같은 날 피처** 입력. | LightGBM 3-class `down`(0), `neutral`(1), `up`(2). 최대 분류 점수 클래스 **내부 원점수(raw margin)** 기여 절댓값 상위 5개와 당시 피처값. 기여도는 확률 변화량이나 인과 효과가 아니다. |
| 화면 신호 가격 | 현재 수정종가와 Sigma에 pack의 **라벨 배리어** 배수 적용: H5 `1.75/1.50`, H20 `3.75/3.00`. | `inference.barriers.up/down`. 학습 입력용 배리어와 다르며 미래 가격 예측이 아니다. |
| 과거 표본 | walk-forward `Date, Code, Prob`와 종목별 `Date, Close, Trading_Halt, Sigma`. 거래정지 표시를 건너뛴 H번째 후속 실거래 행을 찾는다. | `return_pct = (미래 수정종가 / 예측일 수정종가 − 1) × 100`. 후속 가격 부족 등 제외 사유는 pack 보고서에 기록. H5/H20 분리. |
| 유사 표본 | 같은 H, `abs(과거 up − 현재 up) ≤ 0.01`, `abs(과거 Sigma − 현재 Sigma) ≤ 현재 Sigma × 0.05` **동시 충족**. 예측일 < 기준일, 관측 완료일 ≤ 기준일. | 여러 종목 포함. 비교 전 반올림 없음, 경계 포함, Sigma 0이면 과거도 0. 자동 확대·최소 표본 수 없음. 하방·중립 점수는 선택에 사용하지 않음. |

선택 표본이 0건이면 `no_cases`와 빈 `bins`를 낸다. 1건 이상이면 수익률을 **2%p 간격**으로 나누고 마지막 구간은 오른쪽 경계도 포함한다. 경계는 2의 배수에 맞추고 모든 수익률이 같으면 해당 값이 속한 2%p 구간 하나를 만든다. `central_68`은 **같은 표본**의 16·84백분위다. `bins[].count` 합계는 `sample_count`와 같다. 이는 유사 과거 신호의 **실현 수익률 분포**이며 미래 상승 확률이나 미래 가격 범위가 아니다.

현재 모델은 2022~2024 학습 hold 모델, 과거 표본은 2019~2025 walk-forward 예측이다. 과거 휴장일 표시와 새 VWAP 피처의 학습 입력 동등성은 아직 전수 검증되지 않았다. 해당 이슈는 pack manifest에 기록하지만 현재 연결의 실행 차단 조건은 아니다.

## Supabase 저장과 공개 계약

| 자료 | 저장 위치 | 읽는 쪽 |
|---|---|---|
| KOSPI 종목 목록 | `chart_universe` (`as_of`, `stock_code`, `stock_name`) | serving 재실행 |
| 가격 원장 | `chart_prices` (종목·거래일·수정/비수정 가격·거래대금·VWAP·수정계수) | serving |
| 피처 | 비공개 Storage `chart-features`; `chart_feature_snapshots`에 builder·입력 해시·경로 | serving |
| 추론·히스토그램·최근 60개 종가 | `chart_signal_snapshots.payload` JSON | 공개 view를 통한 프론트 |
| 실행 상태 | `chart_batches`, `chart_releases` | serving·운영자 |

`publish.py`는 H5/H20 snapshot을 staging 상태로 모두 저장한 뒤 DB RPC `publish_chart_batch`를 호출한다. 성공한 배치만 `public.latest_chart_signal_snapshots`에 보인다. 동일 입력은 동일 batch ID로 재실행되고, 공개 전에 실패하면 이전 공개 배치가 유지된다. **`--dry-run`도 가격·피처는 DB/Storage에 쓴다.** snapshot만 공개하지 않는다.

프론트가 조회하는 정본은 [v2 JSON Schema](contracts/chart_signal_detail_v2.schema.json)다. 화면은 `latest_chart_signal_snapshots`에서 선택한 종목의 H5/H20 **두 행**을 읽는다. 특정 날짜·시험 배치 ID에 고정하지 않는다. `horizon`은 `5` 또는 `20`, `payload.contract`는 `chart_signal_detail_v2`다.

```ts
const { data, error } = await supabase
  .from('latest_chart_signal_snapshots')
  .select('horizon,payload')
  .eq('stock_code', '005930');
```

| 화면에서 쓸 내용 | `payload` 필드 | 단위·해석 |
|---|---|---|
| 종목·기준일·출처 | `stock_code`, `stock_name`, `data_asof`, `pack_id`, `batch_id`, `sources` | `sources`에는 모델·입력 해시가 있다. |
| 모델 신호 | `inference.scores.up/down/neutral`, `inference.sigma`, `inference.barriers` | 점수 0~1, Sigma 비율, 배리어 가격. 점수는 보정된 미래 상승 확률이 아니다. |
| 모델이 본 이유 | `inference.features[]`의 `label_ko`, `meaning_ko`, `value`, `contribution` | `contribution_space`의 클래스 내부 원점수 기여. 양수는 해당 방향 강화, 음수는 완화. 전체 피처 절댓값 합을 기준으로 상위 5개 표시. |
| 실제 가격 이력 | `prices.history[]`의 `date`, `close`, `volume` | 최근 최대 60개 관측 수정종가·거래량. |
| 더 알아보기 히스토그램 | `distribution.histogram.bins[]`의 `left`, `right`, `count` | 실현 수익률 **%** 구간과 건수. 0건이면 빈 배열. |
| 과거 중앙 범위·비교 조건 | `distribution.histogram.central_68`, `sample_count`, `stock_count`, `period_start/end`, `by_fold`, `current`, `tolerances` | 중앙 범위도 수익률 **%**. 상방 절대 폭 `0.01`, Sigma 상대 폭 `0.05`. |

실제 로컬 미리보기의 삼성전자 H20 행은 상방 `0.327627`, 하방 `0.191341`, 중립 `0.481032`, Sigma `0.057581`이었다. 위 조건으로 **290종목의 과거 사례 615건**을 골랐고, 그 실현 수익률 중앙 68%는 약 `-17.06% ~ +21.31%`였다. 첫 히스토그램 막대 `left=-41.1913`, `right=-24.9032`, `count=43`은 수익률이 그 구간에 들어간 과거 사례가 43건이라는 뜻이다. 이 숫자는 2026-06-12의 **기존 가공 피처를 쓴 로컬 미리보기**이며 최신 운영 신호가 아니다.

프론트는 모든 연결 종목에 대해 최신 게시 배치를 조회한다. 목록과 근거 탭은 H20, 상세의 기존 기간 비교는 H5/H20 방향을 표시하며 검증 전임을 표시한다. 게시 결과가 없는 종목에는 예측 미제공을 표시한다. 기존 `StockDetail`의 순위·적중률·H10·수급·재무는 이 payload에 없으며 임의 값으로 채우지 않는다. 브라우저에는 공개 키만 주고 `SUPABASE_SECRET_KEY`를 전달하지 않는다.

## 파일 구조

`run_daily.py`, `build_pack.py`, `pack.py`, `local_preview.py`는 인자 해석과 `internal/` 호출만 맡는다. 일일 수집·추론과 로컬 미리보기 흐름은 `internal/pipeline.py`, 모델 pack 생성·검증은 `internal/pack.py`, 과거 표본 생성은 `internal/samples.py`에 있다. Supabase 가격·피처 저장과 배치 발행·철회는 `internal/storage.py`의 `SupabaseStore`가 담당한다. `internal/`의 나머지 파일은 거래일, 가격 이력, 피처, 추론, 히스토그램, snapshot, 해시를 처리한다.

설정과 기본 로컬 데이터 경로는 각각 `serving/config.yaml`, `serving/data/`다. 공개 계약은 [`contracts/chart_signal_detail_v2.schema.json`](contracts/chart_signal_detail_v2.schema.json) 하나다. 모델과 과거 표본 pack은 `serving/data/packs/`에 추적한다.

## 실제 확인 상태

| 항목 | 상태 |
|---|---|
| pack 생성·검사, 과거 실현 수익률 표본 | 로컬 확인 완료. H5 1,353,596건, H20 1,353,353건. |
| 로컬 Supabase 실제 입력 미리보기 | 2026-06-12 삼성전자 가격 162행·피처 1건·H5/H20 공개 2행 확인. 히스토그램 H5 699건, H20 615건. **기존 가공 피처 버전 미검증.** |
| 최신 KRX 수집 → 실제 피처 → 운영 Supabase 공개 | 아직 실실행 확인 전. |
| `main` 프론트 화면에 새 데이터 표시 | 프론트 담당 연결 전. |
| Git 추적 pack·Actions 수동/예약 실행 | pack 파일은 저장소에 포함. Actions 실실행은 미확인. |

실행 명령과 로컬 Supabase 조회는 [OPERATIONS.md](OPERATIONS.md)에 모았다. 검증 상태는 위 표에 기록한다.


## 매일 저장·화면 갱신

- 평일 18:30 KST Actions는 확정된 거래일의 KOSPI 목록을 수집하고 `run_daily --publish`로 두 모델 결과를 게시한다. 휴장일에는 새 배치를 만들지 않는다. GitHub 예약 실행은 지연될 수 있다.
- `chart_prices`는 `(stock_code, trade_date)` 키로 날짜별 행을 누적한다. 수정주가 정정이 있으면 해당 날짜 행을 갱신하며 과거 날짜를 삭제하지 않는다.
- `chart_universe`는 기준일별 종목 목록, `chart_feature_snapshots`와 비공개 Storage는 날짜·입력 해시별 피처를 보관한다.
- `chart_batches`와 `chart_signal_snapshots`는 날짜별 결과를 보관한다. 같은 입력을 재실행하면 중복 배치를 만들지 않는다. 같은 날짜의 정정 배치를 게시해도 기존 결과는 withdrawn 상태로 남는다.
- 두 기간의 결과를 모두 저장한 뒤 게시 RPC를 호출한다. 수집·검증·게시가 실패하면 기존 게시 배치를 유지한다.
- 화면은 최신 완성 배치 view를 조회한다. 화면에 돌아오거나 표시 중 5분마다 새로 읽는다. 모든 수치에는 실제 `data_asof`를 사용한다. 해당 종목 결과가 없으면 이전 예시 신호로 채우지 않는다.
- 수동 검증만 하려면 Actions `dry_run=true` 또는 `run_daily --dry-run`을 쓴다. dry-run도 가격·피처 입력은 DB에 저장하지만 공개 결과는 교체하지 않는다.

이 변경의 로컬 검증은 2026-09-30의 네 종목 입력과 H5/H20 여덟 snapshot으로 수행했다. 자동 게시 활성화는 main 반영 후 적용된다.

## 2026-10-01: 방향별 설명과 일일 실행 오류 수정

- 일일 결과는 `scores` 최대 클래스(동점이면 down → neutral → up 순서)를 설명한다. `contribution_space`의 class_0/1/2는 하방/중립/상방 원점수다. 과거 class_2 snapshot은 계속 상방 설명으로 읽으며 하방 기여로 재해석하지 않는다.
- 기여도 분모도 선택한 클래스의 전체 피처 절댓값 합이며 모델 기본값은 제외한다. 기본값과 전체 기여값 합이 해당 클래스 원점수와 일치하는지 검사한다.
- 히스토그램 사례 선택은 기존 상방 점수와 Sigma 기준을 유지한다. 설명 대상 클래스 변경은 사례 선택·예측 점수·모델을 바꾸지 않는다.
- 9월 30일 예약 실행 #36741211629는 영문 포함 정상 KRX 코드 27개를 숫자 전용 검사가 거부해 실패했다. 목록·가격·캐시 코드 검사를 기존 DB 규격 `[0-9A-Z]{6}`에 맞췄다. 실제 942종목 목록 및 00104K/0126Z0 가격 조회를 확인했다. 전체 운영 DB 게시 재실행은 main 반영 후 확인해야 한다.
- 변경은 로컬 검토 브랜치에만 있으며 아직 운영 배포하지 않았다. frozen `schema/` v1 계약은 변경하지 않았다. serving 내부 v2 설명 대상 enum은 과거 class_2와 호환되도록 확장했다.
