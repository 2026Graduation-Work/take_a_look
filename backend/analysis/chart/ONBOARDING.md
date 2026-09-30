# Chart 온보딩

이 문서가 chart 파트의 실행·재현·수정 기준이다. 모든 명령은
`backend/analysis/chart/`에서 실행한다.

## A/B comparison 빠른 실행

- A: `data/processed/`의 기존 161피처
- B: A에 추가 피처를 결합한 `data/feature_store/<name>/`
- stable은 H20, aggressive는 H5로 각각 A/B를 비교한다.

```bash
cp experiments/comparison/config.example.yaml experiments/comparison/config.yaml
# config.yaml에서 treatment_price_dir, tickers, features.treatment를 수정
python -m experiments.comparison.runner --config experiments/comparison/config.yaml
```

결과는 `experiments/results/psychology_ab/`에 저장된다. A/B 사이에는 추가 피처만 달라야
하며 Date·Code·라벨·기존 161피처가 다르면 실행이 중단된다. 완료 시 네 prediction에
대응하는 공용 backtest config와 실행 명령도 출력된다.

## 1. 현재 정본

> 아래 모델 파일은 PIT universe 도입 전 학습 산출물이므로 서비스 회귀 확인용으로만
> 보존한다. 새 `security_master.parquet`로 수집·전처리·재학습·2025 holdout 평가를
> 완료하기 전에는 생존편향을 제거한 연구 결과로 인용하지 않는다.

| profile      | 모델 | 라벨                        | 학습      | 평가 | 모델 파일                                                           |
| ------------ | ---- | --------------------------- | --------- | ---- | ------------------------------------------------------------------- |
| `aggressive` | H5   | dynamic sigma `u1.75/d1.50` | 2022~2024 | 2025 | `core/models/baseline_h5_u175_d150_train2022_2024_holdout2025.txt`  |
| `stable`     | H20  | dynamic sigma `u3.75/d3.00` | 2022~2024 | 2025 | `core/models/baseline_h20_u375_d300_train2022_2024_holdout2025.txt` |

- LightGBM 3분류: `0=down`, `1=neutral`, `2=up`
- 서비스 스코어: class 2 확률
- 피처: Alpha158 계열 161개
- 모델 매핑·SHA-256 정본: `core/models/registry.yaml`
- PIT universe SSOT: `data/universe/security_master.parquet`
- 경계 규칙: `ListingDate <= Date < DelistingDate` (`DelistingDate`가 없으면 현재 상장)
- 공식 config: `experiments/configs/holdout_2025_h5.yaml`, `holdout_2025_h20.yaml`

## 2. 파일 구조와 역할

```text
backend/analysis/chart/
├── core/
│   ├── features.py              # 학습 라벨 계산(피처는 serving/internal/features.py 공통 사용)
│   └── models/
│       ├── registry.yaml        # profile → 모델·라벨·SHA 매핑 정본
│       └── baseline_*.txt       # 배포용 H5/H20 LightGBM 모델
├── data_collectors/
│   ├── price_collector.py       # raw OHLCV 수집·갱신
│   └── preprocess_data.py       # raw → 종목별 processed 161피처
├── data/                        # Git 제외
│   ├── raw/<Code>.parquet
│   ├── processed/<Code>.parquet
│   ├── external/*.parquet       # 선택: 추가 피처 원본
│   └── feature_store/<name>/    # 선택: 추가 피처 결합 결과
├── experiments/
│   ├── configs/                 # 공식·로컬 실험 config
│   ├── train_src/loaders.py     # config 기준 H5/H20 3분류 라벨 재생성
│   ├── train_src/lgbm_wrapper.py# LightGBM 학습·저장
│   ├── train.py                 # 학습 + OOS prediction 생성
│   ├── run_ml_evaluation.py     # 공용 ML 평가
│   ├── run_backtest.py          # 공용 백테스트
│   ├── run_experiment_analysis.py # ML 평가 + 백테스트 실행
│   ├── run_inference.py         # 전 종목 배치 추론
│   ├── evaluation/              # 공용 평가 함수
│   ├── backtest/engine.py       # VectorBT 실행 엔진
│   ├── features/                # 외부 피처 검증·결합
│   ├── comparison/              # baseline/treatment 4런 비교
│   ├── handoff/                 # universe·Drive 패키지 생성
│   └── results/legacy_screening/# 과거 H5/H20 선정 근거·결과(로컬 보관)
├── notebooks/
│   └── chart_holdout_2025_colab.ipynb # 로컬·Drive 전용, Git 제외
└── requirements.txt
```

