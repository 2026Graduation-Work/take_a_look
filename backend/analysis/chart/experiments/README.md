# 실험 실행

장기 데이터 구축·재개와 학습·평가를 수행한다. 가격 처리와 입력 피처 계산은 `shared` 한 벌을 호출한다.

## 완료된 A/B 평가 원본 내보내기

H5, H20의 A 예측 전체에 원래 라벨과 같은 관측 기간의 종가 수익률을 붙인다. 재학습이나 원천 재조회 없이 저장된 입력만 읽는다. 아래 2019–2025 실행은 기존 경로 예시다. 공식 사건표 해시가 없는 그 기간의 구형 산출물은 새 내보내기에서 거부한다.

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
python -m experiments.dataset.collect --config experiments/configs/datasets/dataset_kospi.yaml --mode full \
  --action-snapshot "$ACTION_SNAPSHOT"
python -m experiments.dataset.preprocess --config experiments/configs/datasets/dataset_kospi.yaml
python -m experiments.features.build_feature_panel --config experiments/configs/sliding_2016_2026_h5.yaml
python -m experiments.train --config experiments/configs/sliding_2016_2026_h5.yaml
python -m experiments.run_experiment_analysis --config experiments/configs/sliding_2016_2026_h5.yaml
```

먼저 아래 절차로 공식 사건표를 수집하고, 출력된 파일 경로를 `ACTION_SNAPSHOT`에 지정한다. H20은 마지막 세 명령의 설정을 `sliding_2016_2026_h20.yaml`로 바꾼다. `--allow-partial`은 검증된 가격 파일만 처리하고 제외 이유를 남길 때 명시적으로 사용한다. 수급 모델 변경·추가 튜닝은 이번 전환에 포함하지 않았다.

## 저장과 재개

설정의 `root`는 새 `workspace/experiments/datasets/shared_v3_kospi_2016`을 가리킨다. 기존 `local_2016_kospi_v1`은 원본 보존용이며 자동 재연결하지 않는다. 공급자 로그인은 `.env`의 기존 KRX 인증 설정을 사용한다.

같은 root에서 `collect --mode full`을 다시 실행하면 검증된 수집 파일을 재사용한다. 끝 날짜는 최초 구축 때 확정하고 이후 재개에서도 고정한다. `--rebuild`는 새 빈 root에서만 허용한다. 처리 버전·builder가 다른 processed 자료는 덮어쓰지 않는다.

데이터는 `workspace/experiments/datasets/`, 예측은 `workspace/experiments/cache/predictions/`, 모델·학습 입력 캐시는 `workspace/experiments/cache/training/`, 결과는 `workspace/experiments/runs/`에 저장한다. 변경된 경로·코드·입력 해시는 새 캐시 식별자를 만든다. 이전 캐시와 manifest는 보존하며 검증 없이 새 식별자로 옮기지 않는다.

처리 설정의 정본은 `shared/settings.py`다. 기본 데이터셋 YAML의 `preprocessing: shared_v3`가 이를 참조한다. Sigma는 20행·최소 10개 관측, 입력 배리어는 상방 1.5·하방 1.2배다. 연구 라벨과 표본 선택은 별도 실험 설정이다.

## 공식 사건표와 KRX 학습 가격

수집 대상 CSV에 KRX 종목코드와 표준코드(ISIN), 주식 종류, 상장·상장폐지일, 시장을 적는다. 상장 중인 증권은 `delisting`을 비워 둔다. OpenDART 법인코드와 발행사의 대표 종목코드를 함께 적는다. 우선주의 `issuer_code`는 법인의 대표 종목코드이고 `code`와 `isin`은 우선주 자체의 식별자다. KRX 개별증권 정보(MDCSTAT01901)와 OpenDART 법인코드에서 각 필드를 확인한다.

```csv
code,isin,share_class,listing,delisting,corporation,issuer_code,market
104620,KR7104620000,common,2019-01-30,,00632845,104620,KOSDAQ
```

다음은 노랑풍선 한 종목과 가격 24거래일에 한정한 재현 예제다. `--lookback`은 최초 결정이나 정정을 찾기 위한 첫 공시일, `--through`는 확인할 마지막 공시일이다. 현재 확인 가능한 공시를 사용하려면 `--through`에 실제 확인일을 지정한다. 설정한 범위 밖의 최초 공시나 정정 관계를 발견하면 검토 대기 상태로 남긴다. KRX 달력은 검증된 기간만 지원한다.

```bash
python -m experiments.dataset.collect_actions \
  --root workspace/experiments/official_actions \
  --run yellow-2021 --securities securities.csv \
  --start 2021-07-19 --end 2021-08-20 --lookback 2020-07-19 --through 2021-08-31 \
  --request-budget 25 --env-file .env
