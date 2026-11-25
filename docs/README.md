# 문서 색인

`docs/`에는 지금도 맞는 참조 문서만 둡니다. 아래 규칙을 지키면 문서가 다시 쌓이지 않습니다.

- 작업 계획, 브랜치 검증 기록, QA 결과, 에이전트 실행 로그는 PR 본문이나 이슈에 씁니다. 레포에 커밋하지 않습니다.
- 연구 결과는 `research/<주제>/` 폴더 하나에 README와 재현에 필요한 데이터만 둡니다.
- 새 문서를 추가하면 같은 PR에서 이 색인에 한 줄을 넣습니다.
- `python .github/scripts/check_doc_links.py`가 깨진 링크와 색인에 없는 문서를 찾습니다.

지운 기록은 태그 [`v1.1.0`](https://github.com/2026Graduation-Work/take_a_look/tree/v1.1.0/docs)에 남아 있습니다.

## 시작

| 문서 | 내용 |
|---|---|
| [../README.md](../README.md) | 서비스 소개, 빠른 시작, 구조 |
| [../AGENTS.md](../AGENTS.md) | 공통 지침·제품 원칙·운영과 안전·작업별 정본 |
| [CONTRIBUTING.md](CONTRIBUTING.md) | 블록 구분·브랜치·커밋·PR·머지·훅 변경 절차 |
| [../CHANGELOG.md](../CHANGELOG.md) | 버전별 변경과 초기 기록(서비스명, 레포 이름) |

## 운영

| 문서 | 내용 |
|---|---|
| [auth-setup.md](auth-setup.md) | 계정 로그인 설정(Supabase, Vercel), 사람이 할 일 |
| [erd.md](erd.md) | Supabase 테이블 |
| [security.md](security.md) | RLS와 권한 요약 |
| [security/2026-10-audit.md](security/2026-10-audit.md) | 권한 기준선 감사 |
| [ops/free-tier-budget.md](ops/free-tier-budget.md) | 무료 한도 예산표와 주간 감시 기준(2027-02-01까지) |
| [ops/backups.md](ops/backups.md) | 백업 위치와 규칙 |
| [stock-master-rules.md](stock-master-rules.md) | 종목 마스터 위험 등급, 표시 규칙, 임계값 |
| [disclosure-kinds.md](disclosure-kinds.md) | DART 공시 제목 유형표 |

## 데이터와 계약

| 문서 | 내용 |
|---|---|
| [chart-data-contract.md](chart-data-contract.md) | 화면이 차트 서빙 결과에서 실제로 읽는 테이블, 뷰, payload |
| [data-inventory.md](data-inventory.md) | 화면 수치의 출처와 실데이터 여부(2026-09-24 기준, 갱신 필요) |
| [../backend/analysis/chart/serving/README.md](../backend/analysis/chart/serving/README.md) | H5, H20 serving 구조, 공개 계약, 검증 상태 |
| [../backend/analysis/chart/serving/OPERATIONS.md](../backend/analysis/chart/serving/OPERATIONS.md) | H5, H20 실행과 DB 발행 절차 |
| [../backend/analysis/chart/experiments/backtest/EXECUTION_SPEC.md](../backend/analysis/chart/experiments/backtest/EXECUTION_SPEC.md) | 백테스트 체결 순서, 장벽 기준, 비용, 회귀 방지 테스트 |
| [../backend/analysis/text/VALUE_PIPELINE_VALIDATION.md](../backend/analysis/text/VALUE_PIPELINE_VALIDATION.md) | 가치투자 파이프라인 출력 검증 절차 |

## 화면과 브랜드

| 문서 | 내용 |
|---|---|
| [../frontend/DESIGN.md](../frontend/DESIGN.md) | 화면 규칙. 값은 `frontend/app/globals.css`의 `@theme` |
| [brand/README.md](brand/README.md) | 로고 후보, 선택 이유, 사용 규칙 |

## 연구와 결정

| 문서 | 내용 |
|---|---|
| [research/psychology-ab-2019-2025/README.md](research/psychology-ab-2019-2025/README.md) | 심리 피처 A/B, 2019~2025 표본 밖 평가 |
| [research/psych-candidates/README.md](research/psych-candidates/README.md) | 심리지표 후보 P1~P5 1차 선별, 2단계 사전 등록, 가격 밖 데이터 조사 |
| [research/psych-candidates/stage2-plan.md](research/psych-candidates/stage2-plan.md) | 심리 후보 2단계 실험 사전 등록(목록, 설정, 판정 기준) |
| [research/flow-161-vs-170-2019-2026/README.md](research/flow-161-vs-170-2019-2026/README.md) | 기본 모델과 수급 모델 비교 |
| [research/horizon-selection.md](research/horizon-selection.md) | 1주, 4주를 남기고 H10을 뺀 근거 |
| [research/2026-06-selection-report.md](research/2026-06-selection-report.md) | H5, H10, H20 라벨 배수 후보 비교와 최종 후보 선정(2026-06-29) |
| [research/2026-06-progress-roadmap.md](research/2026-06-progress-roadmap.md) | 6월 실험 기록. Multiplier Screener, 기간 확장, Factor Attribution, Factor-Neutral Backtest |
| [research/metric-choice.md](research/metric-choice.md) | 성적표 지표 선택 |
| [research/usability-test-plan.md](research/usability-test-plan.md) | 사용성 평가 계획 |
| [research/persona-walkthrough-2026-10.md](research/persona-walkthrough-2026-10.md) | 페르소나 시나리오 점검 |
| [research/source-display.md](research/source-display.md) | 기준 시점과 출처 표시 조사 |
| [research/oss-scan.md](research/oss-scan.md) | 오픈소스와 무료 공급원 조사, 채택 결정 |
| [product/beginner-gap.md](product/beginner-gap.md) | 초보 투자자가 어려워하는 점 |
| [decisions/bigkinds-acquisition.md](decisions/bigkinds-acquisition.md) | BigKinds 뉴스 수집 방식 |
| [decisions/tool-reviews.md](decisions/tool-reviews.md) | 스킬, 플러그인, 외부 도구 검토 판정 |
