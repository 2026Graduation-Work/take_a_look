# H5/H20 chart serving

`serving/`은 일일 가격 수집, 피처 계산, H5/H20 LightGBM 추론, 과거 실현 수익률 히스토그램 계산, Supabase 배치 공개를 담당한다. 일일 실행 경로(`run_daily.py`)는 연구 폴더를 import하지 않는다. 기존 v1 연구 변환 보조 파일은 별도로 남아 있다. 화면 계약은 이 폴더의 `contracts/`에 두며 freeze된 `schema/`와 별개다.

## Model pack

한 pack은 H5와 H20의 `model.txt`, 2019~2025 walk-forward `historical_samples.parquet`, 해시와 피처 순서를 담은 `manifest.json`으로 구성된다. 현재 추론 모델은 2022~2024 학습 hold 모델이다. pack은 GitHub Release 첨부 파일로 배포하고 `config.yaml`의 `active_pack`에서 release 태그, 파일명, SHA-256, pack ID를 지정한다.

pack 생성은 명시적으로 전달한 연구 산출물에서 한 번 수행한다.

```bash
python -m serving.build_pack --pack-id PACK_ID --output serving/data/packs \
  --model-h5 H5_MODEL.txt --model-h20 H20_MODEL.txt \
  --predictions-h5 H5_OOS.parquet --predictions-h20 H20_OOS.parquet \
  --processed-dir PROCESSED_DATA_DIR
```

명령은 `serving/data/packs/PACK_ID.tar.gz`와 표본 제외 사유가 담긴 `build_report.json`을 만든다. 실행 환경에서는 다음 명령으로 활성 pack을 받아 검사한다.

```bash
cd backend/analysis/chart
python -m pip install -r serving/requirements.txt
export CHART_SERVING_DATA_DIR="$PWD/serving/data"
export GITHUB_REPOSITORY=2026Graduation-Work/Stock_Prediction_v2
# 비공개 Release라면 GH_TOKEN도 설정한다.
python -m serving.pack download --config serving/config.yaml
```

로컬에 같은 pack 디렉터리가 있으면 다운로드 단계는 생략할 수 있다.

## 일일 실행

```bash
python -m serving.run_daily --dry-run
python -m serving.run_daily --publish
python -m serving.run_daily --as-of YYYY-MM-DD --publish
```

`--publish`에는 `SUPABASE_URL`과 `SUPABASE_SECRET_KEY`가 필요하다. 최신 확정 거래일에는 원천 가격을 새로 수집해 가격 DB와 피처 Storage를 갱신한다. 과거 날짜 재실행에는 저장된 해당 날짜의 종목 목록과 입력이 필요하다. H5/H20은 한 배치로 저장·공개되며, 실행 실패 시 이전 공개 배치는 유지된다. 실제 표본이 1건 이상이면 히스토그램을 만들고 0건은 `no_cases`로 표시한다.

자세한 배포·재실행·복구 절차와 실제 운영 확인 상태는 [OPERATIONS.md](OPERATIONS.md)에 기록한다. [HISTOGRAM_INFERENCE.md](HISTOGRAM_INFERENCE.md)는 확정된 계산·표시 규칙이다.