## 3. 환경 준비

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

검증:

```bash
ruff check .
pytest
```

## 4. 데이터 준비

### 새로 구축

```bash
# 활성·상폐 이력을 병합하고 누락 상장일은 최초 OHLCV 거래일로 보강
python data_collectors/price_collector.py --mode master

# 상폐 종목을 포함해 각 종목의 상장 구간만 수집
python data_collectors/price_collector.py --mode full --start-date 2016-01-01
python data_collectors/preprocess_data.py --mode full
```

누락 종목만 다시 받을 때는 다음처럼 제한할 수 있다.

```bash
python data_collectors/price_collector.py --mode full --start-date 2016-01-01 \
  --codes 000001,000002
```

`full` 수집은 master도 먼저 갱신한다. 한 종목이라도 이력 수집/보정에 실패하면
`data/failed_downloads.csv`를 남기고 실패하므로, 이 파일을 해결하기 전에는 PIT
데이터셋이 완성된 것으로 간주하지 않는다. 기존 processed에는 PIT 메타데이터가 없으므로
첫 실행에서 자동으로 다시 전처리된다. 이전 버전의 processed가 섞여 있거나 PIT
메타데이터 누락으로 학습 로더 검증에 실패하면 `python data_collectors/preprocess_data.py --mode full`
명령으로 전체 재전처리한다.

### 최신 거래일 갱신

```bash
python data_collectors/price_collector.py --mode update
python data_collectors/preprocess_data.py --mode update
```

### Drive 스냅샷 사용

Drive 공유본도 `security_master.parquet`과 그 기간에 한 번이라도 포함된 processed를 함께
전달해야 한다. 학습·평가 로더는 config의 `data.universe_file`을 실제로 읽으며, 파일이
없으면 실행을 중단한다. 폴더에 어떤 parquet가 우연히 들어 있는지로 universe를 정하지 않는다.
최종 배치 위치는 아래와 같다.

```text
backend/analysis/chart/data/processed/<6자리 Code>.parquet
```

#### 방법 A: processed 폴더 사용

로컬에서 필요한 종목만 받거나 Drive를 직접 연결할 때 사용한다.

```text
Drive/chart/processed_kospi_holdout2025/<Code>.parquet
```

받은 parquet를 `data/processed/`에 복사한다. 전체 KOSPI 학습이면 폴더 전체를 받고, 일부
종목 실험이면 해당 종목 파일만 받아도 된다.

#### 방법 B: archive 사용

Colab 또는 전체 KOSPI 데이터를 한 번에 복사할 때 사용한다. archive는 필수가 아니며,
수천 개 파일의 전송 누락과 Drive I/O를 줄이기 위한 선택 사항이다.

```bash
mkdir -p data
tar -xzf /다운로드/경로/chart_processed_holdout2025_v1.tar.gz -C data
find data/processed -maxdepth 1 -name '*.parquet' | head
```

archive 내부가 `processed/<Code>.parquet` 구조이므로 `data/`에 압축을 풀어야 한다.
Parquet 자체가 압축돼 있어 archive의 주목적은 용량 절감이 아니다.

학습·평가·백테스트에는 processed만 필요하다. 기존 모델로 서비스 추론까지 실행하려면
직접 수집으로 만든 `data/raw/<Code>.parquet`도 필요하다.

학습 입력은 `data/processed/<Code>.parquet`이다. 파일 안의 기존 `Y_Label`은 최종
target이 아니다. `experiments/train_src/loaders.py`가 실행 config에 따라 H5/H20
라벨을 다시 계산한다. H5/H20 전용 parquet를 별도로 만들지 않는다.

## 5. 기존 모델 추론

### 단일 종목

```python
import lightgbm as lgb
import pandas as pd

from data_collectors.trading_calendar import get_krx_trading_days
from serving.internal.features import build_feature_frame
from serving.internal.inference import infer_batch

model = lgb.Booster(
    model_file="core/models/baseline_h5_u175_d150_train2022_2024_holdout2025.txt"
)
prices = pd.read_parquet("data/raw/005930.parquet")
prices["Date"] = pd.to_datetime(prices["Date"])
prices = prices.sort_values("Date").tail(85)
days = get_krx_trading_days(
    prices.Date.min().strftime("%Y-%m-%d"), prices.Date.max().strftime("%Y-%m-%d")
)
features = build_feature_frame(prices, days)
latest = features.loc[features.Date.eq(prices.Date.max())]
scores, top_features, _ = infer_batch(model, latest)[0]
latest_score = scores["up"]  # class 2 확률. 65거래일 미만이면 Sigma가 비어 추론하지 않는다
```