```

`OPEN_DART_API` 환경변수나 `--env-file`의 기존 키를 사용한다. `--request-budget`은 이번 실행의 두 출처 합계 요청 한도다. 제공자 한도와 다른 수집 작업의 사용량을 먼저 확인한다. 요청 오류나 예산 소진 뒤 같은 `--run`으로 재개하면 검증된 응답을 재사용한다. 조회 기간, 증권, 코드 판본을 바꾸거나 새 정정을 확인하려면 새 실행 이름을 사용한다. 페이지 사이에 전체 건수가 바뀌면 다음 재개 때 해당 조회 구간의 페이지를 다시 확인한다.

공식 수집 root 아래 `archive/objects`와 `archive/receipts`에는 응답 본문과 수신기록을 해시별로 보관한다. 같은 접수번호로 내용이 바뀌면 별도 판본이 쌓인다. `runs/<run>/status.json`은 조회 실패와 검토 대기를 구분한다. 다 읽은 기간의 페이지 증거와 공식 문서 판본을 `snapshots/<sha256>.json`에 고정한다. 수집 root를 보존해야 사건표가 가리키는 공식 원문과 수신기록을 다시 검증할 수 있다. [OpenDART 공시 목록](https://opendart.fss.or.kr/guide/detail.do?apiGrpCd=DS001&apiId=2019001) · [KIND 시장조치](https://kind.krx.co.kr/disclosure/detailsExt.do?ext=y&method=searchDetailsMktactMainExt)

### KIND 시장조치 판정 장부

차트 디렉터리에서 보존한 KRX 일별 전 종목 원주가로 판정 장부를 만든다. `KRX_ACTIVE_MASTER`는 KRX 전 종목 기본정보 파일이다. `KRX_DELISTED_MASTER`에는 공식 상장폐지 이력과 단축코드·시장별로 확인한 ISIN이 필요하다. 파일에서 확인한 증권 종류, 시장 및 상장일을 판정 키로 사용한다.

```bash
python -m experiments.dataset.census_actions \
  --start 2016-01-01 --end 2026-11-20 \
  --published-start 2016-01-01 --published-end 2026-11-20 \
  --krx-days "$KRX_DAYS" --active-master "$KRX_ACTIVE_MASTER" \
  --delisted-master "$KRX_DELISTED_MASTER" --kind-root "$KIND_ARCHIVE" \
  --kind-daily-cache "$KIND_DAILY_CACHE" --output "$CENSUS_RUN" --preview
