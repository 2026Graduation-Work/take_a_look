# 실행 방법

현재 계산·DB·화면 데이터 규격은 [README.md](README.md)에 있다. 모든 명령은 `backend/analysis/chart`에서 실행한다. `serving/data/`는 Git에서 제외한 작업 공간이다.

## 1. 로컬 Supabase에서 저장된 실제 입력 확인

저장소 루트에서 Docker가 실행 중인지 확인하고 로컬 Supabase를 시작한다. CLI 전역 설치는 필요 없다.

```bash
docker info
npx --yes supabase@latest start
npx --yes supabase@latest status
```

`start`는 저장소 migration을 적용한다. `status`에 표시된 Project URL과 Secret key(구 CLI에서는 service_role key)를 사용한다. `db reset`은 데이터를 지우므로 확인용 실행에 사용하지 않는다. 모델과 과거 표본 pack `serving/data/packs/hold2022_2024_wf2019_2025_v1/`은 Git에 포함돼 있다. 미리보기에 쓰는 `serving/data/raw/005930.parquet`, `serving/data/processed/005930.parquet`는 별도로 준비해야 한다.

```bash
cd backend/analysis/chart
python3 -m venv /tmp/chart-serving-venv
source /tmp/chart-serving-venv/bin/activate
python -m pip install -r serving/requirements.txt
export SUPABASE_URL=http://127.0.0.1:54321
read -rsp '로컬 Secret 또는 service_role key: ' SUPABASE_SECRET_KEY; echo
export SUPABASE_SECRET_KEY
python -m serving.local_preview --compute-only
python -m serving.local_preview --publish
```

첫 명령은 DB 없이 snapshot을 계산한다. 둘째 명령은 가격 DB·비공개 피처 Storage·H5/H20 공개 snapshot을 기록한다. 기본 입력은 **2026-06-12 삼성전자** 캐시이며, 기존 가공 피처 계산 버전은 미확인이다. `--as-of`는 raw와 processed 양쪽에 있는 날만, `--code`는 해당 두 캐시 파일이 있는 종목만 허용한다. 이 미리보기는 최신 KRX 수집을 검증하지 않는다.

로컬 Studio SQL Editor(보통 `http://127.0.0.1:54323`)에서 확인한다.

```sql
select count(*) from public.chart_prices where stock_code = '005930';
select as_of, builder_id, storage_path from public.chart_feature_snapshots where stock_code = '005930';
select id, as_of, status, pack_id from public.chart_batches order by created_at desc limit 3;
select horizon, payload->'distribution'->>'sample_count' as cases,
       payload->'distribution'->>'stock_count' as stocks
from public.latest_chart_signal_snapshots where stock_code = '005930' order by horizon;
```

검증 당시 가격 162행, 피처 1건, 공개 snapshot 2행이었고 H5/H20 사례 수는 각각 699/615건이었다. `main` 프론트는 아직 이 공개 view를 읽지 않으므로 DB에 보이는 것과 화면에 보이는 것을 구분한다. 작업 후 저장소 루트에서 `npx --yes supabase@latest stop`으로 서비스를 종료할 수 있다.

## 2. 최신 거래일 수집·추론

거래일 **18:00 KST 이후** KRX 접근과 인터넷이 가능한 환경에서 실행한다. 현재 runner는 전체 KOSPI를 처리한다. `--dry-run`도 가격·피처를 Supabase에 저장하지만 새 공개 batch는 만들지 않는다.

```bash
cd backend/analysis/chart
python -m serving.run_daily --dry-run
python -m serving.run_daily --publish
```

`SUPABASE_URL`, `SUPABASE_SECRET_KEY`와 활성 pack도 필요하다. `KRX_ID`, `KRX_PW`가 있으면 pykrx가 KRX 로그인을 시도한다. 계정이 없어도 인증 없는 조회를 시도하므로 필수 입력으로 막지 않는다. 로그인 실패 메시지만으로 성공·실패를 판단하지 말고 실제 거래일·가격 데이터와 실행 결과를 확인한다. 같은 날 입력을 재실행하면 batch ID가 같고, 가격이나 pack이 바뀌면 새 batch가 된다. `--as-of YYYY-MM-DD`는 해당 날짜까지 새로 수집한다. `--replay`를 함께 쓰면 그날의 종목 목록과 가격이 저장된 경우에만 실행한다. 휴장일에는 당일 batch가 생성되지 않는다. 수집 또는 공개 전에 실패하면 이전 공개 batch가 남는다.

지난 거래일의 실제 가격으로 수집·피처·추론·히스토그램을 시험할 때는 **로컬 Supabase**에서만 아래 옵션을 쓴다. `--code`를 빼면 KRX의 지정일 KOSPI 목록 전체를 수집하므로 먼저 한 종목으로 확인한다. 단일 종목 테스트는 현재 KRX 종목명을 쓰며, 지정일 가격이 있어야 진행한다. 결과는 `serving/data/batches/<batch-id>/`에 쓰고, 새로 받은 가격·피처는 로컬 Supabase에 저장한다. 기존 종목 목록은 덮어쓰지 않고 공개 batch도 발행하지 않는다.

