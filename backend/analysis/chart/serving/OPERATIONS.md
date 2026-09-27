# Chart serving 운영 절차

이 문서는 `serving/`만 복사한 실행 환경과 `.github/workflows/chart-serving.yml`에 적용한다. 실행에 필요한 모델과 과거 표본은 하나의 model pack이다. 활성 pack은 `config.yaml`의 `active_pack`으로 지정한다.

## 배포 준비

1. 새 serving migration을 Supabase에 적용하고 공개 snapshot 조회 권한을 확인한다. DB 적용 여부는 코드 배포와 별도로 기록한다.
2. `README.md`의 `python -m serving.build_pack` 명령으로 H5/H20 모델과 2019~2025 walk-forward 자료를 묶는다. 생성 보고서의 원본 예측 수, 사용 가능한 표본 수, 제외 사유를 확인한다.
3. pack 압축 파일을 GitHub Release 첨부 파일로 올린다. `config.yaml`의 `active_pack.release_tag`, `asset_name`, `sha256`, `pack_id`를 해당 파일에 맞춘다. SHA-256은 압축 파일 전체의 값이다. H5/H20은 항상 함께 교체한다.
4. Actions repository secrets에 `SUPABASE_URL`, `SUPABASE_SECRET_KEY`를 등록한다. KRX 비수정 가격·거래대금과 거래일 조회에는 `KRX_ID`, `KRX_PW`가 필요하다. 서비스 키를 프론트 환경변수나 로그에 넣지 않는다.
5. `Daily chart serving`을 수동 실행해 첫 배치를 확인한다. 실행 성공, DB 반영, 상세 화면 표시는 각각 따로 확인한다.

pack 생성 후 release 업로드 예시는 다음과 같다. 태그가 이미 있으면 `gh release upload`만 사용한다.

```bash
sha256sum serving/data/packs/PACK_ID.tar.gz
gh release create RELEASE_TAG serving/data/packs/PACK_ID.tar.gz --title "Chart pack PACK_ID" --notes "H5/H20 serving pack"
```

## 로컬 실행

```bash
cd backend/analysis/chart
python -m pip install -r serving/requirements.txt
export CHART_SERVING_DATA_DIR="$PWD/serving/data"
export GITHUB_REPOSITORY=2026Graduation-Work/Stock_Prediction_v2
# 비공개 Release라면 GH_TOKEN도 설정한다.
python -m serving.pack download --config serving/config.yaml
python -m serving.run_daily --dry-run
python -m serving.run_daily --publish
```

로컬에서 `serving/data/packs/<pack_id>/`를 이미 생성했다면 `serving.pack download`는 생략한다. Release는 새 Actions runner가 pack을 받을 때 사용한다.

`--publish`에는 `SUPABASE_URL`과 `SUPABASE_SECRET_KEY`가 필요하다. `--as-of YYYY-MM-DD`를 지정하면 그 날짜를 재실행한다. 과거 날짜의 정확한 종목 목록과 입력이 Supabase에 없으면 runner가 이유를 출력하고 종료한다. 새 runner의 로컬 `serving/data/`는 작업 공간이며 가격·피처 상태의 정본은 Supabase다.

## 예약과 재실행

워크플로는 평일 09:30 UTC, 즉 18:30 KST에 예약되어 있다. GitHub Actions의 예약 시작 시각은 지연될 수 있으므로 로그의 실제 기준일을 확인한다. 수동 실행에서는 선택적으로 `as_of` 날짜를 입력한다. 예약·수동 실행은 하나의 concurrency 그룹을 사용한다.

pack 다운로드는 실패 시 최대 세 번 시도한다. runner는 휴장일에 당일 배치를 만들지 않는다. 가격 전체 수집이나 모델 로드, 필수 저장이 실패하면 공개 전 단계에서 중단하고 직전 공개 배치를 유지한다. 같은 날짜·pack·입력·계산 버전으로 재실행하면 동일 batch ID에 저장하며, 입력 정정 또는 pack 교체 뒤에는 새 batch ID를 공개한다.

로그에서 기준일, pack ID, 처리 건수, 실패 단계, 공개 batch ID를 확인한다. 일부 종목의 가격이 없으면 해당 종목의 `unavailable` 상태와 건수를 확인한다. 비공개 Storage의 피처 파일은 계산 버전·기준일·입력 해시로 찾고, 공개 화면은 snapshot만 읽는다.

## 교체와 복구

새 pack을 GitHub Release에 올리고 `active_pack` 네 값을 바꾼 PR을 배포한다. 이전 pack으로 되돌릴 때는 이전 release 태그·첨부 파일명·SHA-256·pack ID를 설정에 다시 지정한다. 매번 수동 실행으로 H5/H20이 같은 pack에서 왔는지, snapshot 건수가 대상 종목 수의 두 배인지 확인한다.

공개 실패 후에는 이전 배치가 계속 조회되는지 확인하고 같은 입력으로 다시 실행한다. 이미 공개한 잘못된 배치는 batch 철회 절차를 사용한다. DB migration 철회는 별도 백업과 영향 확인 후 진행한다.

## 확인 기록

| 단계 | 상태 | 근거 |
|---|---|---|
| 코드 구현 | 로컬 완료 | chart Ruff와 chart/serving 테스트 31개 통과, pack 검증·단일 종목 실제 모델 추론 완료 |
| Actions 설정 작성 | 완료 | 평일 18:30 KST 예약, 수동 날짜 입력, 단일 실행 설정 및 YAML 검사 |
| 실제 DB migration 적용 | 미확인 | Supabase 적용 결과 필요 |
| 첫 실제 batch 공개 | 미확인 | batch ID와 조회 결과 필요 |
| 수동 Actions 실행 | 미확인 | workflow run URL 필요 |
| 예약 실행 | 미확인 | 예약 run URL 필요 |

현재 환경의 `gh auth status`는 토큰 무효를 보고한다. Release 업로드와 수동 workflow 실행은 GitHub 인증이 복구된 뒤 수행해야 한다.
이 환경에는 Supabase secret key 값과 KRX 로그인 정보가 없고 KRX/Naver 호스트 이름 조회가 실패한다. DB migration 적용과 최신 가격 수집은 이 환경에서 검증하지 못했다.