```

기본 요청 예산은 0이다. `--kind-daily-cache`로 가져오는 파일은 날짜별 HTML과 동일 이름의 JSON 수신기록이다. 수신기록의 응답 SHA-256, 수신 시각, 인코딩, URL 및 요청 양식이 응답과 일치해야 한다. `--kind-archive`는 `응답_저장소=실행_폴더` 형식으로 이전 수집 영수증을 가져온다. `--action-snapshot`으로 현행 구현에서 검증한 DART·KIND 단위 변경 사건표도 넣을 수 있다. KIND 온라인 수집 전에 남은 한도를 확인한다. `--request-budget`만큼 새 요청을 허용하며, KIND 요청 사이에 0.6초 이상 기다리고 HTTP 403 또는 429에서 새 요청을 멈춘다. 재실행할 때 저장소는 재사용하고 출력 경로를 새로 지정한다. [무료 운영 한도](../../../../docs/ops/free-tier-budget.md)

`candidates.csv`는 원주가 관측을, `notices.csv`는 KIND에서 확인한 증권별 시행 사실을 담는다. `resolutions.csv`는 시행일별 판정과 근거, 유리수 가격·거래량 계수를 담는다. 가격 후보가 없어도 공식 인적분할, 합병 및 스팩 합병 시행일을 기록한다. 거래정지 중 주식수만 바뀐 판정이나 구간 판정의 계수는 비워 둔다. `coverage.json`은 미완료 조회, 검토 대상 공시, 증권 식별 실패를 남긴다. 후보가 없던 상장 구간도 실제 거래일 범위, 거래대금을 포함한 원주가 지문, 스팩 소속부 공시 근거를 기록한다. `manifest.json`에는 각 표와 가격 입력의 해시, 시장 전체와 학습 대상 시장의 집계가 있다.

완료한 조회에서 근거를 확인할 수 없으면 검토가 필요한 `segment_break`를 기록한다. 누락된 KIND 목록이나 본문은 미완료 조회로 남긴다. `--preview`, `--code`, `--sample`은 부분 검증에 쓴다. 전체 범위를 조회했을 때 장부가 미완료면 명령은 종료 코드 2를 반환한다. 이 명령은 학습 입력과 라벨을 바꾸지 않는다.

`notices.csv`의 `Published`는 KIND 목록에 표시된 날짜다. 접수번호는 원문 조회 키로 보존한다. 당시 공개 자료만 쓴 분석에는 최초 공개 시점을 별도로 확인해야 한다.

주주배정 유상증자는 거래소가 확인한 권리락 기준가를 사용한다. 무상증자와 주식배당은 공식 공시의 1주당 배정 비율로 조정한다. 2023-01-25 전후의 거래소 호가표를 적용하며, 공시가 가격 차이를 설명하지 않는 경우에 호가 올림을 확인한다. [KRX 기준가격](https://regulation.krx.co.kr/contents/RGL/03/03010100/RGL03010100T6.jsp) · [KRX 권리락](https://regulation.krx.co.kr/contents/RGL/03/03010401/RGL03010401.jsp) · [KRX 과거 호가표](https://global.krx.co.kr/contents/GLB/01/0109/0109000000/guide_to_trading_in_the_korean_stock_market.pdf) · [KRX 개정 호가표](https://regulation.krx.co.kr/contents/RGL/03/03020100/RGL03020100.jsp)

새 데이터셋은 시작할 때 사건표를 `official_actions/`에 복사하고 해당 해시를 가격·전처리·피처·학습·내보내기 manifest에 전달한다. 이후 같은 데이터셋은 고정된 사건표로 재개한다. 새 사건표를 쓰려면 새 데이터셋 root를 사용한다. 가격 범위는 사건표의 가격 범위 안에 있어야 한다.

가격 수집기는 KRX 원주가를 `krx_raw_prices/{code}.parquet`에 먼저 보존한다. 원본과 영업일을 검증한 뒤 공식 사건을 적용한다. 승인한 분할·병합·무상증자의 가격과 비교용 거래량은 공시의 교환비율로 각각 환산한다. 무상증자는 권리락일 전 가격과 거래량을 환산하고 후속 신주 상장일에는 같은 비율을 다시 적용하지 않는다. Raw OHLC, `RawVolume`, `RawChange`, `Amount`는 그대로 보존한다. 실제 거래량은 `RawVolume`이다.

`ExchangeChange`는 KRX 당일 기준가 대비 등락률이다. `Change`는 단위를 맞춘 종가의 전일 대비 수익률이다. 씨아이테크의 3대1 병합은 정지 전 종가 295원을 885원으로 환산하고 재개 종가 623원을 그대로 사용한다. 학습 수익률에 약 -29.60%가 남으며, 재개 시초가 636원 대비 KRX 등락률 약 -2.04%도 별도로 남는다. 보통주 단위가 변하지 않은 액면감액의 확인된 기준가 재설정은 가격과 거래량을 그대로 유지한다. [씨아이테크 시행 공지](https://kind.krx.co.kr/external/2020/03/17/000810/20200317002023/68155.htm) · [2023년 전 호가단위](https://global.krx.co.kr/contents/GLB/01/0109/0109000000/guide_to_trading_in_the_korean_stock_market.pdf) · [현행 호가단위](https://global.krx.co.kr/contents/GLB/06/0602/0602010201/GLB0602010201T3.jsp)

기준가 변화나 정지 전후 주식수는 검토할 KRX 관측이다. 교환비율과 적용일을 증명하지 못하거나 공시와 관측이 충돌하면 해당 종목의 파생 입력을 보류한다. 구형 파일이 있더라도 최신 manifest의 허용 목록에 없으면 전처리·학습에서 읽지 않는다. 명시적으로 부분 전처리한 결과에는 승인된 파일과 보류 내역을 남긴다.

이 가격은 현재 선택한 공식 자료를 적용해 과거 주식 단위를 재구성한 자료다. 각 예측일에 당시 발표된 자료만으로 같은 피처를 생성할 수 있었는지는 별도 검증이 필요하다. 미지원·복합 사건과 공식 연결이 모호한 정정도 검토 대상이다.

저장한 KRX 원본, 적용 사건표, 파생 가격은 네트워크 없이 재계산해 대조할 수 있다.

```bash
python -m experiments.dataset.verify_training_prices --root workspace/experiments/datasets/krx_price_check
```

`shared/` 변경은 연구용 `processing_contract`를 바꾼다. 기존 운영 팩은 서빙 계약과 고정 피처 기대값으로 별도 검증한다.

## 학습 경로의 KRX 원천

학습 영업일은 pykrx 지수 1001·2001에서 받고 KRX 직접 조회 MDCSTAT00301 및 `exchange_calendars` XKRX 일정과 대조한다. pykrx와 직접 조회는 같은 KRX 원천이며 XKRX가 별도 일정 검사다. 이전 달력 캐시는 출처 버전과 XKRX 날짜가 맞아야 재사용한다.

활성 종목 상장일은 KRX MDCSTAT01901, 상장폐지 이력은 MDCSTAT23801을 사용한다. 기존 KRX `주권` 범위를 유지한다. FDR의 일반 상장 목록과 실제 학습 목록은 다르다. 기존 `-DESC` 목록에는 상장일 누락이 있어 KRX 보조 경로를 사용했다. 2026-11-20 기준 기존·변경 수집기를 직접 실행한 목록은 KOSPI 908개·KOSDAQ 1,816개로 같았다. 리츠·외국주 등의 추가는 이번 작업에 포함하지 않았다.

2016-01-01부터 2026-11-20까지 두 시장의 2,669영업일이 기존 지수 목록 및 XKRX와 일치했다. 실제 5종목 검증에서는 학습 코드의 FDR import를 금지하고도 수집이 완료됐다. 변경 전후 원주가·파생 가격 파일 해시와 두 지수의 날짜·종가·수익률이 같았다.

백테스트는 `evaluation.benchmark_file`에 지정한 동결 지수 파일을 사용한다. 학습 수집기가 pykrx KOSPI 1001과 KOSDAQ 2001을 검증해 `benchmarks/`에 저장한다. 백테스트 실행 중 지수를 다시 다운로드하지 않는다.

FDR은 `shared/requirements.txt`에서 제거하고 `serving/requirements.txt`에 남겼다. 서빙 전환이 완료될 때까지 종목 마스터와 기존 서빙 가격 대체 어댑터만 사용한다. 가격 어댑터는 `shared/data/prices.py`로 옮겨 동작을 보존했고 학습 수집기는 해당 어댑터를 호출하지 않는다.

## v3 실험 결과를 pack으로 내보내기

현재 활성 모델은 기본 161개 + 수급 9개 입력의 H5/H20이다. 현재 처리 계약과 같은 공식 사건표로 완료한 H5·H20 run의 디렉터리를 지정한다. 수급 모델을 내보낼 때는 `--with-flows`를 붙인다.

```bash
python -m experiments.export.refresh_pack \
  --h5-result "workspace/experiments/runs/<H5 run 이름>" \
  --h20-result "workspace/experiments/runs/<H20 run 이름>" \
  --pack-id YOUR_NEW_PACK_ID --activate