```bash
python -m serving.run_daily --as-of 2026-09-21 --historical-test --code 005930 --dry-run
```

기존 로컬 미리보기에서 저장한 2026-06-12 가격에는 실제 VWAP이 없는 행이 있다. 이 데이터는 일일 피처 입력 검증을 통과하지 않으므로 과거 재실행 테스트에 사용하지 않는다.

## 3. 새 pack과 Actions

현재 H5/H20 모델과 과거 표본은 `serving/data/packs/<pack-id>/`에 Git으로 추적한다. Actions는 checkout한 pack을 `python -m serving.pack validate`로 해시·모델 피처 순서·클래스·표본 H를 확인한다. GitHub Release 업로드는 필요 없다. `config.yaml`의 `active_pack.pack_id`가 선택할 디렉터리를 정한다.

새 pack은 `backend/analysis/chart`에서 아래처럼 생성한다. H5/H20을 함께 만들고 보고서의 표본 수와 제외 사유를 확인한 뒤 pack 디렉터리와 `config.yaml`의 새 ID를 같은 PR에 포함한다.

```bash
python -m serving.build_pack --pack-id PACK_ID --output serving/data/packs \
  --model-h5 H5_MODEL.txt --model-h20 H20_MODEL.txt \
  --predictions-h5 H5_OOS.parquet --predictions-h20 H20_OOS.parquet \
  --processed-dir PROCESSED_DATA_DIR
python -m serving.pack validate --path serving/data/packs/PACK_ID
```

Actions secrets는 `SUPABASE_URL`, `SUPABASE_SECRET_KEY`가 필요하다. KRX 인증이 필요한 조회가 있으면 `KRX_ID`, `KRX_PW`도 설정한다. `.github/workflows/chart-serving.yml`은 평일 **18:30 KST** 예약과 수동 실행을 제공한다. 설정 작성과 실제 실행 성공은 다르다. 현재 원격 migration, Actions 수동·예약 실행은 확인되지 않았다. 운영 Supabase migration 적용 뒤 수동 실행으로 공개 batch ID, H5/H20 두 snapshot, 기준일을 확인해야 한다. 서비스 키는 브라우저나 로그에 넣지 않는다.

## 2026-09-30: 인증 점검과 화면 연결 시험

- 저장소 secrets는 `KRX_ID`, `KRX_PW`다. 로컬 `.env`의 `_1` 계정을 사용할 때는
  두 값을 각각 이 환경 변수로 전달한 뒤 실행한다. 파일 자체는 커밋하지 않는다.
- `python -m serving.run_daily --diagnose`: 로그인·공식 거래일·KOSPI 유니버스·삼성전자
  수정/비수정 가격과 거래대금만 검사한다. DB에는 쓰지 않는다.
- 예약 실행은 `--dry-run`으로 가격·피처를 보관하고 추론 결과를 검증한다.
  결과는 14일간 Actions artifact에 보관한다. 공개 배치를 교체하지 않는다.
- 자정 이후 지연 실행도 전날 확정 입력을 새로 수집한다. 저장된 입력만 재사용하려면
  `--as-of YYYY-MM-DD --replay`를 명시한다. 휴장일에는 새 배치를 만들지 않는다.
- 화면 연결 시험은 `python -m serving.publish_preview`로 검증하고 `--publish`로 발행한다.
  Actions 수동 실행의 `publish_preview=true`도 같은 명령이다. `previews/2026-09-21`의
  삼성전자 두 기간 snapshot만 발행한다. 기존 모델의 학습 입력 정합성 검증은 미완료다.
- 프론트는 공개 batch ID `18e7a9f66fa63d4b6e0439c9189828e26f4496c128d17e79755d6711e0f3dc48`를
  명시해 조회한다. `NEXT_PUBLIC_CHART_PREVIEW_BATCH_ID` 환경 변수가 없으면 이 공개 ID가
  기본값이다. 빈 문자열로 설정하고 재배포하면 시험 화면을 끈다.
  테스트 batch는 공개용 출력만 담으며 원본 가격 테이블이나 전체 유니버스를 덮어쓰지 않는다.
- 시험 화면은 기존 종목 목록·상세 UI를 유지한다. 목록은 20거래일, 상세의 기존 기간
  비교 칸에는 5/20거래일 모델에서 가장 높은 분류 점수의 방향을 표시한다.
  모델 근거 탭에는 LGBM의 피처별 상방 원점수 기여값만 표시하며 뉴스·재무·성향을 섞지 않는다.
  모든 시험 결과에 모델 검증 전·기준일을 적는다. 순위·10거래일 값은 만들지 않는다.
- 재학습(#107)은 별도 작업이다. 계산 공유(#169)는 serving 피처·추론을 사용하며
  실험 CLI의 기존 출력 열과 모델 경로 옵션을 유지한다.
