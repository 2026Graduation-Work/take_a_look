# 실험 실행

장기 데이터 구축·재개와 학습·평가를 수행한다. 가격 처리와 입력 피처 계산은 `shared` 한 벌을 호출한다.

## 완료된 A/B 평가 원본 내보내기

H5, H20의 A 예측 전체에 원래 라벨과 같은 관측 기간의 종가 수익률을 붙인다. 재학습이나 원천 재조회 없이 저장된 입력만 읽는다.

```bash
python -m experiments.export_oos \
  --suite-dir workspace/experiments/runs/psychology_ab_2019_2025 \
  --input-evidence ../../../frontend/artifacts/performance/performance-input-evidence.json \
  --output-dir workspace/experiments/exports/psychology_ab_2019_2025_oos_20261020
```

실행 디렉터리는 `backend/analysis/chart/`다. 출력은 `h5_A.parquet`, `h20_A.parquet`, `manifest.json`이며 기존 출력 폴더가 있으면 중단한다. 완료 기록, 예측, 실행 설정, 고정 피처 입력의 해시와 A/B 표본, 평가 fold, 재계산 라벨의 일치를 확인한다. 두 파일을 모두 검증한 뒤 출력 폴더를 만든다.

| 열 | 의미 |
|---|---|
| `Date`, `Code`, `fold_id` | 신호 날짜, 문자열 종목 코드, 표본 밖 평가 fold |
| `prob_down`, `prob_neutral`, `prob_up`, `Prob` | 저장된 세 클래스 점수와 기존 상승 점수 |
| `Y_Label`, `label_observed` | 원래 라벨 0=하락, 1=중립, 2=상승과 관측 여부 |
| `horizon`, `return_date`, `forward_return`, `return_observed` | 기간, 관측 종료일, 종료 종가/신호 종가−1, 수익률 관측 여부 |
| `Trading_Halt` | 신호 날짜의 기존 거래정지 표시 |

수익률은 H5는 5개, H20은 20개의 후속 거래 가능 관측을 사용하고 거래정지를 건너뛴다. 라벨과 같이 최대 `floor(2.5 × horizon)`행 안에서 관측해야 한다. 미래 관측이 부족하거나 라벨을 확정할 수 없는 행은 제거하지 않고 라벨과 수익률을 비워 둔다. 비용, 다음 날 시가 진입, 배리어 조기 청산을 반영한 전략 수익률과는 다르다.

라벨 배수는 실행 manifest가 정본이다. 이 A/B의 H5는 상방 1.75σ, 하방 1.5σ, H20은 상방 3.75σ, 하방 3.0σ다. 화면 설명의 배수로 다시 라벨링하지 않는다. 고정된 B 입력의 공통 가격 경로를 사용하고 저장된 A 라벨과 전수 대조한다. 산출물은 로컬 workspace에 남기며 Git에 대용량 원본을 추가하지 않는다.

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

## 학습 가격 원본과 권리 이벤트

학습 수집기는 KRX 원주가를 `krx_raw_prices/{code}.parquet`에 한 번 저장한다. 열은 `Date`, `RawOpen`, `RawHigh`, `RawLow`, `RawClose`, `RawChange`, `RawVolume`, `Amount`, `ListedShares`다. `RawChange`는 KRX `CMPPREVDD_PRC`이며 등락률이 아니다. 원본 해시가 바뀌거나 기존 원주가와 재조회 결과가 다르면 중단한다.

각 상장 기간의 KRX 영업일을 모두 확인한 뒤 기준가 `RawClose - RawChange`로 이벤트를 계산한다. `dataset_manifest.json`의 `price_events.path`가 가리키는 이벤트 파일과 이벤트·원본 해시가 감사 기록이다. 데이터셋 종료일까지만 이벤트를 적용한 가격·수급 파일은 기존 `raw/`에 저장한다. 거래량은 주식수 변경 비율로 조정하므로 이전 경로의 원거래량과 달라진다. 현금배당은 포함하지 않는다.

학습 가격 기준은 `krx_raw_base_price_events_v1`이다. 기존 서빙 가격 기준과 구분한다. 이전 dataset의 파생 가격은 원주가가 같으면 다시 계산할 수 있다. 처리 코드가 달라진 기존 processed 자료는 보존하고 새 root에서 전처리한다.

실제 분할·병합·거래정지·신규상장·상장폐지 5종목 검증은 다음 명령으로 재현한다. 원주가·이벤트·파생 파일의 해시, 영업일, KRX 대비/기준가와 일간 수익률, ±30% 범위, 이전 VWAP 계산과의 일치를 확인한다. 이미 있는 원본은 재조회하지 않는다.

```bash
python -m experiments.dataset.verify_training_prices --env .env --root workspace/experiments/datasets/krx_price_check
```

