# Serving 운영

기준일: 2026-11-27 (#511)

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

### 가격 입력 기대값 검증

`serving/tests/test_price_input_golden.py`는 빈 임시 캐시에서 `fetch_prices`의 KRX 우선 경로를 실행한다. pykrx 호출에는 고정 응답을 넣고 거래일 달력은 테스트 데이터로 제공한다. KRX 인증과 네트워크 연결 없이 날짜별 수정 OHLC, VWAP, 수정배율, 플래그를 기대값과 비교한다. 값이 다르면 입력 경우, 날짜, 열을 출력한다.

삼성전자 2018-05-04 액면분할과 거래정지 사례의 원본 OHLC와 거래량·거래대금은 KRX 기록에서 가져왔다. 수정 응답은 네이버 수정종가를 기준으로 합성했다. 정규장 OHLC 미제공 사례는 두 응답 모두 합성했다. 이 사례는 원본과 수정 응답의 시가·고가·저가·거래량·거래대금을 다르게 넣어 응답 선택을 검증한다.

변환 결과를 의도적으로 바꿨다면 아래 명령으로 `serving/tests/fixtures/price-input-golden.json`을 다시 만든다. 달라진 경우, 날짜, 열과 변경 이유를 PR에 적는다.

```bash
python -m pip install pytest
python -m serving.tests.price_input_golden
```

## 일일 실행과 재실행

```bash
python -m serving.pack download --config serving/config.yaml
python -m serving.run_daily --dry-run
# 별도 운영 발행 단계에서만:
python -m serving.run_daily --publish
```

KRX 인증과 `SUPABASE_URL`, `SUPABASE_SECRET_KEY`가 필요하다. 기본 활성 설정은 로컬 파일이 있으면 `serving/config.local.yaml`, 없으면 `serving/config.yaml`이다. `CHART_SERVING_CONFIG`를 지정하면 그 파일만 쓴다. 배포 작업은 설정을 명시한다.

당일 가격은 한국 시간 18시 이후에 확정된 날짜만 실행한다. 날짜를 생략한 실행이 공통 KRX 일정상 휴장일이면 DB 입력 조회 전에 `holiday`로 종료한다. 명시적인 과거 날짜 재실행에는 보관된 입력이 계속 필요하다. 첫 수집은 2016년과 확인된 개별 종목 상장일 중 늦은 날짜부터 전체 관측 이력, 이후 갱신은 최근 240일과 상장일 중 늦은 날짜부터다. 상장 구간은 shared의 동일 공급자 함수로 검증하며 확인되지 않은 상장일은 거부한다. 상장 메타데이터도 운영 캐시에 별도로 보관한다. 겹치는 구간은 최신 응답으로 교체한다. 과거 rolling 상관의 수치 재현을 위해 전체 이력을 유지한다.

Storage에는 날짜별 최근 원본 최대 61행과 전체 입력 해시를 보관하고, 서빙 계약과 기대값 파일 해시로 키를 만든 계산 완료 피처를 함께 저장한다. 전체 현재 이력은 운영 가격 저장소에 남긴다. 재실행은 새 키를 먼저 조회하고, 필요한 경우 팩이 기록한 이전 계약 키로 같은 입력 해시를 조회한다. 두 키에 해당하는 피처가 없으면 중단한다.

공개 차트 가격은 최근 60거래일이다. 같은 수정종가 입력과 거래일을 확인한 경우에만 `prices.event_basis`에 최근 최대 250일 로그수익률의 표본 표준편차와 첫 표시일의 직전 가격을 넣는다. 기준을 저장한 archive는 보관 가격과 객체의 해시를 검증해 재실행한다. 운영 가격 이력에 수정 기준을 확인한 첫 날짜를 기록한다. 이 기록이 없거나 겹친 종가가 달라지면 새 응답 구간부터 다시 확인한다. 확인된 구간의 최소 60개, 최대 250개 로그수익률을 변동 기준에 쓴다. 이전 60행 archive에 기록된 기준이 없을 때도 가격만 제공한다. 운영 공개 전에 서빙 계약 추가를 팀에서 확인한다.

과거 날짜의 `--as-of YYYY-MM-DD` 재실행은 보관된 운영 universe·달력·raw 입력을 요구한다. 공급자 재조회나 연구 캐시 fallback은 하지 않는다. 달력은 동일 공통 거래일 검증을 다시 적용한다. 과거 운영 입력이 없으면 중단한다. 부분 snapshot 업로드 실패는 공개 publish RPC를 호출하지 않으며 이전 공개 batch를 유지한다.

`--historical-test --as-of ... --code ... --dry-run`은 loopback HTTP Supabase에서만 사용할 수 있는 별도 수집 점검 경로다. 운영 재실행과 다르며 원격 발행은 금지한다. 프리뷰의 `--publish`도 loopback HTTP에서만 허용한다.

## pack 전환과 되돌리기

새 팩은 `python -m experiments.export.refresh_pack ... --activate`로 검증 후 로컬에서 활성화한다. 새 팩을 만들 때 `golden/<pack_id>.json`을 팩에 포함하며 manifest와 로컬 활성 설정에 SHA-256을 기록한다. 운영 설정을 새 팩으로 바꿀 때 팩에 든 기대값 파일을 `serving/golden/`에도 추가한다. 이미 운영 중인 팩의 기대값 파일은 고정한다. 피처 계산 결과가 달라지면 새 팩에서 새 기대값을 만든다.

`serving/config.yaml`은 수급 포함 팩 `kospi_shared_v3_flow_train2023_2025_20261014`의 기존 릴리스와 `serving/golden/<pack_id>.json`을 지정한다. 기본 161개와 수급 9개 입력을 쓴다. 필요한 수급 입력이 결측이면 해당 모델·종목 추론을 `flow_window_incomplete`로 제외한다.

팩 로딩은 builder ID, 가격 기준, 전처리 설정, H5/H20 모델의 피처 기대값을 확인한다. 비교가 실패하면 입력 경우와 달라진 피처 이름을 출력한다. 압축 파일, 모델, 과거 사례, 달력은 각 SHA-256으로 검증한다. 기대값 검사는 수정 가격과 VWAP가 준비된 입력부터 시작한다. KRX 응답을 수정 가격·VWAP로 변환하는 단계는 위의 [가격 입력 기대값 검증](#가격-입력-기대값-검증)이 맡는다.

팩 내보내기는 고정한 학습 산출물과 입력 파일의 해시를 검증한다. 연구 계약의 엔진, 가격 기준, 처리 설정, 피처 순서가 현재 내보내기 계약과 맞아야 한다. 팩의 `processing_contract`와 `builder/` 사본은 검증 당시 사용한 구현의 이력을 남긴다.

종목 목록 캐시는 날짜, 파일 해시와 서빙 계약을 확인해 재사용한다. 상장 구간 판정 코드만 바꾸면 같은 날짜의 캐시는 그대로 적중한다. 해당 날짜를 다시 검증할 때는 `cache/listings/`의 대상 날짜 캐시와 JSON 메타데이터를 지운 뒤 다시 수집한다.

새 로컬 프리뷰 입력 manifest는 `feature_cache_key`를 쓴다. 이전 manifest의 `processing_contract_sha256`도 팩에 맞는 해시라면 읽을 수 있다.

이전 팩으로 되돌릴 때는 해당 버전의 서빙 코드와 설정을 함께 복원한다. 그 팩을 새 서빙 코드에서 사용하려면 해당 팩의 검증된 기대값 파일과 해시가 필요하다. 이전 팩은 GitHub Release의 `chart-serving-*` 태그에 보존돼 있다.

### 현재 운영 팩 기대값 재현

기대값 파일이 있는 checkout의 chart 디렉터리에서 생성 도구의 커밋을 찾는다.

```bash
golden_source=$(git log -1 --diff-filter=A --format=%H -- serving/golden/kospi_shared_v3_flow_train2023_2025_20261014.json)
```

같은 셸에서 `16be22b1ad6f5c2d65a2dcbe8c18262d1004cab8`에 만든 별도 worktree의 chart 디렉터리로 이동한다. 기존 계약 해시를 먼저 확인한다. Python 3.12.16, pandas 2.3.3, NumPy 2.5.5를 사용한다.

```bash
python -m pytest serving/tests/test_regular_session_close.py::test_shared_builder_still_matches_the_active_pack
git restore --source "$golden_source" --worktree -- experiments/export/golden.py shared/golden.py
python -m experiments.export.golden --pack-id kospi_shared_v3_flow_train2023_2025_20261014 --inputs shared/tests/fixtures/v3-golden.json --out serving/golden/kospi_shared_v3_flow_train2023_2025_20261014.json
shasum -a 256 serving/golden/kospi_shared_v3_flow_train2023_2025_20261014.json
```

SHA-256은 `d85f39143b021238b21176a806ec80b413937baf99e724993afad53efbf83983`이다. 입력은 기존 네 경우와 봉 모양·거래대금을 바꾼 합성 경우다. 이 경우의 고정 식별자는 `corporate_event`다. 고가와 선택 행은 봉·롤링 피처를, 거래대금은 수급 피처를 검증한다. 수정 배율과 원시 OHLC는 피처 빌더가 입력으로 소비하는 값에 포함되지 않는다. 생성은 재현용 worktree에서 실행한다.

시장 상태·수급·종목 마스터·보존 정리는 별도 명령이다. `python -m serving.supply`, `python -m serving.stock_master`, `python -m serving.retention`.

기사·공시 기본 보존 기간은 90일이다. `python -m serving.retention --article-days 120 --dry-run`은 KST 기준 D-120보다 오래된 기사·공시의 날짜와 건수만 조회한다. 운영 용량과 기사 보관 권한을 확인한 뒤 담당자가 120일 전환을 결정한다.

## 원격 모델 확인

Daily chart serving의 `model_check=true`는 마지막 확정 거래일의 삼성전자 가격과 최근 20거래일 수급을 공급자에서 읽어 H5/H20 실제 추론을 확인한다. DB 저장 객체를 생성하지 않으며 발행·보존 정리·수급 저장·종목 마스터 단계도 실행하지 않는다. 결과는 Actions artifact에만 남긴다. 수급 결측으로 추론이 제외되면 점검도 실패한다. 이 점검은 과거 운영 발행 재실행이 아니다.

```bash
python -m serving.model_check
```
