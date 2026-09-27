# 실행 방법

현재 계산·DB·화면 데이터 규격은 [README.md](README.md)에 있다. 모든 명령은 `backend/analysis/chart`에서 실행한다. `serving/data/`는 Git에서 제외한 작업 공간이다.

## 1. 로컬 Supabase에서 저장된 실제 입력 확인

저장소 루트에서 Docker가 실행 중인지 확인하고 로컬 Supabase를 시작한다. CLI 전역 설치는 필요 없다.

```bash
docker info
npx --yes supabase@latest start
npx --yes supabase@latest status
```

`start`는 저장소 migration을 적용한다. `status`에 표시된 Project URL과 Secret key(구 CLI에서는 service_role key)를 사용한다. `db reset`은 데이터를 지우므로 확인용 실행에 사용하지 않는다. `serving/data/packs/hold2022_2024_wf2019_2025_v1/`, `serving/data/raw/005930.parquet`, `serving/data/processed/005930.parquet`가 있어야 한다. 다른 컴퓨터라면 파일을 별도로 준비해야 하며 **로컬 pack이 있으면 GitHub Release가 필요 없다.**

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
read -rp 'KRX ID: ' KRX_ID
read -rsp 'KRX password: ' KRX_PW; echo
export KRX_ID KRX_PW
python -m serving.run_daily --dry-run
python -m serving.run_daily --publish
```

`SUPABASE_URL`, `SUPABASE_SECRET_KEY`와 활성 pack도 필요하다. 같은 날 입력을 재실행하면 batch ID가 같고, 가격이나 pack이 바뀌면 새 batch가 된다. 과거 날짜 `--as-of YYYY-MM-DD`는 Supabase에 그날의 종목 목록과 해당 날짜까지의 가격이 저장된 경우에만 실행한다. 휴장일에는 당일 batch가 생성되지 않는다. 수집 또는 공개 전에 실패하면 이전 공개 batch가 남는다.

## 3. 새 pack과 Actions

`config.yaml`의 `active_pack`이 pack ID·Release 태그·첨부 파일명·압축 파일 SHA-256을 고정한다. 로컬에 같은 pack 디렉터리가 있으면 다운로드를 생략한다. 새 Actions runner에는 로컬 pack이 없으므로 GitHub Release 첨부 파일에서 내려받는다.

```bash
python -m serving.build_pack --pack-id PACK_ID --output serving/data/packs \
  --model-h5 H5_MODEL.txt --model-h20 H20_MODEL.txt \
  --predictions-h5 H5_OOS.parquet --predictions-h20 H20_OOS.parquet \
  --processed-dir PROCESSED_DATA_DIR
sha256sum serving/data/packs/PACK_ID.tar.gz
gh release create RELEASE_TAG serving/data/packs/PACK_ID.tar.gz --title "Chart pack PACK_ID" --notes "H5/H20 serving pack"
```

pack 생성 보고서의 원본 예측 수·사용 표본 수·제외 사유를 확인한다. 기존 태그라면 `gh release upload`를 사용한다. 새 pack으로 바꿀 때 H5/H20을 함께 교체하고 `config.yaml` 네 값을 한 번에 변경한다. 이전 설정으로 되돌리면 이전 pack을 다시 쓸 수 있다.

Actions secrets는 `SUPABASE_URL`, `SUPABASE_SECRET_KEY`, `KRX_ID`, `KRX_PW`가 필요하다. `.github/workflows/chart-serving.yml`은 평일 **18:30 KST** 예약과 수동 실행을 제공한다. 설정 작성과 실제 실행 성공은 다르다. 현재 Release 업로드, 원격 migration, Actions 수동·예약 실행은 확인되지 않았다. 운영 Supabase migration 적용 뒤 수동 실행으로 공개 batch ID, H5/H20 두 snapshot, 기준일을 확인해야 한다. 서비스 키는 브라우저나 로그에 넣지 않는다.