```

동일 pack ID를 덮어쓰지 않는다. 모델·OOS 예측·raw/processed·학습 피처의 출처, 공식 사건표 해시, 파일 SHA-256과 가격·피처 일치를 검증한다. `--activate`는 기존 서빙 가격 계산과의 일치도 요구한다. 실패 시 활성 설정을 바꾸지 않는다.

pack은 `workspace/serving/packs/`에 생성한다. `--activate`는 `serving/config.local.yaml`만 갱신하고 이전 설정을 pack 옆에 보존한다. 프리뷰용 삼성전자 입력도 출처와 해시를 기록해 `workspace/serving/inputs/`로 명시적으로 복사한다. 원격 Release 업로드·Supabase 발행은 실행하지 않는다.

```bash
python -m experiments.export.refresh_pack \
  --h5-result "workspace/experiments/runs/<수급 H5 run 이름>" \
  --h20-result "workspace/experiments/runs/<수급 H20 run 이름>" \
  --with-flows --pack-id YOUR_NEW_FLOW_PACK_ID --activate
```

수급 모델 export는 학습 피처 저장소의 170개 입력 순서·값·결측을 공통 builder와 대조한다. 수급이 완전했던 연구 표본에서 나온 OOS 예측으로 유사 사례를 다시 만든다.
