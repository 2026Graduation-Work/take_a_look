# 이동·검증 기록

브랜치: `refactor/chart-shared-v3-workspaces`. 원본 기준 커밋 `095584b`, 파일 이동 커밋 `59f9ca2`. 미커밋 chart 작업을 기준 커밋으로 보존했으며 chart 밖의 사용자 변경은 포함하지 않았다.

## 보존

이동 직전 48,034개 파일, 33,073,679,216바이트를 기록했다. 이동 직후 전체 SHA-256이 일치했다. Git에서 제외된 데이터·모델도 로컬 workspace에 그대로 남겼다. 삭제로 보이는 Git diff는 추적 해제이며 물리적 데이터 삭제가 아니다.

요약·경로 매핑은 [migration.json](migration.json), 추가 연구 테스트 이동은 [test-migration.json](test-migration.json)에 기록했다. 전체 파일별 이전/이후 경로·크기·해시는 `workspace/archive/pre-refactor/migration-files.json`에 있다. 전체 기록 SHA-256은 요약에 고정했다. 원본 source·문서와 사용자 diff는 `workspace/archive/pre-refactor/originals/`, `tracked.patch`에 보존했다. 이미 작업 트리에서 삭제돼 있던 processed 삼성전자 샘플은 `deleted-tracked/`에 Git 원본도 복구해 보관했다.

## 기준과 검증

변경 전 Ruff 통과. pytest는 217개 통과, 9개 KRX 로그인 DNS 실패, 3개 건너뜀(107.38초)이었다. 원문 로그는 `workspace/archive/pre-refactor/baseline-tests.log`에 있다.

새 검증은 이전 serving 출력 대신 보존된 최신 v3를 기준으로 한다. 가격·VWAP·정규화·Sigma·모델 입력 순서·값을 대조한다. 정상, 수정가격, 정규장 미관측, 수급 결측의 골든 값은 원본 v3 source에서 생성했으며 거래일 누락은 거부한다.

mock 수집→동일 가격 처리→피처→미래 정보가 필요한 연구 라벨→소규모 LightGBM 학습→공용 평가→H5/H20 pack→serving 추론을 실행한다. 설정 불일치는 Storage 연결 전에 막는다. 미래 입력 차단·정수 수량·상폐 처리·부분 발행 실패 검증은 기존 테스트를 유지했다.

serving 단독 검증은 실험 디렉터리 없이 shared·serving만 복사하고 실험 전용 패키지 없이 설치해 수행한다. CI도 experiments/serving 설치를 별도 matrix로 실행한다. 테스트는 공급자 proxy와 HTTP를 로그인 전에 mock하여 실네트워크 사용을 거부한다.

## 기본 모델 전환 시 로컬 검사

전체 chart pytest: **282 passed, 3 skipped**, 117.01초. serving 단독 설치·격리 디렉터리: **98 passed**, 9.60초. Ruff는 레포 루트에서 통과했다. 프런트엔드는 `node node_modules/next/dist/bin/next build --webpack`으로 통과했다. 환경의 Turbopack 소켓 제한 때문에 Webpack을 사용했으며 프런트엔드 코드는 수정하지 않았다.

로그는 `workspace/archive/validation-20261010/`과 `workspace/archive/validation-20261011/`에 보존한다. 삭제 후보와 확인 범위는 [DELETION_CANDIDATES.md](DELETION_CANDIDATES.md)에 있다. 파일은 삭제하지 않았다.

## 기본 모델 전환 기록

로컬 pack과 전체 실자료 대조 결과는 [local-pack-validation.json](local-pack-validation.json)에 기록한다. 모델·예측·데이터·학습 피처·builder 출처와 SHA-256, 실제 기간·제외 사유, 추론 검증을 포함한다. `serving/config.local.yaml`만 전환하고 이전 pack·설정은 보존한다. 원격 배포·Release 업로드·운영 발행은 별도 단계다.

전체 1,019종목·2,368,027행의 가격·피처 및 학습 피처 저장소를 대조했다. 정규장 미관측 34,967행과 일봉 범위 밖 VWAP 4,478행도 임의 변환 없이 일치했다. 허용 오차는 rtol=1e-8, atol=1e-10이다.

새 로컬 pack: `kospi_shared_v3_train2023_2025_20261011`. H5 1,666,324건, H20 1,651,754건의 관측 완료 사례를 생성했다. 미래 관측 미완료로 각각 4,805건·19,375건을 제외했다. 예측 기간은 2019-01-07~2026-10-06이며 2026은 부분 연도다.

같은 운영 입력으로 삼성전자 2026-10-06 프리뷰를 일반 환경과 serving 단독 환경에서 실행했다. 배치 ID `c315ebe06c0fcb1d9d7cc335cbadd0b1fce17aba78c29e3315182c3c6593a42b`가 같았고 유사 사례는 H5 8,806건·H20 6,175건이었다. 공개 JSON 스키마 검사를 통과했으며 Supabase 저장·발행은 수행하지 않았다.

