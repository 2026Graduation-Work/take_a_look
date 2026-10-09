# 로컬 실험 파이프라인 (계약 v3)

공통 dataset YAML 하나와 실험 YAML로 수집 → 전처리 → 피처 준비 → 학습 → 평가를 실행한다.
모든 설정 안의 상대 경로는 `backend/analysis/chart/` 기준이다. `--config`는 실제 파일 경로 또는 chart 기준 경로를 받는다.

```bash
cd backend/analysis/chart
python data_collectors/price_collector.py --config configs/dataset_kospi.yaml --mode full
python data_collectors/preprocess_data.py --config configs/dataset_kospi.yaml --mode full
python -m experiments.features.build_feature_panel --config experiments/configs/local_h5.yaml
python experiments/train.py --config experiments/configs/local_h5.yaml
python experiments/run_ml_evaluation.py --config experiments/configs/local_h5.yaml
python experiments/run_backtest.py --config experiments/configs/local_h5.yaml
# 두 평가를 연속 실행하는 기존 편의 명령
python experiments/run_experiment_analysis.py --config experiments/configs/local_h5.yaml
```

저장소 루트에서도 실행 파일의 전체 상대 경로를 사용하면 같은 데이터를 읽는다.
피처 준비의 모듈 실행은 chart 디렉터리에서 하거나 `PYTHONPATH=backend/analysis/chart`를 설정한다.

## 구축과 검증

`configs/dataset.yaml`의 `root`와 `dataset_id`를 새 이름으로 정한다. 기존 `data/raw`·`data/processed`와 분리한다.
`full --rebuild`는 비어 있는 새 루트만 허용한다. 같은 설정의 `full` 재실행은 정상 가격 파일과 검증된 수급 캐시를 재사용한다.
`update`는 **그 구축의 고정된 종료일까지** 종목 전체 가격을 재조회해 초기·중간·마지막 누락과 과거 수정가격 변경을 확인한다. 기존 관측의 OHLC·등락률·거래량·거래대금·수정계수·VWAP이 바뀌면 `price_revisions/`에 이전/신규 값을 저장하고 해당 종목 갱신을 실패 처리한다. 기존 raw는 보존하며, 수정 원천값을 채택하려면 새 dataset root로 구축한다.
새 종료일까지 확장하려면 새 dataset root로 구축한다. 이전 구축의 종료일을 조용히 바꾸지 않는다.

KOSPI의 두 조회 경로와 KOSDAQ 관측일이 일치해야 달력을 저장한다. 응답 경계가 오래됐거나 중간 날짜가 다르면 중단한다.
휴일이라고 입증되지 않은 응답 뒤 구간으로 검증 범위를 연장하지 않는다. 마지막 관측일과 요청 종료일을 따로 기록한다.
지수 캐시 응답이 실패하면 명시된 KRX 지수 조회를 시도하고 실제 사용한 출처를 저장한다.
활성 상장일은 FDR DESC, 대체 원천은 KRX 종목별 기본정보(`MDCSTAT01901`)다. 회사 목록으로 우선주 상장일을 대신하지 않고 각 종목 코드의 상장일을 사용한다. FDR의 응답에 상장일이 누락돼도 이 대체 경로를 사용한다. 상폐 구간은 로그인된 KRX 이력을 사용한다.
확인되지 않은 상장일이나 겹치는 재상장 구간은 중단한다. 현재 시장 정보만으로 과거 시장 이동을 검증했다고 표시하지 않는다.

`collection.tickers: ['005930', '000660']`로 작은 범위를 먼저 검증할 수 있다.
수급 없이 기본 실험을 시작하려면 `investor_flows: false`로 구축할 수 있다.
`prices_complete`(가격 검증), `flow_queries_complete`(날짜별 수급 조회 검증), `flows_complete`(모든 원천 수급 관측의 완전성)를 분리한다.
수급 결측·조회 실패는 가격 구축을 실패시키지 않는다. 실패 날짜는 `flow_failures`로 보고하고 재실행 시 유효 캐시를 재사용한다.
수급 실험의 필요한 창이 완전한 표본만 사용하고 `flow_excluded_rows`에 다른 기본 조건을 통과했으나 수급 때문에 제외된 표본 수를 기록한다.
조회에 성공해도 순매수상위종목 응답에 특정 종목·투자자가 없을 수 있다. 그 빈칸은 0으로 추정하지 않는다.
가격 재수집 없이 기존 수급 캐시의 날짜·해시·값·커버리지를 검증하려면 다음을 실행한다.

