# 실험 실행

장기 데이터 구축·재개와 학습·평가를 수행한다. 가격 처리와 입력 피처 계산은 `shared` 한 벌을 호출한다.

## 환경과 명령

```bash
python -m venv workspace/experiments/.venv
source workspace/experiments/.venv/bin/activate
python -m pip install -r experiments/requirements.txt
python -m experiments.dataset.collect --config experiments/configs/datasets/dataset_kospi.yaml --mode full
python -m experiments.dataset.preprocess --config experiments/configs/datasets/dataset_kospi.yaml
python -m experiments.features.build_feature_panel --config experiments/configs/sliding_2016_2026_h5.yaml
python -m experiments.train --config experiments/configs/sliding_2016_2026_h5.yaml
python -m experiments.run_experiment_analysis --config experiments/configs/sliding_2016_2026_h5.yaml
```

H20은 마지막 세 명령의 설정을 `sliding_2016_2026_h20.yaml`로 바꾼다. `--allow-partial`은 검증된 가격 파일만 처리하고 제외 이유를 남길 때 명시적으로 사용한다. 수급 모델 변경·추가 튜닝은 이번 전환에 포함하지 않았다.

## 저장과 재개

설정의 `root`는 새 `workspace/experiments/datasets/shared_v3_kospi_2016`을 가리킨다. 기존 `local_2016_kospi_v1`은 원본 보존용이며 자동 재연결하지 않는다. 공급자 로그인은 `.env`의 기존 KRX 인증 설정을 사용한다.

같은 root에서 `collect --mode full`을 다시 실행하면 검증된 수집 파일을 재사용한다. 끝 날짜는 최초 구축 때 확정하고 이후 재개에서도 고정한다. `--rebuild`는 새 빈 root에서만 허용한다. 처리 버전·builder가 다른 processed 자료는 덮어쓰지 않는다.

데이터는 `workspace/experiments/datasets/`, 예측은 `workspace/experiments/cache/predictions/`, 모델·학습 입력 캐시는 `workspace/experiments/cache/training/`, 결과는 `workspace/experiments/runs/`에 저장한다. 변경된 경로·코드·입력 해시는 새 캐시 식별자를 만든다. 이전 캐시와 manifest는 보존하며 검증 없이 새 식별자로 옮기지 않는다.

처리 설정의 정본은 `shared/settings.py`다. 기본 데이터셋 YAML의 `preprocessing: shared_v3`가 이를 참조한다. Sigma는 20행·최소 10개 관측, 입력 배리어는 상방 1.5·하방 1.2배다. 연구 라벨과 표본 선택은 별도 실험 설정이다.

## 검증된 기존 v3 결과 내보내기

```bash
python -m experiments.export.refresh_pack \
  --h5-result workspace/experiments/runs/sliding_2016_2026_h5_kospi_739166ce0d474177 \
  --h20-result workspace/experiments/runs/sliding_2016_2026_h20_kospi_1734679be11d0369 \
  --pack-id YOUR_NEW_PACK_ID --activate
```

동일 pack ID를 덮어쓰지 않는다. 원본 run manifest의 과거 경로는 이 명시적 export에서만 `docs/migration.json`의 이동 기록으로 해석한다. 모델·OOS 예측·raw/processed·학습 피처의 출처, 파일 SHA-256, 전체 가격·피처 일치를 검증한다. 실패 시 활성 설정을 바꾸지 않는다.

pack은 `workspace/serving/packs/`에 생성한다. `--activate`는 `serving/config.local.yaml`만 갱신하고 이전 설정을 pack 옆에 보존한다. 프리뷰용 삼성전자 입력도 출처와 해시를 기록해 `workspace/serving/inputs/`로 명시적으로 복사한다. 원격 Release 업로드·Supabase 발행은 실행하지 않는다.
