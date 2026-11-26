# Serving 운영

기준일: 2026-11-24

모든 명령은 chart 디렉터리에서 실행한다. 운영 파일은 기본 `workspace/serving/`에 저장하며 `CHART_SERVING_DATA_DIR`로 운영 저장소만 명시적으로 바꿀 수 있다.

## 환경과 로컬 검증

```bash
python -m venv workspace/serving/.venv
source workspace/serving/.venv/bin/activate
python -m pip install -r serving/requirements.txt
python -m serving.pack validate --path workspace/serving/packs/kospi_shared_v3_flow_train2023_2025_20261014
python -m serving.local_preview --code 005930 --as-of 2026-10-06 --compute-only
```

프리뷰는 `workspace/serving/inputs/raw/`의 명시적으로 내보낸 운영 입력과 해당 출처·해시 manifest만 읽는다. 연구 데이터셋 자동 탐색은 없다. `--compute-only`는 Supabase에 접속하지 않고 결과를 운영 `batches/`에 기록한다.

## 일일 실행과 재실행

```bash
python -m serving.pack download --config serving/config.yaml
python -m serving.run_daily --dry-run
# 별도 운영 발행 단계에서만:
python -m serving.run_daily --publish
```

KRX 인증과 `SUPABASE_URL`, `SUPABASE_SECRET_KEY`가 필요하다. 기본 활성 설정은 로컬 파일이 있으면 `serving/config.local.yaml`, 없으면 `serving/config.yaml`이다. `CHART_SERVING_CONFIG`를 지정하면 그 파일만 쓴다. 배포 작업은 설정을 명시한다.

당일 가격은 한국 시간 18시 이후에 확정된 날짜만 실행한다. 날짜를 생략한 실행이 공통 KRX 일정상 휴장일이면 DB 입력 조회 전에 `holiday`로 종료한다. 명시적인 과거 날짜 재실행에는 보관된 입력이 계속 필요하다. 첫 수집은 2016년과 확인된 개별 종목 상장일 중 늦은 날짜부터 전체 관측 이력, 이후 갱신은 최근 240일과 상장일 중 늦은 날짜부터다. 상장 구간은 shared의 동일 공급자 함수로 검증하며 확인되지 않은 상장일은 거부한다. 상장 메타데이터도 운영 캐시에 별도로 보관한다. 최근 구간은 새 값으로 덮어쓰고, 과거 rolling 상관의 수치 재현을 위해 저장 이력 앞부분을 유지한다. 원천 값이 달라져도 전체 이력을 다시 조회하지 않는다. 수정계수 변경은 아래 기준으로 처리한다.

Storage에는 날짜별 최근 원본 60행과 전체 입력 해시를 보관하고, 공통 builder 계약 해시가 붙은 계산 완료 피처를 함께 저장한다. 전체 현재 이력은 운영 가격 저장소에 남긴다. 재실행은 해당 계약의 피처가 없으면 중단한다.

과거 날짜의 `--as-of YYYY-MM-DD` 재실행은 보관된 운영 universe·달력·raw 입력을 요구한다. 공급자 재조회나 연구 캐시 fallback은 하지 않는다. 달력은 동일 공통 거래일 검증을 다시 적용한다. 과거 운영 입력이 없으면 중단한다. 부분 snapshot 업로드 실패는 공개 publish RPC를 호출하지 않으며 이전 공개 batch를 유지한다.

`--historical-test --as-of ... --code ... --dry-run`은 loopback HTTP Supabase에서만 사용할 수 있는 별도 수집 점검 경로다. 운영 재실행과 다르며 원격 발행은 금지한다. 프리뷰의 `--publish`도 loopback HTTP에서만 허용한다.

## 권리 이벤트와 수정 가격 기준

`raw-history-v3/{code}.parquet`와 `chart_prices`는 같은 수정 가격 기준을 쓴다. 매일 겹치는 날짜의 `새 AdjustmentFactor / 저장 AdjustmentFactor`를 비교한다. 가격 반올림 허용오차는 `check_adjustment_steps`와 같은 수준이다. 날짜별 비율의 허용 구간이 겹치는지 확인하고, 공통 구간 안의 비율로 보정한다.