```bash
python data_collectors/price_collector.py --config configs/dataset.yaml --verify-flows
```

`flow_validation_report.json`에 조회 검증 결과, 현재 raw 종목의 기관·개인·외국인 관측 커버리지와 1/5/20일 대금 창의 완전·제외 수를 저장한다. 아직 가격 파일이 없는 종목은 이 커버리지의 분모에 포함하지 않는다.
수급 실험에는 12개 원천 열 중 선택된 비율 피처 계산에 필요한 관측만 사용하며, 없는 응답은 0으로 만들지 않는다.

루트에는 `calendar.json`, `ticker_metadata.csv`, `benchmarks/`, `dataset_manifest.json`,
`collection_report.json`, `processed_manifest.json`, `preprocessing_report.json`이 남는다.
가격은 KRX 비수정 `RawOpen/RawHigh/RawLow/RawClose/RawVolume/Amount`를 보존하고, 공급자의 수정종가 / KRX 비수정종가 비율을 같은 날의 네 OHLC 모두에 적용한다. 수정계수의 유한·양수 여부, 원천 날짜 대응, 비수정 OHLC 관계와 수정 OHLC 산식을 검사한다. 가격은 소급 수정된 현재 스냅샷이며 당시 수정계수를 복원한 시점별 아카이브가 아니다.
KRX 원천 시가·고가·저가가 모두 정확히 0이면 `RegularSessionUnavailable`로 기록한다. 거래량·대금이 양수여도 원본과 실제 VWAP은 보존하며, 존재하지 않는 정규장 범위와 비교하지 않는다. 일부 OHLC만 0인 경우에는 검증을 실패시킨다. 전처리는 이 날짜를 기존 `Trading_Halt` 실행 제외 경로로 정규화하여 학습 표본·진입 레이블·백테스트 체결에서 제외한다. 이 플래그는 공식 거래정지 공시 확인을 뜻하지 않는다. 거래량 양수인 해당 날짜 목록은 `collection_report.json`의 `regular_session_unavailable_dates`로 보고한다.
기존 일별 캐시는 보존한다. 대규모 구축은 하루 전체 종목 조회로 부족한 KRX 비수정 OHLC를 `price_ohlc_day_cache/`에 보충하고, 소규모·일별 응답 누락 종목은 `raw_ohlc_cache/`의 종목별 전체 기간 조회로 보충한다. 기존 2년 분할 OHLC 캐시도 재사용하며 기존 종가·거래량·거래대금과 일치해야 결합한다. 기존 raw의 가격 기준을 바꿀 때는 `price_basis_backups/`에 원본을 먼저 저장한다. 재개는 `--mode full`을 사용하고 `--rebuild`를 사용하지 않는다.
VWAP = Amount / RawVolume × AdjustmentFactor 산식·날짜·양수·단위 기준은 유지한다. KRX 일별 거래대금·거래량의 거래 집계 범위는 아직 확인되지 않았으므로 `VWAPScope`에 미확인 상태를 명시한다. 일봉 범위를 벗어나면 `VWAPOutsideDailyRange`와 보고서의 날짜·건수로 기록하며 값을 강제로 자르거나 전체 가격 구축을 실패시키지 않는다.
이탈 사례 전체를 시간외 거래 때문이라고 해석하지 않는다. 공급자 응답의 원인을 확인한 사례만 따로 설명한다.
전처리의 `Trading_Halt` 실행 제외 대상은 거래량 0인 원천 행, 명시적 정지 표시, `RegularSessionUnavailable` 행이다. 원천 날짜 누락은 오류이며, 결측을 거래정지나 무거래로 추정하지 않는다.
전처리는 종목·상장 구간 전체를 다시 계산하며 워밍업 가격 행을 보존한다. processed에는 미래 라벨이 없다.
Sigma 기본 정의는 최근 20개 시장 거래일 중 비정지 로그수익률, 최소 10개다.

