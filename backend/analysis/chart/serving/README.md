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
      ├─ 같은 피처 → inference.py (H5/H20 점수·상방 기여도)
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
| 추론 | pack의 H5/H20 `model.txt`에 각 모델의 `feature_names` 순서대로 **같은 날 피처** 입력. | LightGBM 3-class `down`(0), `neutral`(1), `up`(2). 상방 클래스 **내부 원점수(raw margin)** 기여 절댓값 상위 5개와 당시 피처값. 기여도는 확률 변화량이나 인과 효과가 아니다. |
| 화면 신호 가격 | 현재 수정종가와 Sigma에 pack의 **라벨 배리어** 배수 적용: H5 `1.75/1.50`, H20 `3.75/3.00`. | `inference.barriers.up/down`. 학습 입력용 배리어와 다르며 미래 가격 예측이 아니다. |
| 과거 표본 | walk-forward `Date, Code, Prob`와 종목별 `Date, Close, Trading_Halt, Sigma`. 거래정지 표시를 건너뛴 H번째 후속 실거래 행을 찾는다. | `return_pct = (미래 수정종가 / 예측일 수정종가 − 1) × 100`. 후속 가격 부족 등 제외 사유는 pack 보고서에 기록. H5/H20 분리. |
| 유사 표본 | 같은 H, `abs(과거 up − 현재 up) ≤ 0.01`, `abs(과거 Sigma − 현재 Sigma) ≤ 현재 Sigma × 0.05` **동시 충족**. 예측일 < 기준일, 관측 완료일 ≤ 기준일. | 여러 종목 포함. 비교 전 반올림 없음, 경계 포함, Sigma 0이면 과거도 0. 자동 확대·최소 표본 수 없음. 하방·중립 점수는 선택에 사용하지 않음. |

선택 표본이 0건이면 `no_cases`와 빈 `bins`를 낸다. 1건 이상이면 수익률의 최솟값~최댓값을 **동일 폭 12구간**으로 나누고 마지막 구간은 오른쪽 경계도 포함한다. 모든 수익률이 같으면 해당 값 중심의 1구간을 만든다. `central_68`은 **같은 표본**의 16·84백분위다. `bins[].count` 합계는 `sample_count`와 같다. 이는 유사 과거 신호의 **실현 수익률 분포**이며 미래 상승 확률이나 미래 가격 범위가 아니다.

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

프론트가 조회하는 정본은 [v2 JSON Schema](contracts/chart_signal_detail_v2.schema.json)다. 종목 `005930`은 공개 view에서 `stock_code = '005930'`인 H5/H20 **두 행**을 읽는다. `horizon`은 `5` 또는 `20`, `payload.contract`는 `chart_signal_detail_v2`다.

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
| 모델이 본 이유 | `inference.features[]`의 `label_ko`, `meaning_ko`, `value`, `contribution` | 상방 클래스 내부 원점수 기여. 부호 유지. |
| 실제 가격 이력 | `prices.history[]`의 `date`, `close`, `volume` | 최근 최대 60개 관측 수정종가·거래량. |
| 더 알아보기 히스토그램 | `distribution.histogram.bins[]`의 `left`, `right`, `count` | 실현 수익률 **%** 구간과 건수. 0건이면 빈 배열. |
| 과거 중앙 범위·비교 조건 | `distribution.histogram.central_68`, `sample_count`, `stock_count`, `period_start/end`, `by_fold`, `current`, `tolerances` | 중앙 범위도 수익률 **%**. 상방 절대 폭 `0.01`, Sigma 상대 폭 `0.05`. |

실제 로컬 미리보기의 삼성전자 H20 행은 상방 `0.327627`, 하방 `0.191341`, 중립 `0.481032`, Sigma `0.057581`이었다. 위 조건으로 **290종목의 과거 사례 615건**을 골랐고, 그 실현 수익률 중앙 68%는 약 `-17.06% ~ +21.31%`였다. 첫 히스토그램 막대 `left=-41.1913`, `right=-24.9032`, `count=43`은 수익률이 그 구간에 들어간 과거 사례가 43건이라는 뜻이다. 이 숫자는 2026-06-12의 **기존 가공 피처를 쓴 로컬 미리보기**이며 최신 운영 신호가 아니다.

현재 `main` 프론트는 이 view를 조회하지 않고 기존 `predictions`와 정적 데모 자료를 사용한다. 프론트 담당자가 새 view 조회와 H5/H20 전환을 연결해야 실제 데이터가 화면에 나온다. 기존 `StockDetail`의 순위·적중률·H10·수급·재무는 이 payload에 없으며 임의 값으로 채우지 않는다. 브라우저에는 공개 키만 주고 `SUPABASE_SECRET_KEY`를 전달하지 않는다.

## 파일 구조

`run_daily.py`, `build_pack.py`, `pack.py`, `local_preview.py`는 인자 해석과 `internal/` 호출만 맡는다. 일일 수집·추론과 로컬 미리보기 흐름은 `internal/pipeline.py`, 모델 pack 생성·검증·다운로드는 `internal/pack.py`, 과거 표본 생성은 `internal/samples.py`에 있다. Supabase 가격·피처 저장과 배치 발행·철회는 `internal/storage.py`의 `SupabaseStore`가 담당한다. `internal/`의 나머지 파일은 거래일, 가격 이력, 피처, 추론, 히스토그램, snapshot, 해시를 처리한다.

설정과 기본 로컬 데이터 경로는 각각 `serving/config.yaml`, `serving/data/`다. 공개 계약은 [`contracts/chart_signal_detail_v2.schema.json`](contracts/chart_signal_detail_v2.schema.json), 기록용 v1 설명은 [`contracts/v1_contract.md`](contracts/v1_contract.md)에 있다.

## 실제 확인 상태

| 항목 | 상태 |
|---|---|
| pack 생성·검사, 과거 실현 수익률 표본 | 로컬 확인 완료. H5 1,353,596건, H20 1,353,353건. |
| 로컬 Supabase 실제 입력 미리보기 | 2026-06-12 삼성전자 가격 162행·피처 1건·H5/H20 공개 2행 확인. 히스토그램 H5 699건, H20 615건. **기존 가공 피처 버전 미검증.** |
| 최신 KRX 수집 → 실제 피처 → 운영 Supabase 공개 | 아직 실실행 확인 전. |
| `main` 프론트 화면에 새 데이터 표시 | 프론트 담당 연결 전. |
| GitHub Release 업로드·Actions 수동/예약 실행 | 설정은 있으나 실실행 확인 전. |

실행 명령과 로컬 Supabase 조회는 [OPERATIONS.md](OPERATIONS.md)에 모았다. 검증 상태는 위 표에 기록한다.
