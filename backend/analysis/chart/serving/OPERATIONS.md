# Serving 운영

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

당일 가격은 한국 시간 18시 이후에 확정된 날짜만 실행한다. 날짜를 생략한 실행이 공통 KRX 일정상 휴장일이면 DB 입력 조회 전에 `holiday`로 종료한다. 명시적인 과거 날짜 재실행에는 보관된 입력이 계속 필요하다. 첫 수집은 2016년과 확인된 개별 종목 상장일 중 늦은 날짜부터 전체 관측 이력, 이후 갱신은 최근 240일과 상장일 중 늦은 날짜부터다. 상장 구간은 shared의 동일 공급자 함수로 검증하며 확인되지 않은 상장일은 거부한다. 상장 메타데이터도 운영 캐시에 별도로 보관한다. 겹치는 종가·원종가·거래량·거래대금의 변경을 확인하면 전체 이력을 다시 받는다. 과거 rolling 상관의 수치 재현을 위해 전체 이력을 유지한다.

Storage에는 날짜별 최근 원본 60행과 전체 입력 해시를 보관하고, 공통 builder 계약 해시가 붙은 계산 완료 피처를 함께 저장한다. 전체 현재 이력은 운영 가격 저장소에 남긴다. 재실행은 해당 계약의 피처가 없으면 중단한다.

과거 날짜의 `--as-of YYYY-MM-DD` 재실행은 보관된 운영 universe·달력·raw 입력을 요구한다. 공급자 재조회나 연구 캐시 fallback은 하지 않는다. 달력은 동일 공통 거래일 검증을 다시 적용한다. 과거 운영 입력이 없으면 중단한다. 부분 snapshot 업로드 실패는 공개 publish RPC를 호출하지 않으며 이전 공개 batch를 유지한다.

`--historical-test --as-of ... --code ... --dry-run`은 loopback HTTP Supabase에서만 사용할 수 있는 별도 수집 점검 경로다. 운영 재실행과 다르며 원격 발행은 금지한다. 프리뷰의 `--publish`도 loopback HTTP에서만 허용한다.

## 로컬 전환과 되돌리기

새 pack은 `python -m experiments.export.refresh_pack ... --activate`로 검증 후 활성화한다. pack·tar.gz·builder 소스·이전 설정은 보존한다. pack 내부 `processing_contract`에 설정·코드 SHA-256이 있고 `builder/`에는 해당 공통 구현 원본이 있다.

같은 공통 builder와 호환되는 이전 pack으로 돌아갈 때는 그 pack을 검증한 뒤 보관된 설정을 `serving/config.local.yaml`로 복원한다. 다른 builder의 pack은 설정만 되돌리면 실행되지 않는다. 기록된 builder 코드와 pack을 함께 복구해야 한다.

전환 이전 v3 구현의 기준 커밋은 `095584b`, 원본은 `workspace/archive/pre-refactor/originals/`이다. 해당 커밋의 별도 checkout에서 호환 구현과 이전 설정을 사용하고 `CHART_SERVING_DATA_DIR`를 보관된 운영 workspace로 지정하면 이전 pack을 검증할 수 있다. 현재 builder에 이전 모델만 끼우지 않는다.

`serving/config.yaml`은 수급 포함 pack `kospi_shared_v3_flow_train2023_2025_20261014`을 사용한다. GitHub Release의 tar.gz SHA-256은 `20da6a515edc32f5e906116f748484bac0fd224220ad4d9b9c0e1561f9b88086`다. 다운로드 후 builder 계약과 모델·사례 파일 해시를 모두 검사한다. 10/14 전환은 NumPy 날짜 단위 명시만 바꿨으며 H5/H20 모델·사례 파일 SHA-256은 10/11 pack과 같다. 바로 이전 수급 pack으로 복구할 때는 PR #313 머지 커밋 `9cd2f75174b657c4956d18e81493674f3306bf2a`의 builder와 `serving/config.yaml`을 함께 복원한다. 상세 동등성 검증은 `../docs/TIMEDELTA_COMPATIBILITY.md`다.

시장 상태 갱신·수급·종목 마스터·기존 보존 정책은 최신 main 동작을 유지했다. 별도 운영 명령은 `python -m serving.supply`, `python -m serving.stock_master`, `python -m serving.retention`이다. 이번 작업에서 실행하거나 발행하지 않았다. 이전 표시용 preview는 호환 pack이 있어야 검증·발행할 수 있다.

main 통합 직전 공통 v3 코드 기준은 `e5a0fe4`이며 최초 전환 전 기준은 `095584b`다. 과거 로컬 활성화에서 생성한 `previous_active_pack.json`에는 당시 이전 설정·처리 계약·builder 소스 경로가 있다. 10/14 원격 pack은 아래 명시된 Git 커밋·설정으로 복구한다. 이전 pack의 builder와 해당 코드 기준을 함께 사용한다.

상장 구간 통합 직전 builder 기준 커밋은 `0c474ff`다. `20261010_main` pack으로 되돌릴 때는 이 코드와 보존된 이전 로컬 설정을 함께 복원한다.

현재 로컬 활성 pack은 수급 포함 H5/H20이며 기본 161개 + 수급 9개 입력을 사용한다. 필요한 수급 입력이 결측이면 `flow_window_incomplete`로 해당 모델·종목 추론을 제외한다. 기본 pack `kospi_shared_v3_train2023_2025_20261011`은 이전 builder와 함께 보존한다. 현재 날짜 단위 명시 builder에서는 설정만 복원하면 계약 검사가 실패한다. 원격 기본 설정도 동일한 수급 pack을 사용한다.

## 원격 모델 확인

Daily chart serving의 `model_check=true`는 마지막 확정 거래일의 삼성전자 가격과 최근 20거래일 수급을 공급자에서 읽어 H5/H20 실제 추론을 확인한다. DB 저장 객체를 생성하지 않으며 발행·보존 정리·수급 저장·종목 마스터 단계도 실행하지 않는다. 결과는 Actions artifact에만 남긴다. 수급 결측으로 추론이 제외되면 점검도 실패한다. 이 점검은 과거 운영 발행 재실행이 아니다.

```bash
python -m serving.model_check
```

초기 원격 운영 성공 기록은 `37899919906`, 호환 코드 기준은 `7bb84b69345e51c0badf9aefcd7132037173bdc3`다. 이전 pack `kospi_uniform_v3_train2023_2025_20261009`와 Release는 보존한다. 이 pack으로 복구하려면 위 코드와 그 커밋의 설정을 함께 복구한다. 현재 shared builder에서 이전 원격 설정만 복원하면 호환성 검사로 중단한다.