## 피처·표본·라벨

`features.groups`는 `base`, `psychology`, `flow`를 받는다. `include`·`exclude`로 개별 열을 조절한다.
기본 161개는 기존 모델의 순서인 `Change` + Alpha158 + 과거 Sigma 배리어 2열이다.
배리어 피처의 배율은 dataset.preprocessing 설정이다. 실험 labels 배율을 바꿔도 과거 입력이 바뀌지 않는다.
심리 기본 그룹은 구성 지표 4개이며 요약 축을 자동 중복 선택하지 않는다. 설문 성향은 입력에 없다.
수급 그룹은 개인·기관합계·외국인의 1/5/20 시장 거래일 순매수대금 / 같은 기간 비수정 Amount 합계, 총 9개다.
분모 0·원천 결측·불완전한 창은 결측이다. 실제 0은 정상 관측이다.

추가 외부 피처는 기존 `features.sources`의 `Date`, `Code`, `AvailableDate` 계약으로 결합한다.
로컬 가격 경로를 보존하기 위해 결측 행 제거와 결측 0 대체는 거부한다.
`SampleEligible`에 학습 표본 여부를 표시하고 선택된 수급 피처의 완전한 행만 포함한다.
`feature_manifest.json`에는 실제 피처 목록·순서·입력 식별자·종목별 결측과 제외 수가 남는다.
원천 열이 늘어도 모델 입력은 자동으로 늘지 않는다.

H5/H20 각각 `local_h{5,20}.yaml`, `_psychology`, `_flow`, `_psychology_flow` 예시가 있다.
수급 A/B에서는 treatment 준비 후 기본 설정에 다음을 넣어 동일 표본의 baseline을 따로 준비한다.

```yaml
features:
  groups: [base]
  matched_sample_file: data/datasets/local_2016_v1/feature_store/<treatment-id>/sample_keys.parquet
```

전체 표본 baseline 설정은 별도로 유지한다. 가격 경로는 표본 제외 후에도 남아 청산에 사용된다.

라벨은 공통 함수로 학습·검증·ML 평가에서 생성한다. dynamic은 미래 고가 상단, 미래 종가 하단,
동시 도달 하단 우선이며 horizon 비정지 거래일을 탐색 한도 `int(horizon * 2.5)` 내에 관측해야 확정한다.
fixed는 기존 horizon 시장 거래일 범위에서 정지 행을 건너뛰며 관측 부족을 미확정으로 남긴다.
학습·검증 라벨은 해당 관측 종료일에서 닫는다. 테스트는 후속 가격을 사용하지만 평가 날짜는 test fold에 한정한다.
미확정 라벨은 ML 평가에서만 제외한다. 원본 OOS 예측은 그대로 보관한다.

## 학습·캐시·백테스트

LightGBM은 명시적 피처 순서와 고정 시드, 결정론 옵션을 사용한다. 클래스 가중치는 설정을 따른다.
파일이나 피처가 빠지면 중단한다. 가격 파일 내용·계산 구현·피처 목록·라벨·분할·표본 정책이 캐시 식별에 반영된다.
예측에는 날짜·코드·fold와 down/neutral/up 확률이 남는다. 외부 예측도 같은 실행 manifest와 파일 해시가 필요하다.
전략만 바꿔도 예측 캐시는 재사용한다. 결과 폴더에는 설정의 실행 식별자가 붙어 다른 실행과 구분된다.

