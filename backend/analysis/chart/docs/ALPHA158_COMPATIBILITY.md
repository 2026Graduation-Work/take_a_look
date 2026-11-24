# Alpha158 원본 적용과 기존 모델 호환성

공식 `pyqlib==0.9.7`의 `Alpha158DL.get_feature_config()`와 Qlib 연산자를 직접 사용한다. 수식을 별도로 재작성하지 않는다. 새 경로는 `preprocessing: qlib_alpha158`로 선택한다. 기존 운영 H5/H20 모델은 학습 당시의 `shared_v3` 계산을 유지한다.

> **기존 계산 경로는 임시다.** 운영 모델을 Qlib 피처로 재학습해 전환하면 `shared_v3` Alpha158 계산, `--legacy-model`, 계산 방식 분기를 삭제한다. 삭제 목록과 완료 조건은 [#464](https://github.com/2026Graduation-Work/take_a_look/issues/464)에서 관리한다. 기존 경로에 새 기능을 추가하지 않는다.

## 계산 차이

| 피처 | 기존 계산 | Qlib 원본 |
|---|---|---|
| `BETA` | 가격 회귀 기울기 | 가격 회귀 기울기 / 현재 종가 |
| `CORR` | 종가와 거래량의 상관 | 종가와 `Log(거래량 + 1)`의 상관 |
| `CORD` | 가격 수익률과 거래량 변화율의 상관 | 가격 비율과 `Log(거래량 비율 + 1)`의 상관 |
| `WVMA` | 거래량 가중 장중 고저 폭 / 현재 거래량 | 절대 종가 수익률 × 거래량의 표준편차 / 평균 |
| `RANK` | 현재 가격 이하인 관측 비율 | 동률에 평균 순위를 부여한 백분위 |
| `IMAX`, `IMIN` | 0부터 시작하는 위치 / 윈도우 | 1부터 시작하는 위치 / 윈도우 |
| 초기 구간 | 대부분 전체 윈도우를 요구 | 연산자별 부분 윈도우 처리 |
| 수치 표현 | 주로 float64, 분모에 `1e-8` 사용 | 공식 파일 제공자의 float32 입출력, 원본 수식의 분모와 `1e-12` 사용 |

원본 피처 이름은 기존 이름에 대응시킨다. `BETA5`는 `beta_5`, `KMID2`는 `kmid_2`다. 모델 입력 순서는 기존 `BASE_FEATURES`를 따른다. 실제 VWAP, 거래정지 정규화, `Change`, Sigma, 입력 배리어와 수급 피처는 기존 계산을 사용한다. 이는 원본 Alpha158 피처 앞뒤에 적용하는 서비스의 데이터 처리 정책이다.

## 검증 결과

2026-11-24에 Python 3.12와 공식 PyPI 배포본으로 검증했다. [검증 결과 JSON](alpha158-validation.json)에 원본 소스 해시와 NumPy·pandas·SciPy 버전이 있다.

검증 명령은 별도 프로세스에서 Qlib의 표준 바이너리 파일 제공자와 `D.features()`를 실행한다. 새 어댑터와 수식 평가 코드를 공유하지 않는다. 13개 합성 입력, 713행의 158개 피처가 float32 값과 NaN·무한대 위치까지 정확히 일치했다. 수정가격, 거래정지 정규화 입력, 수급 결측, 동일 가격, 동률, 거래량 0, 가격·거래량 결측과 1·2·5·59·60·61행 이력을 포함했다. 별도 테스트는 미래 입력을 제외한 계산, 반복 호출 간 캐시 격리와 가격 단위 변경도 확인한다.

실제 운영 pack `kospi_shared_v3_flow_train2023_2025_20261014`의 해시와 H5/H20 모델의 170개 입력 순서를 검증했다. 기존 입력의 실제 `infer_batch()` 실행은 모두 통과했다. 같은 합성 입력의 초기 60행 이후 15행에 원본 피처를 넣으면 두 모델 모두 15행의 출력 확률이 달라졌다. 최대 차이는 H5 약 0.05882, H20 약 0.05732였다. 이는 호환성 실험이며 예측 성능이나 수익률의 개선을 의미하지 않는다.

기존 모델을 원본 피처와 조합하려면 재학습해야 한다. 기존 학습 원본 데이터 전체가 이 체크아웃에 없어 실제 KOSPI 전체 재학습과 성능 평가는 수행하지 않았다. 합성 데이터의 전처리·피처 저장·학습 CLI는 검증했다.

최종 차트 블록 검사는 `ruff check .` 통과, `pytest -q -ra` 373개 통과와 3개 건너뜀이다. 건너뛴 3개는 기존 심리 피처 테스트이며 `data/processed/005930.parquet` 샘플 부재가 원인이다. Qlib가 설치되지 않은 별도 서빙 환경에서도 기존 shared·serving 테스트 122개와 실제 운영 pack 로드를 검증했다. 독립 검토는 계산 대조를 재실행하고, 상장 구간·61행 추론과 잘못된 pack 혼입 거부를 확인했다.

## 연구에서 사용하기

모든 명령은 `backend/analysis/chart`에서 실행한다. Python 3.12를 사용한다.

```bash
python -m pip install -r experiments/requirements.txt
```

새 데이터셋 설정은 `experiments/configs/datasets/dataset_kospi_qlib.yaml`이다. 저장 경로는 `workspace/experiments/datasets/qlib_2016`이다. 기존 데이터셋의 processed 결과를 이 경로로 옮겨 재사용하지 않는다. 수집 전에 [무료 운영 규칙과 API 한도](../../../../docs/ops/free-tier-budget.md)를 확인한다.

```bash
python -m experiments.dataset.collect --config experiments/configs/datasets/dataset_kospi_qlib.yaml --mode full
python -m experiments.dataset.preprocess --config experiments/configs/datasets/dataset_kospi_qlib.yaml
```

사용할 H5/H20 실험 YAML을 별도 파일에 복사하고 다음 두 값을 지정한다. 나머지 학습·평가 설정은 비교 대상 실험과 같게 둔다.

```yaml
dataset: experiments/configs/datasets/dataset_kospi_qlib.yaml
experiment_name: qlib_alpha158_h5
```

```bash
python -m experiments.features.build_feature_panel --config YOUR_EXPERIMENT.yaml
python -m experiments.train --config YOUR_EXPERIMENT.yaml
python -m experiments.run_experiment_analysis --config YOUR_EXPERIMENT.yaml
```

계약에는 선택한 계산기, 어댑터 소스, Qlib 소스 해시와 수치 라이브러리 버전이 포함된다. 피처 저장본의 계약이 현재 계약과 다르면 학습 CLI가 중단한다. 기존 학습 캐시와 모델에 새 계약을 붙여 재사용하지 않는다.

원본 모델의 연구 추론에서는 모델 파일과 `.manifest.json`을 함께 보관한다. 추론 CLI는 manifest의 계약·모델 해시·입력 순서를 검증하고 해당 계산기를 선택한다. 원본 경로는 raw 디렉터리와 같은 데이터셋의 `calendar.json`과 `ticker_metadata.csv`를 읽는다. 대상 시점의 상장 구간 전체를 사용하고 학습 피처와 같은 준비 구간·거래 가능 여부·Sigma·수급 결측 기준을 적용한다. manifest가 없으면 실행을 거부한다. 학습 당시 기존 피처를 사용했다고 확인한 과거 모델만 `--legacy-model`을 붙여 기존 계산 경로로 실행한다.

```bash
python -m experiments.run_inference --model-path YOUR_MODEL.txt --raw-dir workspace/experiments/datasets/qlib_2016/raw
```

원본 모델의 운영 pack 내보내기는 현재 `refresh_pack`의 기존 v3 검증에서 거부된다. 직접 `build_pack`을 호출해도 모델·예측 sidecar가 있으면 파일 해시와 처리 계약을 검사한다. 새 Qlib 모델에 기존 연구 manifest를 잘못 붙여도 내보내지 않는다. sidecar가 없는 과거 보관 파일은 기존 연구 manifest 검증을 유지한다. 실제 재학습·평가 후 원본 계약을 지원하는 pack 검증과 담당자 확인을 거쳐 운영을 전환한다. 이 변경은 활성 pack, 정기 실행, DB를 바꾸지 않는다.

## 검증 다시 실행하기

```bash
python -m experiments.features.verify_qlib_alpha158 --output workspace/experiments/alpha158-validation.json --pack /ABSOLUTE/PATH/TO/EXISTING_PACK
ruff check .
pytest
```

`--pack`을 생략하면 공식 제공자와의 수치 비교만 실행한다. 입력 시나리오는 저장소의 가짜 가격·수급 fixture다. 실제 계좌나 보유 정보는 사용하지 않는다.

## 출처

- [Microsoft Qlib 0.9.7 Alpha158 수식](https://github.com/microsoft/qlib/blob/v0.9.7/qlib/contrib/data/loader.py)
- [Microsoft Qlib 0.9.7 연산자](https://github.com/microsoft/qlib/blob/v0.9.7/qlib/data/ops.py)
- [Qlib 공식 파일 제공자와 float32 변환](https://github.com/microsoft/qlib/blob/v0.9.7/qlib/data/data.py)
- [pyqlib 0.9.7 PyPI 배포본](https://pypi.org/project/pyqlib/0.9.7/)
- [Qlib MIT 라이선스](https://github.com/microsoft/qlib/blob/v0.9.7/LICENSE)
