# CHANGELOG

- 2026-09 서비스명 변경: SignalLab → Take a Look
- 2026-09-26 레포 이름 변경: `Stock_Prediction_v2` → `take_a_look`. GitHub이 옛 주소(클론·링크·API)를 자동으로 넘겨 준다. 로컬은 `git remote set-url origin https://github.com/2026Graduation-Work/take_a_look.git`로 바꾸면 깔끔하다. `schema/*.json`의 `$id`는 freeze된 식별자라 그대로 둔다. Vercel 프로젝트·배포 주소는 변경 없음.

- 2026-09-27 H5·H20 차트 serving 공개 계약과 일일 실행 경로 추가. 차트 migration은 기존 DB 변경 뒤 단일 `0007`로 적용한다. 운영 DB 적용과 첫 원격 발행은 미확인. [서빙 현황](../backend/analysis/chart/serving/README.md), [실행 절차](../backend/analysis/chart/serving/OPERATIONS.md).