지원 전략은 `top_k`·`equal_weight`, 선택 확률 열·임계·N이다. 진입은 시가, 청산은 `exit_price: rule`이다.
다른 값과 알 수 없는 설정 키는 오류다. 진입 지연과 보유기간은 독립 설정이다.
시가 청산 → 시가 진입 → 장중 손절/익절 → 종가 점검 순으로 실제 체결 상태를 계산한다.
신규 진입 당일도 배리어를 검사한다. 양쪽 터치는 손절 우선, 갭은 시가를 반영한다.
진입 예산은 시가 청산 뒤 현금의 1/N을 한 번 고정하며 비용을 포함한다. 덜 선택되면 현금을 남긴다.
시그널 날짜 Sigma를 고정하고 임의 0.01 보정과 상폐 이후 가격 이어붙이기를 하지 않는다.
종가 점검 기준 도달은 다음 거래 가능한 시가 청산이다. 시간 만기는 기존 비정지 보유일 카운트를 사용한다.
보유 가격을 잃으면 포지션 정보와 오류를 기록한다.
실제 주문을 VectorBT로 집계하고 종료일 미청산 포지션은 종가 평가한다. 청산 거래 통계와 미실현손익은 분리한다.
벤치마크는 지정한 dataset 지수의 같은 날짜이며 이전 종가도 필요하다. 실행 중 지수를 내려받거나 대체하지 않는다.

결과에는 `run_manifest.json`, ML 평가, `orders.csv`, `trades.csv`, `equity_curve.csv`,
`daily_returns.csv`, `execution_report.json`, `backtest_metrics.json`이 남는다.

## 검증 상태

검증용 합성 데이터는 계약·결정론·현금 계산 확인에만 사용한다. 연구 성능 결과가 아니다.
작은 LightGBM 설정으로 실제 학습 → ML 평가 → 백테스트 CLI를 실행하는 회귀 테스트가 있다.

```bash
ruff check backend/analysis/chart
pytest backend/analysis/chart/tests backend/analysis/chart/experiments
```

실제 전 종목 구축과 H5/H20 성능 실험은 공급자의 상장 구간·가격·수급 완전성을 확인한 후 실행해야 한다.
공급자 실패 보고서를 데이터 완료나 모델 성능 검증으로 취급하지 않는다.

달력의 KS11/KQ11 캐시가 정상 응답이어도 거래일이 검증 원천과 다르면 직접 KRX 지수로 다시 조회한다. KOSPI는 인증 세션을 사용하는 KRX `MDCSTAT00301`과 pykrx 거래일을 다시 대조하며, 불일치가 남으면 날짜 차이를 출력하고 저장하지 않는다. `calendar.json`의 `fallbacks`에 원래 공급자와 재조회 이유가 남는다.

수급은 투자자별 HTTP 요청에 연결 10초·응답 30초 제한을 적용하고, 요청 오류나 빈 응답은 최대 3회 시도한다. 값·순매수 정합성 오류는 재시도 없이 실패로 보고한다. `collection_report.json`의 `flow_progress`에 날짜, 투자자, 시도 횟수, 완료·캐시 재사용 일수를 즉시 기록한다. 전체 명령에 짧은 `timeout`을 걸지 말고 이 보고서로 진행을 확인한다. 재실행은 해시·검증 버전을 통과한 일별 캐시를 재사용한다. Ctrl-C 중단도 보고서에 기록하며, 가격 완료 체크포인트는 유지한다.


