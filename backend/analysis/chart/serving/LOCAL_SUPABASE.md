# 로컬 Supabase에서 실제 자료 확인

원격 Supabase 계정 없이 Docker와 Supabase CLI로 실행한다. 첫 실행은 이미 저장된 삼성전자 실제 가격과 기존 가공 피처를 사용한다. 기존 가공 피처의 계산 버전은 확인되지 않았으므로 결과는 `legacy_processed_unverified_preview`로 식별된다. 최신 가격·실제 VWAP 피처를 검증하려면 아래의 별도 일일 실행을 사용한다.

## 1. 로컬 DB 시작

저장소 루트에서 Docker 데몬을 실행한다. WSL2에서는 Windows의 Docker Desktop을 열고 해당 배포판의 WSL Integration을 켠 뒤 `docker info`가 성공해야 한다. [Supabase CLI](https://supabase.com/docs/guides/local-development/cli/getting-started)는 `npx`로 실행할 수 있으므로 전역 설치나 `supabase init`이 필요 없다. 저장소에는 `supabase/config.toml`과 `0001`~`0006` migration이 있다.

```bash
docker info
npx --yes supabase@latest start
npx --yes supabase@latest status
```

`start`가 migration과 `seed.sql`을 적용한다. `status`의 Project URL, Secret key(이전 CLI에서는 service_role key), Publishable key(이전 CLI에서는 anon key)를 확인한다. 로컬 Studio 주소는 보통 `http://127.0.0.1:54323`이다. 포트가 다른 경우 `status` 출력값을 따른다. `db reset`은 로컬 DB 데이터를 지우므로 재초기화할 때만 사용한다.

## 2. 저장된 실제 가격으로 H5/H20 화면 보기

Git에서 제외된 `serving/data/packs/hold2022_2024_wf2019_2025_v1/`, `serving/data/raw/005930.parquet`, `serving/data/processed/005930.parquet`가 있는지 확인한다. 다른 컴퓨터에는 이 파일을 별도로 복사해야 한다. GitHub Release는 이 로컬 실행에 필요 없다.

```bash
cd backend/analysis/chart
python3 -m venv /tmp/chart-serving-venv
source /tmp/chart-serving-venv/bin/activate
python -m pip install -r serving/requirements.txt pytest

export SUPABASE_URL=http://127.0.0.1:54321
read -rsp '로컬 Secret 또는 service_role key: ' SUPABASE_SECRET_KEY; echo
export SUPABASE_SECRET_KEY

python -m serving.local_preview --compute-only
python -m serving.local_preview --publish
```

첫 명령은 DB 없이 snapshot을 계산해 `serving/data/batches/<batch-id>/`에 저장한다. 둘째 명령은 로컬 DB에 가격을 upsert하고 피처 Parquet을 비공개 Storage에 올린 후 H5/H20 snapshot을 공개한다. 출력의 `as_of`, `sample_counts`, `batch_id`를 확인한다. 기본 입력은 저장된 삼성전자 자료의 마지막 가공일인 **2026-06-12**이다. `--as-of`는 raw와 processed 양쪽에 있는 날짜만 허용한다. `--code`로 종목을 바꿀 수 있으나 두 캐시 파일이 필요하다.

로컬 Studio의 SQL Editor에서 다음을 실행해 저장 결과를 확인한다.

```sql
select count(*) as price_rows from public.chart_prices where stock_code = '005930';
select as_of, builder_id, storage_path from public.chart_feature_snapshots where stock_code = '005930';
select id, as_of, status, pack_id from public.chart_batches order by created_at desc limit 3;
select horizon, payload->'distribution'->>'sample_count' as sample_count,
       payload->'distribution'->>'stock_count' as stock_count
from public.latest_chart_signal_snapshots where stock_code = '005930' order by horizon;
```

마지막 조회가 H5와 H20 두 행을 반환해야 한다. 로컬 실행 검증에서는 2026-06-12 기준 각각 699건과 615건의 과거 사례가 선택됐다. 입력 피처는 기존 가공 자료이므로 이 수치는 최신 VWAP 계산 결과나 운영 배치 검증으로 해석하지 않는다.

H20의 615건은 당시 **상방 출력이 현재 값에서 ±0.01**, 당시 Sigma가 **현재 값에서 ±5%**인 여러 종목의 예측이다. 각각의 예측일 수정종가와 그 종목의 20번째 후속 실거래행 수정종가로 실제 수익률을 계산하므로 손실 사례도 포함한다. 기본 히스토그램은 선택된 수익률의 최솟값부터 최댓값까지 12개 동일 폭으로 나눈다. 이 미리보기의 최소값은 약 −41.19%, 최대값은 약 +154.27%여서 한 구간의 폭이 약 16.29%p다. 표시할 때 경계는 소수 첫째 자리로 반올림할 수 있다. 하방·중립 모델 출력은 공개 snapshot에 포함되지만 과거 표본 선택에는 사용하지 않는다.

상방·하방·중립 출력은 실제 H5/H20 LightGBM 추론 결과다. 기여도는 상방 클래스의 내부 원점수 기여도이며 확률 변화량이 아니다. 과거 수익률 히스토그램은 추론값 자체가 아니라, 추론값과 비슷했던 과거 예측들의 **관측된 결과**다.

현재 `main` 프론트는 이 공개 snapshot을 조회하지 않는다. 상세 화면의 히스토그램은 프론트 내부 데모 자료다. **로컬 DB 공개 성공과 실제 화면 표시를 같은 완료 단계로 기록하지 않는다.** 프론트 코드는 담당 팀이 관리하며, 백엔드는 `FRONTEND_HANDOFF.md`의 차트 필드와 공개 view를 제공한다.

기존 `StockDetail` 타입의 차트 관련 필드에 맞춘 전달 JSON은 다음과 같이 만든다.

```bash
python -m serving.frontend_handoff \
  --snapshots serving/data/batches/<batch-id>/snapshots.json \
  --output serving/data/batches/<batch-id>/frontend_handoff.json
```

## 3. 거래일에 최신 가격까지 확인

이 단계는 KRX 로그인 정보와 인터넷이 필요하다. KRX가 당일 자료를 확정한 거래일 **18:00 KST 이후**에 실행한다. 일일 runner는 현재 전체 KOSPI 종목을 수집하며, 날짜를 과거로 지정하면 해당 날짜의 종목 목록·가격이 이미 DB에 있어야 한다.

```bash
cd backend/analysis/chart
read -rp 'KRX ID: ' KRX_ID
read -rsp 'KRX password: ' KRX_PW; echo
export KRX_ID KRX_PW
python -m serving.run_daily --dry-run
python -m serving.run_daily --publish
```

`--dry-run`도 로컬 Supabase의 가격·피처를 갱신하지만 공개 snapshot은 만들지 않는다. `--publish`가 성공하면 `latest_chart_signal_snapshots` view에서 새 기준일을 읽을 수 있다. 위 SQL을 다시 실행해 `chart_prices`의 최근 거래일, 새 `chart_batches` 상태, H5/H20 snapshot을 확인한다. 이 경로는 기존 가공 캐시 대신 당일 수집 가격과 실제 VWAP으로 피처를 계산한다.

작업을 마치면 저장소 루트에서 `npx --yes supabase@latest stop`으로 로컬 서비스를 종료한다. 로컬 DB 데이터는 유지된다.