- 비율이 일정하고 1과 다르면 저장 이력 앞부분의 `Open`, `High`, `Low`, `Close`, `VWAP`, `AdjustmentFactor`에 그 비율을 곱한다. `Raw*`, `Volume`, `Amount`는 유지한다. 해당 종목은 보정한 전체 이력을 `chart_prices`에 500행 단위로 upsert한다. 평소에는 최근 240일만 upsert한다.
- 보존할 앞부분이 있는데 유효한 겹침을 확인하지 못하거나, 겹치는 비율의 허용 구간이 일치하지 않으면 해당 종목을 `price_adjustment_basis_inconsistent`로 제외하고 사유를 기록한다. 가격 저장소를 쓰지 않는다. 보존할 앞부분이 없고 겹치는 거래가 없으면 새 이력으로 전체 대체한다. 모든 종목을 제외하면 이전 게시 배치를 유지한다.
- 전체 DB upsert 전에는 Storage에 기존 가격을 그대로 저장하면서 parquet 속성 `price_rebase_pending`을 남긴다. DB upsert가 끝난 뒤 새 가격으로 Storage를 교체하고 속성을 지운다. 중간에 요청이 실패하면 다음 실행은 이 속성을 보고 전체 upsert를 다시 시도한다. 공급자가 이전 수정 기준을 반환해 비율이 1이 되어도 전체 이력을 맞춘다. `price_adjustment_basis`의 `rebased` 로그에서 보정 비율, upsert 행 수, 요청 수를 확인한다.

종목 마스터는 최근 250개 수익률 표본 안의 수정계수 경계를 검사한다. 허용오차를 넘는 계수 변화와 함께 수정종가의 절대 로그수익률이 반올림 여유를 넘어서 원종가보다 커지면 해당 종목의 변동성·백분위를 계산하지 않고 `price_adjustment_basis_inconsistent` 진단을 남긴다. 등급은 기존 변동성 미확인 규칙에 따라 1이다. 정상 분할에서 원종가만 급변하고 수정종가는 연속이면 계산한다. 가격만으로 권리일과 원천 정정을 완전히 구분할 수 없어, 배당락일의 큰 시장 움직임도 미확인으로 분류할 수 있다.

이미 두 저장소에 같은 잘못된 경계가 남아 겹침 비율이 1이면 이 처리로 과거 오염을 복구하지 못한다. `chart_prices`와 `raw-history-v3`는 전체 이력을 유지하며 보존 기간이나 행 삭제를 바꾸지 않는다. 운영 복구 전에는 읽기 전용으로 영향 종목·경계일·행 수를 확인하고, [무료 한도](../../../../docs/ops/free-tier-budget.md)의 최신 잔여량과 함께 팀 확인을 받는다. 승인 후 검증된 공급자 이력으로 해당 종목의 DB와 Storage를 함께 맞추고 종목 마스터를 다시 계산한다.

[회귀 증거·요청량·운영 복구 계획](PRICE_BASIS_VALIDATION.md)을 함께 확인한다.

## pack 전환과 되돌리기

새 pack은 `python -m experiments.export.refresh_pack ... --activate`로 검증 후 활성화한다. pack 내부 `processing_contract`에 설정·코드 SHA-256이 있고 `builder/`에는 해당 공통 구현 원본이 있다.

`serving/config.yaml`은 수급 포함 pack `kospi_shared_v3_flow_train2023_2025_20261014`을 사용한다. 기본 161개 + 수급 9개 입력을 쓰며, 필요한 수급 입력이 결측이면 `flow_window_incomplete`로 해당 모델·종목 추론을 제외한다. GitHub Release의 tar.gz SHA-256은 `20da6a515edc32f5e906116f748484bac0fd224220ad4d9b9c0e1561f9b88086`다. 다운로드 후 builder 계약과 모델·사례 파일 해시를 모두 검사한다.

이전 pack으로 되돌릴 때는 그 pack을 만든 커밋의 builder 코드와 `serving/config.yaml`을 함께 복원한다. 현재 builder에 설정만 되돌리면 계약 검사에서 중단된다. 이전 pack은 GitHub Release의 `chart-serving-*` 태그에 모두 보존돼 있다.

시장 상태·수급·종목 마스터·보존 정리는 별도 명령이다. `python -m serving.supply`, `python -m serving.stock_master`, `python -m serving.retention`.

## 원격 모델 확인

Daily chart serving의 `model_check=true`는 마지막 확정 거래일의 삼성전자 가격과 최근 20거래일 수급을 공급자에서 읽어 H5/H20 실제 추론을 확인한다. DB 저장 객체를 생성하지 않으며 발행·보존 정리·수급 저장·종목 마스터 단계도 실행하지 않는다. 결과는 Actions artifact에만 남긴다. 수급 결측으로 추론이 제외되면 점검도 실패한다. 이 점검은 과거 운영 발행 재실행이 아니다.

```bash
python -m serving.model_check
```
