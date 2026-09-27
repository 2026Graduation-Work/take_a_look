# 차트 분석 블록

기술적 피처와 3분류 LightGBM으로 profile별 상대 스코어를 생성하고 공용 평가·백테스트를
수행한다.

설치, 데이터, 모델, config, 학습, 평가, 추론, 추가 피처, 파일 구조는
[`ONBOARDING.md`](ONBOARDING.md) 하나를 기준으로 한다.

종목 상세 H5/H20 serving의 현재 구현·공개 계약·검증 상태는
[`serving/README.md`](serving/README.md), 실행 절차는
[`serving/OPERATIONS.md`](serving/OPERATIONS.md)를 참고한다.

후속 연구 과제: 과거 KRX 휴장일 표시의 전수 감사와 실제 VWAP 피처의 학습 입력 동등성 검증. 이 두 항목은 현재 pack의 결과 해석 제한으로 남아 있다.

## 기존 experiments 코드로 2025 KOSPI H5/H20 실행

`experiments/configs/holdout_2025_h5.yaml`과 `holdout_2025_h20.yaml`은
2024-12-30 KOSPI 스냅샷 CSV의 847개 종목을 `data/processed/`에서 읽는다.
기존 파일이 모두 있는지 확인했으며, KRX 구성종목 API는 호출하지 않는다.
`backend/analysis/chart`에서 사용하는 가상환경의 Python으로 실행한다.

```bash
python experiments/train.py --config experiments/configs/holdout_2025_h5.yaml
python experiments/run_experiment_analysis.py --config experiments/configs/holdout_2025_h5.yaml
python experiments/train.py --config experiments/configs/holdout_2025_h20.yaml
python experiments/run_experiment_analysis.py --config experiments/configs/holdout_2025_h20.yaml
```

결과는 `experiments/results/<experiment_name>/`, 예측·모델 캐시는
`experiments/cache/`와 `experiments/train_src/cache/`에 저장된다.
이 스냅샷은 **2024년 말 기준 고정 종목**으로 2025 holdout을 평가한다.
과거 매일의 KOSPI 전 종목 이력이나 2026 독립 평가라고 해석하면 안 된다.
`pipeline/`의 별도 KOSPI200 재구축 스크립트는 이 실행 경로에서 사용하지 않는다.

### 2019~2025 sliding 실험

먼저 기존 FDR 상장/상폐 목록을 사용해 KOSPI 주권의 상장 구간을 한 번 저장한다.
FDR 종목 메타데이터 조회만 하며 가격 다운로드·전처리는 하지 않는다.

```bash
python -m experiments.handoff.build_kospi_universe \\
  --history-start 2016-01-01 --history-end 2025-12-31 \\
  --processed-dir data/processed \\
  --output experiments/configs/universes/kospi_history_2019_2025.csv
```

그 뒤 기존 `experiments` 코드의 3년 학습·1년 평가 설정으로 H5/H20 각각 7개 fold를
학습하고 평가 CLI에서 전체 OOS 예측의 ML 평가와 백테스트를 실행한다.

```bash
python experiments/train.py --config experiments/configs/sliding_2019_2025_h5.yaml
python experiments/run_experiment_analysis.py --config experiments/configs/sliding_2019_2025_h5.yaml
python experiments/train.py --config experiments/configs/sliding_2019_2025_h20.yaml
python experiments/run_experiment_analysis.py --config experiments/configs/sliding_2019_2025_h20.yaml
```

각 날짜는 ListingDate 이상, DelistingDate 미만인 종목만 포함한다. KRX 메타데이터가
종목의 과거 KOSPI 구분과 상장/상폐 날짜를 완전하게 제공하는 범위에서 복원한다.
또한 2025가 sliding 평가에 포함되므로 이 실행 뒤에는 2025를 손대지 않은
독립 holdout으로 부를 수 없다. 모델은 테스트 연도별로 새로 학습하지만, 백테스트는
2019~2025 OOS 신호를 한 자금 흐름으로 이어서 실행한다. 결과에는 fold별
`backtest_metrics_by_fold.csv`와 연도별 `backtest_metrics_by_year.csv`도 저장한다.
연도별 수익률은 그 해 일별 수익률만 다시 누적한 값이며, 연말을 넘겨 보유한 포지션은
다음 해 가격으로 계속 관리된다. 연말에 전량 청산하고 매년 초기자금을 재설정하는
독립 백테스트와는 다르다.

빠른 검증:

```bash
pip install -r requirements.txt
ruff check .
pytest
```
