# 로컬 수집부터 Qlib 학습·평가까지

PR의 변경 버전 또는 머지 후 main에서 실행한다. 모든 명령의 실행 디렉터리는 저장소의 `backend/analysis/chart/`다. 개발자 캐시, 개인 백업 경로, 수동 증권 목록, 사전 V2 스냅샷은 필요하지 않다.

## 1. 런타임과 인증 준비

Python 3.12 환경을 준비한다. Qlib 확장 빌드가 필요한 환경에는 C++ 빌드 도구도 필요하다.

```bash
python3.12 -m venv workspace/experiments/.venv
source workspace/experiments/.venv/bin/activate
python -m pip install -r experiments/requirements.txt
python -m pip freeze > workspace/experiments/runtime-freeze.txt
```

`KRX_ID`와 `KRX_PW`를 환경변수 또는 차트 디렉터리의 로컬 `.env`에 설정한다. KIND 공개 조회에는 별도 키가 필요하지 않다. 자동 수집 경로는 DART 키를 필수로 요구하지 않는다.

같은 KRX 계정의 다른 수집이나 서빙과 시간을 겹치지 않게 한다. 중복 로그인은 기존 세션을 끊을 수 있다. 요청 간격과 예산은 [무료 운영 규칙](../../../../docs/ops/free-tier-budget.md)을 따른다.

## 2. 임시 경로에서 수집·전처리 확인

이 설정은 삼성전자와 우선주의 2025-01-06~2025-01-10 가격·수급을 사용한다. 5거래일 검사는 수집·장부·전처리·독립 재생 검증용이다. 피처 준비 기간과 학습 표본이 부족하므로 이 설정으로 모델 학습을 시작하지 않는다.

```bash
set -e
python -m experiments.dataset.collect \
  --config experiments/configs/datasets/dataset_qlib_smoke.yaml \
  --source-root workspace/experiments/smoke/qlib_2025_01/sources \
  --kind-request-budget 250
python -m experiments.dataset.preprocess \
  --config experiments/configs/datasets/dataset_qlib_smoke.yaml
OMP_NUM_THREADS=1 python -m experiments.dataset.verify_training_prices \
  --root workspace/experiments/smoke/qlib_2025_01/dataset
```

`collect`가 원주가·지수·상장 이력·공시를 준비하고 V2 장부를 생성한다. `preprocess`는 고정한 입력에서 Qlib Alpha158 피처를 계산한다. 마지막 명령은 보존 원주가와 공시 원문으로 조정 가격을 독립 재생한다. 두 종목에서 각각 가격 5행이 검증돼야 한다.

검증에 사용한 macOS·Python 3.12 환경에서 독립 검증이 결과 출력 뒤 종료되지 않는 현상을 확인했다. 위 명령은 해당 검증 프로세스의 OpenMP 스레드만 1개로 지정한다. 학습 프로세스의 스레드 설정은 바꾸지 않는다.

같은 세 명령을 다시 실행해 재사용도 확인한다. `--kind-request-budget 0`은 KIND 새 요청만 금지한다. KRX 요청까지 금지하는 전역 오프라인 옵션은 아니다. 완료된 동일 요청은 고정 입력을 검증하고 매니페스트를 유지한다.

## 3. 4년 데이터셋 수집·재개

사용 설정은 `configs/datasets/dataset_kospi_qlib_2022_2025.yaml`이다. KOSPI, 상장폐지 종목 포함, 수급 포함, 공식 Qlib Alpha158 전처리로 고정했다.

```bash
python -m experiments.dataset.collect \
  --config experiments/configs/datasets/dataset_kospi_qlib_2022_2025.yaml \
  --source-root workspace/experiments/sources/qlib_2022_2025 \
  --kind-request-budget 250
```

`--kind-request-budget`은 한 번 실행의 KIND HTTP 요청 상한이다. KRX 가격·지수·수급 요청은 별도다. 최초 장기 수집은 여러 실행이 필요하다. 예산 소진이나 일시적 원천 오류 뒤에는 같은 명령을 실행한다. 수집기는 검증된 사실을 재사용하고 부족한 자료를 받는다. 임의의 무제한 재시도 루프는 사용하지 않는다.

완료 전 상태는 다음 파일에서 확인한다.

- 데이터셋의 `collection_report.json`에 현재 단계와 실패 이유가 있다.
- `collection_source_plan.json`에 종료일·정정 확인 시한과 재시도할 누락 거래일이 고정된다.
- `source_coverage.json`과 원천 경로의 `listing_history/latest_report.json`에 공시·증권 식별의 미완료 근거가 있다.

필요한 공시 원문과 정정 날짜는 자동으로 보충한다. 조회가 완료됐지만 경제적 조건을 확정할 수 없는 사건은 구간 경계를 만들고 `review_queue.csv`에 남긴다. 이 검토표를 사람이 먼저 승인해야 다음 단계로 진행되는 구조는 아니다.

`collect`가 종료 코드 0으로 완료된 뒤 다음 단계로 진행한다. 일부 수집 상태에서 전처리하면 그 입력이 고정된다. 이후 추가 수집이 필요하면 같은 원천 경로와 새 데이터셋 root를 사용해 기존 입력을 보존한다.

## 4. 전처리와 독립 가격 검증