독립 거래일 검증은 가격 응답이 아닌 `exchange_calendars==4.13.2`의 XKRX 규칙을 사용한다. 라이브러리에 빠진 2026-06-03·2026-07-17은 [KRX 휴장 공지](https://kind.krx.co.kr/external/2026/05/20/000110/20260520000197/32154.htm)와 [시장 간 동일 운영 안내](https://regulation.krx.co.kr/contents/RGL/03/03030100/RGL03030100.jsp)를 근거로 제외한다. 요청 시작일부터 실제 검사 종료일까지 정확히 일치해야 하며, 모든 가격 공급자가 같은 거래일을 누락해도 실패한다. 캐시도 수집 재실행 시 규칙으로 다시 검증한다. `calendar.json.schedule_validation`에 계산 버전·패키지 버전·구현 해시·예외·범위를 저장한다. 검토 범위는 2016..2026이며 새 연도는 휴장 공지를 검토한 뒤 확장한다. 불일치를 임의로 휴장일로 등록하지 않는다.

가격은 **수집 시점 공급자 수정주가의 고정 스냅샷**이다. 분할 등으로 과거 가격 단위가 환산될 수 있으며, 이것만으로 미래 정보 누수라고 단정할 수 없다. 다만 과거 시점에 실제 제공됐던 데이터의 아카이브는 아니며, 동일 dataset에서 이를 복원했다고 주장하지 않는다. 기존 스냅샷의 재현성은 파일 보존·해시·과거 값 변경 거부로 확보한다.


전 종목 가격 구축에서는 필요한 종목들의 개별 730일 요청 수와 거래일 수를 비교해, 요청이 적은 거래일별 전 종목 원천 수집을 선택한다. `price_day_cache/YYYY-MM-DD.parquet`에는 비수정 종가·거래량·거래대금을 보관하며 날짜·코드·값·해시·버전을 검사한다. `full` 재개는 정상 일별 캐시와 저장된 정상 종목을 재사용한다. `update`는 캐시를 다시 조회해 과거 변경 검사를 유지한다. 소수 종목 구축은 개별 경로를 유지한다. 모든 날짜의 원천값이 확인된 종목만 수정가격 조회에 일별 원천을 공급한다. 빠진 날짜/종목은 개별 원천 조회로 보완하며, 누락을 0이나 정지로 채우지 않는다. 새 경로의 KRX 요청에는 연결 10초·응답 30초 제한 및 최대 3회 시도를 적용한다. 가격 단계의 `price_day_progress`, `bulk_price_failures`, 종목별 결과가 보고서에 실시간 기록된다. Ctrl-C 후 같은 명령으로 재개한다. 구형 수집 프로세스는 새 코드로 자동 전환되지 않으므로 중단 후 재실행한다.


KRX 일별 가격 조회는 새 날짜 요청 사이 최소 1초를 확보한다(캐시 읽기는 대기하지 않는다). 요청 실패 시 5초·15초 뒤 재시도하며, 3개 날짜가 연속으로 최종 실패하면 원천 수집을 중단하고 보고서에 실패 상태를 남긴다. HTML 등 비JSON 응답은 HTTP 상태·Content-Type·응답 길이만 기록하고 원문/쿠키는 출력하지 않는다. 명시적인 LOGOUT·로그인 페이지 응답이면 세션을 만료 처리하여 다음 시도에서 갱신한다. 일반 비JSON 오류는 서비스 오류/접근 제한으로 기록하며 로그인 만료라고 단정하지 않는다. 서버 오류가 지속되면 캐시를 보존한 채 중단 후 복구를 기다린다.


오류 이력은 dataset root의 `collection_events.jsonl` 에 누적 저장하며 재실행해도 덮어쓰지 않는다.
가격 일별 요청의 날짜·시도·오류 유형·HTTP 상태(확인 가능한 경우)·응답 종류·소요시간·재시도 대기를 기록한다. 달력·메타데이터·종목 가격·수급의 실패도 같은 파일에 남는다. `collection_report.json`은 현재 진행 상태이고, `collection_events.jsonl`은 실패/재시도 이력이다. 로그는 UTC ISO 시각과 프로세스 ID를 포함한다.

```bash
tail -n 10 data/datasets/local_2016_v1/collection_events.jsonl
```


## 2016..2026 슬라이딩·연도별 독립 백테스트

`sliding_2016_2026_h5_flow.yaml`, `sliding_2016_2026_h20_flow.yaml`은 기본 161개+수급 9개 입력으로 3년 학습·1년 테스트를 반복한다. `_flow`가 없는 두 설정은 기본 161개만 사용한다. 이전 H5/H20 슬라이딩 설정의 모델 파라미터·라벨 배율·보유기간·비용을 유지하며, 이전 2024년 KOSPI 유니버스 파일을 새 코스피 전종목 실험에 자동 적용하지 않는다. 대상은 `configs/dataset_kospi.yaml`의 코스피 전종목(상폐 종목 포함)이며 과거 시장 이동까지 검증된 유니버스라고 주장하지 않는다.

첫 학습은 2016..2018, 첫 OOS는 2019다. 이후 2017..2019→2020, …, 2023..2025→2026으로 8개 폴드를 만든다. 7일 embargo를 유지하여 테스트 시작은 각 연도 1월 7일이며 시장 관측이 있는 날부터 예측한다. 2016..2018은 최초 학습 구간으로 OOS가 없다. YAML의 종료일은 2026-12-31이지만 실행 설정은 dataset manifest의 고정 종료일로 제한된다. 같은 dataset에서 시간이 지나도 평가 종료일이 자동 확장되지 않는다.

`backtest.capital_mode: independent_year`는 각 연도 초기자금 1,000만원·빈 포지션·새 시그널 계산으로 실행한다. 전년도 수익·포지션·지연된 시그널이 다음 연도로 넘어가지 않는다. 연말 미청산 포지션은 해당 연도의 마지막 종가로 평가해 별도 기록하며 강제 청산했다고 표시하지 않는다. 각 연도 결과는 `years/YYYY/`에 저장하고 `backtest_metrics_by_year.csv`로 비교한다. 루트 자산곡선·주문·거래·수익률에는 `year`가 붙으며 여러 해를 연속 복리 운용한 성과로 집계하지 않는다. 기존 단일 실험은 기본값인 `continuous`로 유지한다.

ML 평가의 `oos_history.parquet`에는 모든 OOS 날짜·종목·fold·클래스별 점수와 관측 가능한 라벨을 저장한다. 임계값·Top-N으로 걸러내지 않고 미확정 라벨의 예측도 `label_observed: false`로 보존한다. `oos_history.manifest.json`에 입력 피처·분할·예측 식별자·파일 해시가 남는다. 히스토그램 제작용 원천이며 이번 변경은 serving의 배포 파일을 교체하지 않는다.

```bash
for horizon in 5 20; do
  experiment_config="experiments/configs/sliding_2016_2026_h${horizon}_flow.yaml"
  python -m experiments.features.build_feature_panel --config "$experiment_config" &&
  python experiments/train.py --config "$experiment_config" &&
  python experiments/run_ml_evaluation.py --config "$experiment_config" &&
  python experiments/run_backtest.py --config "$experiment_config" || break
done
```


## 수집 속도 개선 검증 (2026-10-07)

KRX 전체 기간 단일 조회는 두 종목의 2,637일에 대해 기존 2년 분할 캐시와 여섯 원천 값·날짜가 일치했으나 각각 50.231초·93.632초가 걸렸다. 대규모 구축의 주 경로로 선택하지 않았다.
하루 전체 종목 조회는 2016-01-07 / 2024-01-04 / 2026-10-06 표본에서 각각 2.363 / 1.131 / 0.811초였으며 기존 일별 종가·거래량·거래대금과 일치했다. 대규모 구축은 이 경로로 시가·고가·저가를 보충한다. 신규 보충 일별 응답이 기존 종가·거래량·거래대금과 다르면 결합을 거부한다. 기존 캐시는 덮어쓰지 않는다.
수급 병합은 250일마다 원본 종목 파일 전체를 갱신하는 대신 작은 임시 종목별 조각을 저장하고, 조회 완료 후 원본을 종목당 한 번 갱신한다. 한 번에 전체 10년 수급을 메모리에 올리지 않는다. 캐시는 날짜마다 확정 저장하고 원본 병합 시 manifest 해시도 파일마다 갱신한다.
표본의 조회 시간은 전체 완료 시간 보장이 아니다. 서버 상태, 누락 종목의 대체 조회, 캐시 검사·저장, 수급 병합 시간이 추가된다.


## 코스피 후속 단계 실행

`sliding_2016_2026_h{5,20}{,_flow}.yaml` 네 설정과 `local_h*.yaml` 예시는 모두 `configs/dataset_kospi.yaml`을 사용한다. 종목 제한·과거 스냅샷 목록을 적용하지 않고 해당 데이터셋 전체를 후보로 사용하며 비교 지수도 같은 루트의 KOSPI다. 모델 학습의 정상 거래·워밍업·라벨 관측 조건과 수급 실험의 완전한 창 조건은 유지한다. 따라서 모든 종목의 모든 날짜가 학습 표본이 되는 것은 아니다.
chart 디렉터리에서 다음 명령으로 현재 수집된 데이터의 전처리 → 피처 생성 → 학습 → ML 평가·백테스트를 순서대로 실행한다. 수집 보고서의 실패·중단 상태와 가격 완료 플래그는 실행을 막지 않는다. `--allow-partial` 전처리는 원본 해시·가격 검증을 통과한 종목만 사용하고 제외 사유는 `preprocessing_report.json`에 남긴다. 검증된 종목이 없거나 전처리 자체가 실패하면 중단한다. H5/H20 각각 기본·수급 포함, 총 네 실험을 시도한다. 실험 단계가 실패하면 해당 실험의 후속 단계를 건너뛰고 다음 실험을 실행하며, 하나라도 실패하면 최종 종료 코드는 1이다. 불완전한 수집으로 종목 표본이 달라질 수 있고 수급 실험은 수급 창이 완전한 행만 사용한다.

```bash
bash experiments/run_kospi_pipeline.sh
```

실험명에 `_kospi`를 붙였으며 피처·캐시·결과 식별자는 새 데이터셋을 반영한다. 이전 전체 시장 데이터셋과 학습 결과를 그대로 재사용하지 않는다.


기존 `--wait-for-collection` 옵션도 허용하지만 대기하지 않고 현재 데이터로 즉시 진행한다. 수집 프로세스가 원본 파일을 갱신 중이면 해시 검사에서 실패할 수 있으므로 수집을 종료한 뒤 실행한다. 일반 `preprocess_data.py` 명령은 `--allow-partial`을 명시하지 않으면 기존의 엄격한 완료 검사를 유지한다.
2026-10-07 야간 실행은 `overnight_pipeline.log`에 출력하며 `overnight_pipeline.lock`으로 중복 실행을 막는다. 야간 실행은 유지되는 Codex 실행 세션에서 진행한다. 수집 터미널과 Codex 실행 환경을 유지하고 컴퓨터 절전·종료를 막아야 한다.

## 주문 수량·상폐 손실 정책과 백테스트 재실행

2026-10-08 합의: 매수 수량은 기존 수정 체결가격과 수수료 포함 예산으로 계산한 뒤 정수로 버림한다. 1단위도 살 수 없으면 `insufficient_cash`로 기록하고 현금·포지션을 변경하지 않는다. 소수 단위 주문은 생성하지 않는다. 가격·수수료율은 기존 실험 기준을 유지한다. 현재 체결가격은 수정가격이므로, 정수 수량은 해당 가격 기준의 모델 단위다. 비수정가격 기반 실제 주식 수량·기업행동·증권사 원단위 수수료 정산을 완전히 재현하는 정책은 아니다.

상폐는 `ticker_metadata.csv`의 확인된 상폐일 이후에만 평가액·회수 현금 0원으로 처리한다. 현금이 들어오는 매도 주문을 만들지 않고 `orders.csv`에 `writeoff`, `execution_report.json`에 손실 내역을 기록한다. `trades.csv`의 해당 보유 거래는 상폐일의 0원 종료 평가와 `Exit Reason: delisting_zero_recovery`를 기록하며, 평가손실을 종료 손익 통계에 포함한다. 원금 전액과 진입 수수료가 손실이므로 거래 수익률은 -100%보다 작을 수 있다. 일반 가격 결측·확인되지 않은 상폐는 기존처럼 오류이며, 미래 상폐 날짜를 이용해 이전 진입을 금지하거나 마지막 거래일에 강제로 매도하지 않는다. 이 0원 정책은 실제 회수액을 확인한 결과가 아니라 합의한 보수적 가정이다.

수집·전처리·피처 생성·학습·ML 평가 없이 기존 예측 캐시로 백테스트만 재실행한다. 주문 정책이 바뀌므로 기본/수급 H5/H20 네 실험을 모두 다시 계산해 비교 기준을 맞춘다. 아래 명령은 기존 결과 디렉터리의 백테스트 산출물을 갱신한다. 성공한 연도의 오래된 `execution_error.json`은 삭제한다.

```bash
for config in experiments/configs/sliding_2016_2026_h{5,20}{,_flow}.yaml; do
  python -u experiments/run_backtest.py --config "$config" || break
done
```
