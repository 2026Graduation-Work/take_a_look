# PR #186 후속: 전체 과거 뉴스 적재

요청 승인 범위: 기존 UI와 schema를 유지하고 2016-01-01~2026-10-04의 6종목 원본·분석 결과를 확인, 기존 점수를 재사용, 준비된 데이터를 Supabase에 중복 없이 추가한다. 초기 범위는 로컬 검증까지이며, 이후 사용자 요청으로 push/PR 생성을 승인받았다. merge/deploy는 하지 않는다.

1. 원본 파일의 날짜 범위를 스캔하고 누락 구간을 기록한다. filename coverage는 다운로드 범위이지 기사 존재의 보장이 아니다.
2. `value_pipeline/historical_backfill.py`에 연도별 진행·원자적 분석 캐시·재시작 CLI를 추가한다. DB 일별 행(기사 없음 포함)을 우선 재사용하고 검증된 기존 KR-FinBERT CSV는 없는 날짜에만 추가한다. 나머지는 기존 관련성·감성 코어를 사용하며 FinBERT 실패 시 사전 점수 적재를 금지한다. 캐시는 원본 fingerprint에 묶고 성공 전에 DB 기록 여부를 확정하지 않는다.
3. PostgREST GET pagination과 chunked insert-ignore를 추가한다. historical daily/article 고유키로 기존 행을 보존하고 Live에는 쓰지 않는다. 기존 parent track는 최근 정상 수집 창으로 보존한다.
4. 원본 다운로드 범위 내 DB missing / 저장된 0기사 / 점수 존재 날짜를 나눠 종목·연도별 보고서를 생성한다. 파일 누락을 0기사로 바꾸지 않는다.
5. 일별 오늘 Live 연결, 오늘만 filled dot, 날짜 텍스트·최대 10개 창·스크롤 탐색과 월/연 기사수 가중평균을 테스트한다. 로컬 build/lint/backend suite 및 독립 리뷰를 진행한다.
6. 실제 DB 적재와 재조회 검증 후 확인 주소/브랜치/누락·검증 보고서를 전달한다.

검증: source coverage/CSV 재사용/실패 후 cache resume/기존 DB와 Live 불변/고유키 중복/DB missing 분류의 backend 테스트; provider 가중평균과 pagination 테스트; Playwright 기간·날짜·scroll·Live marker 시나리오; `ruff check .`, `pytest`, `pnpm build`.

## 실행 중 결정·검증 기록

- 기존 `supabase_sync backfill-historical` 초기화 계약은 유지한다. 전체 기간 추가 적재는 별도 `historical_backfill` CLI로 실행한다. 독립 리뷰에서 신규 부모가 없는 초기 환경의 회귀를 지적했기 때문이다.
- 추가 적재는 기존 검증된 BigKinds/KR-FinBERT 부모만 받아 최근 정상 수집 창을 보존한다. 부모가 없으면 오류 코드 `historical_parent_required`로 중단하며 임의 요약을 생성하지 않는다.
- 캐시는 월 단위로 저장하되 진행·결과는 연도별로 묶는다. 업로드 실패 전에 완료된 분석을 재사용하고 DB 재조회로 실제 저장 날짜를 확인한다.
- 장시간 계산용 historical 배치 크기는 32로 고정한다. 모델·점수 산식은 동일하며 캐시 버전에도 배치 크기를 넣는다. 기존 Live/일반 historical 수집의 기본 배치 16은 유지한다.
- 삼성전자 2022년 원본이 사용자가 작업 중 추가한 파일로 확인돼 전체 적재에 포함됐다. 원본 66개가 모두 2016-01-01~2026-10-04 범위를 갖는다.
- 독립 리뷰 지적(부모 초기화, 캐시 범위 완전성, 일부 종목 audit 실패, 기존 bootstrap 회귀)을 보완했고 재리뷰에서 남은 actionable finding은 없다.
- 검증: backend 157 tests, frontend unit 87 tests, opt-in 전체 기간 브라우저 테스트, lint, Webpack production build 통과. 기본 Turbopack 빌드는 로컬 처리 포트 권한 오류로 검증되지 않았다.
- 실제 로컬 삼성전자 화면에서 시작일 2016.01.01·오늘 Live 단일 마커·브라우저 오류 0을 확인했다. 전체 적재 종료 후 DB 보존·연도별 행 수·재실행 0-write 검증을 추가한다.

- 최종: 6종목 각각 2016-01-01~2026-10-04 3,930행, 총 23,580 historical 일별 행. 원본 범위/DB 날짜 누락 0개. 기존 모든 historical·Live 행 보존 및 고유키 중복 없음. 전체 재실행 DB 쓰기 0회. 실제 6종목 화면 일·월·연 탭 2016년 시작 탐색 확인. 독립 Python 대조로 월·연 가중평균 확인. 상세 보고서: `docs/validation/2026-10-06-sentiment-full-history.md`.

- 후속 사용자 요청: 오늘 Live의 저장된 일별 결과를 월·연 가중평균에 포함하고 날짜를 2026.10/2026으로 표시한다. 프론트 unit 최종 91개, 브라우저 회귀/lint/Webpack build/독립 재리뷰 통과.