2026-11-24 검증에서 005930·004920·031820·373220·003410의 9,320행과 이벤트 9개를 확인했다. 같은 root에서 `experiments.dataset.preprocess`도 5개 파일 모두 완료했다. 이 결과는 공개 KRX 가격 이력이며 개인 보유 자료가 아니다. 004920의 2020년 감자는 가격 비율과 주식 교환 비율이 달라 거래량 규칙을 확인 중이다. 이 사례의 거래량 검증은 아직 완료하지 않았다.

`shared/` 변경은 `processing_contract`와 pack 해시를 바꾼다. 기존 활성 pack을 이 checkout에서 그대로 실행할 수 없다. 이 작업은 pack 재생성·활성화·운영 게시를 수행하지 않는다. 서빙 전환과 재학습은 후속 작업이다.

## 학습 경로의 KRX 원천

학습 영업일은 pykrx 지수 1001·2001에서 받고 KRX 직접 조회 MDCSTAT00301 및 `exchange_calendars` XKRX 일정과 대조한다. pykrx와 직접 조회는 같은 KRX 원천이며 XKRX가 별도 일정 검사다. 이전 달력 캐시는 출처 버전과 XKRX 날짜가 맞아야 재사용한다.

활성 종목 상장일은 KRX MDCSTAT01901, 상장폐지 이력은 MDCSTAT23801을 사용한다. 기존 KRX `주권` 범위를 유지한다. FDR의 일반 상장 목록과 실제 학습 목록은 다르다. 기존 `-DESC` 목록에는 상장일 누락이 있어 KRX 보조 경로를 사용했다. 2026-11-20 기준 기존·변경 수집기를 직접 실행한 목록은 KOSPI 908개·KOSDAQ 1,816개로 같았다. 리츠·외국주 등의 추가는 이번 작업에 포함하지 않았다.

2016-01-01부터 2026-11-20까지 두 시장의 2,669영업일이 기존 지수 목록 및 XKRX와 일치했다. 실제 5종목 검증에서는 학습 코드의 FDR import를 금지하고도 수집이 완료됐다. 변경 전후 원주가·파생 가격 파일 해시와 두 지수의 날짜·종가·수익률이 같았다.

백테스트 KOSPI는 pykrx 1001을 사용한다. 이전 FDR 벤치마크 캐시는 재사용하지 않는다. 평가 기간과 바로 전 영업일 종가가 빠지면 중단하며, 실제 휴장일만 보유 수익률을 0으로 계산한다. 검증을 통과한 새 응답만 저장한다.

FDR은 `shared/requirements.txt`에서 제거하고 `serving/requirements.txt`에 남겼다. 서빙 전환이 완료될 때까지 종목 마스터와 기존 서빙 가격 대체 어댑터만 사용한다. 가격 어댑터는 `shared/data/prices.py`로 옮겨 동작을 보존했고 학습 수집기는 해당 어댑터를 호출하지 않는다.

## v3 실험 결과를 pack으로 내보내기

현재 활성 모델은 기본 161개 + 수급 9개 입력의 H5/H20이다. 현재 처리 계약과 새 폴더 구조로 완료한 H5·H20 run의 디렉터리를 지정한다. 수급 모델을 내보낼 때는 `--with-flows`를 붙인다.

```bash
python -m experiments.export.refresh_pack \
  --h5-result "workspace/experiments/runs/<H5 run 이름>" \
  --h20-result "workspace/experiments/runs/<H20 run 이름>" \
  --pack-id YOUR_NEW_PACK_ID --activate
```

동일 pack ID를 덮어쓰지 않는다. 모델·OOS 예측·raw/processed·학습 피처의 출처, 파일 SHA-256, 전체 가격·피처 일치를 검증한다. 실패 시 활성 설정을 바꾸지 않는다.

pack은 `workspace/serving/packs/`에 생성한다. `--activate`는 `serving/config.local.yaml`만 갱신하고 이전 설정을 pack 옆에 보존한다. 프리뷰용 삼성전자 입력도 출처와 해시를 기록해 `workspace/serving/inputs/`로 명시적으로 복사한다. 원격 Release 업로드·Supabase 발행은 실행하지 않는다.

```bash
python -m experiments.export.refresh_pack \
  --h5-result "workspace/experiments/runs/<수급 H5 run 이름>" \
  --h20-result "workspace/experiments/runs/<수급 H20 run 이름>" \
  --with-flows --pack-id YOUR_NEW_FLOW_PACK_ID --activate
```

수급 모델 export는 학습 피처 저장소의 170개 입력 순서·값·결측을 공통 builder와 대조한다. 수급이 완전했던 연구 표본에서 나온 OOS 예측으로 유사 사례를 다시 만든다.