chart 디렉터리에서 `PYTHONPATH=.`로 실행한다. 입력에는 거래대금 기반 `VWAP` 컬럼이 필요하다.
저장소에 들어 있는 `data/raw/005930.parquet`는 VWAP 이전 형식이라 직접 수집한 파일로 바꿔야 한다.

H20은 모델 경로만 아래 파일로 바꾼다.

```text
core/models/baseline_h20_u375_d300_train2022_2024_holdout2025.txt
```

### 전 종목

```bash
python experiments/run_inference.py \
  --profile aggressive \
  --target-date 2025-12-31 \
  --output-dir experiments/results/inference_h5
```

H20은 `--profile stable`로 실행한다. `--model-path`는 registry 밖의 모델을 시험할 때만
사용한다. 출력의 `REVIEW`는 사전 합의한 스코어 임계 도달 표시이며 매수·매도 지시가 아니다.

모델 스코어는 미래 상승을 보장하는 확률이 아니다. 화면에서는 과거 유사 신호 기준의
상대 스코어로 표현하고 자동 매매 지시로 사용하지 않는다.

## 6. H5/H20 재학습

### 로컬

공식 config를 복사해 `experiment_name`, `data.price_dir`, `data.version`만 실행 환경에
맞게 수정한다. 공식 파일은 직접 덮어쓰지 않는다.

```bash
cp experiments/configs/holdout_2025_h5.yaml experiments/configs/local_h5.yaml
cp experiments/configs/holdout_2025_h20.yaml experiments/configs/local_h20.yaml
```

`local_h5.yaml` 수정 예시:

```yaml
experiment_name: "local_holdout_2025_h5_20260814"

data:
  price_dir: "/content/drive/MyDrive/stock_prediction/data/processed"
  version: "chart_processed_holdout2025_v1"
```

로컬 저장소 데이터면 `price_dir: "data/processed"`를 사용한다. H20도 같은 세 필드만
바꾸고 `labels`·`model`·`strategy`·`backtest`는 공식 config 값을 유지한다.

실행:

```bash
python experiments/train.py --config experiments/configs/local_h5.yaml
python experiments/run_experiment_analysis.py --config experiments/configs/local_h5.yaml

python experiments/train.py --config experiments/configs/local_h20.yaml
python experiments/run_experiment_analysis.py --config experiments/configs/local_h20.yaml
```

개별 실행:

```bash
python experiments/run_ml_evaluation.py --config experiments/configs/local_h5.yaml
python experiments/run_backtest.py --config experiments/configs/local_h5.yaml
```

## 7. Config 핵심 필드

```yaml
data:
  price_dir: data/processed
  version: 데이터_스냅샷_ID
  tickers: [005930, ...]
  splits:
    - train_start: "2022-01-01"
      train_end: "2024-12-31"
      test_start: "2025-01-08"
      test_end: "2025-12-31"

labels:
  type: dynamic_sigma
  horizon: 5
  up_mult: 1.75
  down_mult: 1.50

model:
  type: LGBM
  objective: multiclass
  params: { ... }

training:
  skip_validation: true
```

- `labels`: target 생성 규칙
- `model.params`: LightGBM 파라미터
- `strategy`: 스코어 임계·Top-N
- `backtest`: 체결 지연·비용·보유기간·청산 규칙
- `evaluation`: 평가 bin·benchmark 설정

2025 final holdout 재현 시 라벨·모델·백테스트 파라미터를 바꾸지 않는다.

## 8. 실행 결과 위치

```text
experiments/train_src/cache/models/<hash>_fold0_model.txt
experiments/cache/<hash>_predictions.parquet
experiments/results/<experiment_name>/
├── model_metrics_by_fold.csv
├── calibration_by_fold.csv
├── backtest_metrics_summary.json
├── backtest_metrics_by_fold.csv
├── benchmark_comparison.csv
├── benchmark_metadata.csv
├── fold_alignment.csv
├── trades.csv
└── daily_returns.csv
```

반드시 확인할 값:

- prediction과 평가 라벨의 `Date × Code` 정합성
- ROC AUC, PR AUC, Rank IC, calibration
- 수익률, Sharpe, MDD, 거래 수
- benchmark source와 비용·보유기간
- 모델 SHA-256과 실행 commit

결과 대시보드:

```bash
streamlit run experiments/result_dashboard/app.py
```

브라우저에서 왼쪽 `결과 분석할 실험` 목록의 `experiment_name`을 선택한다. 목록에 없다면
`experiments/results/<experiment_name>/`가 생성됐는지 먼저 확인한다. 대시보드에서는 ML
지표, fold별 백테스트, benchmark 비교, 거래 내역과 피처 중요도를 확인한다.

## 9. 추가 피처 붙이기

기존 161피처 parquet를 수정하지 않는다. 추가 피처는 별도 parquet로 받는다.

필수 컬럼:

```text
Date | Code | AvailableDate | <numeric_feature_columns...>
```

- `AvailableDate`: 모델이 처음 사용할 수 있는 거래일
- 장 마감 뒤 생성된 값은 다음 거래일을 기록
- `(Code, Date, AvailableDate)` 중복 금지
- target·label·future·next 계열 컬럼 금지

로컬 config 예시:

```yaml
data:
  price_dir: data/feature_store/extra_v1

features:
  profile_name: extra_v1
  base_processed_dir: data/processed
  base_columns: "*"
  materialized_dir: data/feature_store/extra_v1
  sources:
    - name: external
      path: data/external/external.parquet
      apply_period: one_day
      columns: [feature_a, feature_b]
      missing: { policy: zero, add_indicator: true }
```

생성·학습:

```bash
python -m experiments.features.build_feature_panel \
  --config experiments/configs/local_extra.yaml
python experiments/train.py --config experiments/configs/local_extra.yaml
python experiments/run_experiment_analysis.py --config experiments/configs/local_extra.yaml
```

추가 피처 컬럼을 바꿀 때 수정할 곳:

1. 외부 parquet의 숫자 컬럼
2. `features.sources[].columns`
3. 새 `profile_name`, `materialized_dir`
4. 비교실험이면 `experiments/comparison/config.yaml`의 `features.treatment`

결합 코드 수정은 필요 없다. 피처 구성이 바뀌면 기존 feature store를 덮어쓰지 말고 새
경로를 사용한다.

### 9.1 시장 심리 피처 (psychology_market_v1)

가격·거래량만으로 계산하는 행동재무학 프록시 4개를 위 계약대로 생성하는 도구가 있다.

```bash
python -m experiments.features.build_psychology_features \
  --price-dir data/processed --out data/external/psychology_market_v1.parquet
```

정의·계산식·윈도우·한계·결합 설정은
[`experiments/features/PSYCHOLOGY_FEATURES.md`](experiments/features/PSYCHOLOGY_FEATURES.md)를
따른다. 워밍업이 65거래일이므로 `train_start`는 각 종목의 첫 거래일 + 66거래일 이후여야
A/B 행 정합성 검사를 통과한다.

## 10. 기존 161피처 자체를 수정할 때

추가 외부 피처와 달리 다음 파일을 함께 수정한다.

1. `data_collectors/preprocess_data.py`: 학습 parquet 피처 생성
2. `serving/internal/features.py`: 학습·서비스 공통 피처 생성
3. `serving/internal/inference.py`의 `BASE_INFO`/`WINDOW_INFO`: 화면용 피처 이름·설명(없으면 추론이 오류로 멈춤)
4. 관련 테스트
5. processed 전체 재생성
6. H5/H20 모두 재학습·재평가
7. 모델 파일과 `core/models/registry.yaml` SHA 갱신

입력 순서는 학습 모델의 `feature_name()`이 정한다. `build_feature_frame` 결과에 그 이름이
모두 있어야 한다.

## 11. Baseline/Treatment 비교

실제 외부 데이터가 있을 때만 사용한다.

```bash
cp experiments/comparison/config.example.yaml experiments/comparison/config.yaml
python -m experiments.comparison.runner \
  --config experiments/comparison/config.yaml
```

- A: 기존 161피처
- B: A + 추가 피처
- stable H20과 aggressive H5를 각각 A/B 비교
- 같은 profile 내부의 키·라벨·baseline 피처 동일성을 자동 검사
- ML 평가는 공용 평가 함수 사용
- `backtest_configs/`에 네 prediction별 공용 backtest config 자동 생성
- runner가 마지막에 출력하는 네 `run_backtest.py` 명령으로 trading 평가 실행