최신 main `6c7aa26`의 chart 원본 159개·109,421,098바이트도 별도 보존했다. 상세 해시·보존 경로는 [main-sync.json](main-sync.json)에 있다. 공개 JSON 계약과 기여도·히스토그램, 시장 상태, Storage 재시도·panel 저장, 운영 명령은 main 동작을 유지했다. 연구 v3 구축·학습 경로는 검증된 현재 구현을 유지한다. 이전 브랜치의 중복 번호 SQL은 [sql-migration.json](sql-migration.json)의 기록대로 archive로 이동했다. DB 마이그레이션은 실행하지 않았다.

PR #266의 experiments·serving·profiling·text CI와 CodeQL이 통과했다. PR 연동 Vercel 프리뷰는 자동 생성됐고, 모델 Release 업로드·운영 chart 발행·DB 적용은 수행하지 않았다. 상장 구간까지 통합한 최종 공통 builder 계약 SHA-256은 `64abc83dce3eb7164c1e94cab75484c757684fce0c56342863dc7b01baca3fed`이다. 기존 최초 전환 pack과 main 통합 후 pack을 모두 보존했다.

상장 구간·종목 목록·관리종목·벤치마크 공급자 호출도 shared로 추출했다. 원래 최신 v3 함수와 AST가 일치한다. 일일 수집은 확인된 개별 상장일 이전을 요구하지 않으며 알 수 없거나 미래인 상장일은 거부한다. 신규 상장 종목·공급자 실패 조합을 포함해 검증했다.

## 현재 활성 수급 H5/H20

사용자 후속 지시에 따라 기본 pack을 보존하고 수급 포함 H5/H20으로 로컬 활성 모델을 전환했다. pack은 `kospi_shared_v3_flow_train2023_2025_20261011`이며 기본 161개 + 수급 9개, 총 170개 입력이다. 공통 builder 계약은 기존 `64abc83dce3eb7164c1e94cab75484c757684fce0c56342863dc7b01baca3fed`와 같다.

H5 원본 run은 `sliding_2016_2026_h5_flow_kospi_ecb00d84b00063ca`, H20은 `sliding_2016_2026_h20_flow_kospi_b3bdd182d898e80f`다. 2023~2025 학습 모델과 2019-01-07~2026-10-06 OOS 예측의 SHA-256을 검증해 재사용했다. 재학습·추가 튜닝은 수행하지 않았다. H5 예측 hash `1e5d6bd8`, H20 `7dd23966`이며 모델·예측·데이터·피처 저장소의 전체 해시는 `local-pack-validation.json`에 기록했다.

전체 1,019종목·2,368,027행에 대해 가격·기본 피처는 보존된 v3 processed와, 수급 9개는 실제 학습 피처 저장소와 비교했다. 값·순서·결측 패턴이 일치했다. 비교 열은 186개, 허용 오차는 rtol=1e-8, atol=1e-10이다. 연구 표본에서 수급 결측 때문에 제외된 적격 행은 465,436개다. 초기 관측 부족을 포함한 전체 수급 불완전 행은 541,055개다.

각 모델의 OOS 예측은 1,437,834행이다. 완료된 유사 사례는 H5 1,433,666건, H20 1,420,993건이며 후속 관측 미완료 4,168건·16,841건을 제외했다. 2026은 10월 6일까지의 부분 연도다. 입력 수급 결측을 0으로 채우면 export 검증이 실패하고, 활성화용 프리뷰에 수급 결측이 있으면 이전 설정을 유지한다. 일일 serving 역시 `flow_window_incomplete`로 해당 종목·모델의 추론을 제외한다.

최종 chart 테스트: 286 passed, 3 skipped, 118.92초. Ruff 통과. 기존 mock 수집→학습→공용 평가→pack→serving E2E를 기본·수급 양쪽으로 실행하고 수급 값·결측 대조 및 활성화 차단 검증을 추가했다. 로그는 `workspace/archive/validation-flow-20261011/`에 보관한다.

기본 pack과 설정은 새 pack의 `previous_active_pack.json`에 보존했다. 두 pack의 공통 builder가 같으므로 설정을 복구한 뒤 검증하면 되돌릴 수 있다. 원격 Release 업로드·운영 발행·DB 적용은 수행하지 않았다.

삼성전자 2026-10-06 수급 모델 프리뷰를 일반·serving 단독 환경에서 실행했다. 두 H5/H20 snapshot이 모두 available이었으며 배치 ID `44ada62a04f45518b1d875197427f7bd2586bcacc96d92fb4670d8380c1593a6`와 유사 사례 H5 7,023건·H20 5,021건이 일치했다. 공개 JSON 계약 검사를 통과했으며 Supabase 저장·발행은 수행하지 않았다.