```bash
set -e
python -m experiments.dataset.preprocess \
  --config experiments/configs/datasets/dataset_kospi_qlib_2022_2025.yaml
OMP_NUM_THREADS=1 python -m experiments.dataset.verify_training_prices \
  --root workspace/experiments/datasets/qlib_kospi_2022_2025
```

원주가, 조정 가격, 구간, 적용 사건표와 장부 근거가 일치해야 한다. 고정 입력의 검증은 공급자 인증 없이 실행할 수 있다.

## 5. H5/H20 피처·학습·평가·백테스트

H5와 H20은 같은 데이터셋을 쓴다. 기본 모델과 비용 설정을 유지하고, 기존 10년 설정의 기간과 데이터셋 경로만 4년 실험에 맞췄다.

| 항목 | 설정 |
| --- | --- |
| 피처 | 공식 Qlib Alpha158 기반 `base` 피처 |
| 학습 구간 | 2022-01-01~2024-12-31 |
| 평가 구간 | 2025년 단일 fold |
| 실제 평가 시작 조건 | 기존 7달력일 embargo에 따라 2025-01-07부터 가능한 관측 사용 |
| H5 라벨 | 관측 5개, 상방 1.75σ, 하방 1.5σ |
| H20 라벨 | 관측 20개, 상방 3.75σ, 하방 3.0σ |
| 비용·포지션 규칙 | 각 YAML의 `strategy`와 `backtest`가 정본 |

```bash
set -e
for horizon in 5 20; do
  config="experiments/configs/qlib_2022_2025_h${horizon}.yaml"
  python -m experiments.features.build_feature_panel --config "$config"
  python -m experiments.train --config "$config"
  python -m experiments.run_experiment_analysis --config "$config"
done
```

첫 명령은 선택한 피처 저장소를 준비한다. 두 번째 명령은 모델과 예측을 만든다. 세 번째 명령은 ML 평가 후 백테스트를 실행한다. H20에서 같은 피처를 선택하면 검증된 피처 저장소를 재사용한다. 라벨과 학습 규칙이 다른 모델은 별도 저장한다.

H5에서 실패하면 위 루프는 H20으로 넘어가지 않는다. 원인을 해결한 뒤 같은 명령을 재실행한다. 유효한 캐시는 재사용한다. 모델 캐시가 있다는 이유로 다른 학습 입력에 대응시키지 않는다.

보유 중인 포지션이 가격 기준을 비교할 수 없는 구간을 넘으면 백테스트가 실패할 수 있다. 실행 root의 `backtest_status.json`과 `years/2025/execution_error.json`의 종목·날짜·사유를 확인한다. 이 실패를 전체 실행 성공으로 처리하거나 해당 종목을 임의로 제외하지 않는다.

## 6. 결과와 보관 확인

| 위치 | 확인할 산출물 |
| --- | --- |
| 데이터셋 root | `dataset_manifest.json`, `processed_manifest.json`, 고정 장부·원문, `review_queue.csv` |
| 데이터셋 root의 `feature_store/` | `feature_manifest.json`, 종목별 피처, `sample_keys.parquet` |
| `workspace/experiments/cache/training/` | 학습 바이너리·모델과 sidecar |
| `workspace/experiments/cache/predictions/` | 예측 Parquet과 manifest |
| `workspace/experiments/runs/qlib_2022_2025_h5_*`와 `h20_*` | `run_manifest.json`, `oos_history.parquet`, `ml_metrics_summary.json`, `backtest_status.json`, 백테스트 지표·거래 기록 |

H5와 H20 각각의 완료 상태와 실제 평가 구간을 확인한다. 성공한 실행은 root의 `backtest_status.json`이 `status: done`이고 `backtest_metrics.json`과 `trades.csv`가 생성된다. 단계 진입, 캐시 파일 존재, 수집 성공만으로 전체 학습·백테스트 완료를 판단하지 않는다.

고정 실행을 재생할 때는 데이터셋의 장부·원문·manifest·피처와 실행 설정·환경 기록을 함께 보존한다. 수집을 이어갈 때는 공용 원천 경로도 보존한다. 원천 개정판은 별도 원천 경로와 새 데이터셋 root를 사용한다. 원자료와 `.env`는 Git 또는 공개 PR 첨부에 올리지 않는다. 공유 보관 절차는 [백업 절차](../../../../docs/ops/backups.md)를 따른다.

## 확인된 범위와 남은 인수 실행

2026-11-28 로컬 검증에서는 빈 원천에서 두 종목·5거래일 수집·수급·자동 장부·전처리·독립 재생을 통과했다. 동일·부분 요청의 추가 통신 0회와 실제 한 거래일 확장의 부족분 수집을 확인했다. 보관 장부의 977거래일 부분 사용은 005930·005935 두 종목에서 원주가와 대조했다. 기존 전처리·피처 각 964개도 검증해 읽었다.

이번 PR 검증에서는 4년 KOSPI 전체를 빈 원천에서 새로 받아 H5/H20 학습·백테스트까지 완료하는 실행을 수행하지 않았다. 실제 전체 실행과 작성자 외 인수 실행은 #535에 남긴다. 이 문서와 설정 추가만으로 #535 F1~F9 또는 #486의 Actions 실행·보관 완료를 표시하지 않는다.
