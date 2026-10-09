# 배포 절차

활성 pack: `kospi_uniform_v3_train2023_2025_20261009` (기본 H5/H20, 2023~2025 학습).
검증된 archive는 [GitHub Release](https://github.com/2026Graduation-Work/take_a_look/releases/tag/chart-serving-kospi_uniform_v3_train2023_2025_20261009)에 업로드했다. Actions는 config의 SHA256으로 다운로드를 검증한다.

PR 머지 후 `Daily chart serving`을 실행한다. 첫 배포에서 과거 거래일을 새로 수집하려면 `as_of`에 확정 거래일을 입력하고 `replay=false`로 실행한다. `replay=true`는 새 builder로 저장된 입력만 재사용한다. `dry_run=true`는 입력을 저장·검증하지만 공개 batch를 바꾸지 않는다. 예약 실행은 평일 18:30 KST이며 휴장일에는 게시하지 않는다.

```bash
gh workflow run chart-serving.yml --ref main -f as_of=2026-10-08 -f dry_run=true
gh run list --workflow chart-serving.yml --limit 3
# 검증 완료 후 동일 날짜를 게시한다.
gh workflow run chart-serving.yml --ref main -f as_of=2026-10-08
```

KRX_ID, KRX_PW, SUPABASE_URL, SUPABASE_SECRET_KEY는 저장소 Secrets에 등록되어 있다. 공개 batch는 H5/H20 전체 snapshot 검증 후 원자적으로 교체하며, 실패하면 기존 batch가 유지된다. 수급은 개인·기관합계·외국인의 마지막 20 거래일 원본과 1/5/20일 피처를 수집·저장한다. **현재 기본 모델은 수급 피처를 점수에 사용하지 않는다.**

전체 가격 이력은 2016년부터 유지해 학습 입력을 재현한다. 첫 실행은 전체 조회가 필요하다. 이후 최근 240일을 갱신하고 수정가격 변화가 발견되면 전체를 다시 받는다. 일자별 재실행에는 현재 피처와 60개 관측 가격을 보관하며, 전체 이력을 날짜마다 복제하지 않는다.

## 로컬 검증과 pack 재생성

## 수정된 기본 모델 pack 재생성과 검증

현재 pack은 로컬에서 생성·활성화했다. 재학습 없이 완료된 연구 실행의 2026 fold 모델과 저장된 walk-forward 예측으로 재생성할 수 있다.

```bash
python -m serving.refresh_local_pack \
  --h5-result experiments/results/sliding_2016_2026_h5_kospi_739166ce0d474177 \
  --h20-result experiments/results/sliding_2016_2026_h20_kospi_1734679be11d0369 \
  --pack-id kospi_uniform_v3_train2023_2025_20261009 --activate
python -m serving.local_preview --compute-only
```

동일한 검증된 pack이 이미 있으면 재사용한다. 새 pack에는 공식 calendar, 2023~2025 학습 기간, 모델·예측 해시, 2019~2026 walk-forward 표본, 피처 동등성 증거가 들어간다. 기존 학습/수집 캐시와 이전 pack은 지우지 않는다. `previous_active_pack.json`으로 이전 설정을 확인할 수 있다. 이전 pack으로 실제 되돌리려면 피처 생성 코드도 그 버전에 맞춰야 하며, 새 daily 경로는 구형 피처 pack을 거부한다.

새 runner에는 로컬 pack이 없으므로 업로드된 Release에서 다운로드한다. 이 코드 변경은 PR로 배포한다. `serving/config.yaml`은 새 태그와 archive SHA를 이미 가리킨다. Release를 준비하기 전에 새 설정만 원격에 반영하면 pack 다운로드가 실패한다.

```bash
gh release create chart-serving-kospi_uniform_v3_train2023_2025_20261009 \
  serving/data/packs/kospi_uniform_v3_train2023_2025_20261009.tar.gz \
  --title "Corrected KOSPI basic H5/H20 models" \
  --notes "Uniform raw OHLC adjustment and actual VWAP; trained 2023-2025."
```

기본 모델을 교체한 상태이므로 수급은 수집·피처 계산·저장되지만 기본 모델 점수에는 쓰이지 않는다. 수급 모델 적용에는 해당 모델과 과거 표본을 함께 담은 별도의 pack이 필요하다.

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


## 첫 전체 이력 수집

가격 전체 이력을 가진 종목이 충분하지 않으면, 첫 실행은 KRX 날짜별 전체시장 비수정 OHLC 응답을 종목 간 공유한다. 기존 private history가 없는 종목이 `max(20, 전체 종목 수 // 10)`개를 초과할 때 사용한다. 종목별 수정가격 조회와 결합할 때 날짜가 완전히 일치하는 원본만 재사용한다. 조회 실패/누락은 개별 원본 조회로 보충하며, 각 날짜 응답은 runner 내부 SHA 검증 캐시에 보존한다. 별도 로컬 가격 데이터 archive는 공개 Release에 업로드하지 않는다. Actions 제한은 첫 실행에 맞춰 240분이다.
