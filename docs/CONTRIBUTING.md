# CONTRIBUTING.md — 협업 규칙

규칙 본문(블록 나누기, 머지, 커밋 형식, 훅 변경)은 [`AGENTS.md`](../AGENTS.md)의 "PR 규칙" 한 곳에 있다. 이 문서는 사람이 따라 하는 작업 흐름만 적는다.

## 작업 흐름

1. `main`을 최신으로 받는다. `git pull origin main`
2. 작업 브랜치를 딴다. `git switch -c feat/기능명` (접두는 `feat/` `fix/` `docs/` `chore/` `refactor/` `test/`)
3. 한 블록 안에서만 고치고 커밋한다. `fix(web): 차트 축 라벨 겹침 수정`
4. 다른 블록도 고쳐야 하면 브랜치를 새로 따서 PR을 따로 올린다.
5. PR 템플릿을 채워 올린다. 필수 체크가 초록이 되면 작성자가 바로 머지한다(승인 필요 없음).
6. 머지하면 작업 브랜치는 지워진다(`--delete-branch`).

## 커밋 타입

| 타입 | 용도 |
| --- | --- |
| `feat` | 새로운 기능 |
| `fix` | 버그 수정 |
| `docs` | 문서 변경 |
| `chore` | 설정·빌드·잡일 (코드 동작 변화 없음) |
| `refactor` | 동작 변경 없는 코드 정리 |
| `test` | 테스트 추가·수정 |
| `ci` | `.github/` 워크플로 |

괄호 안 범위는 블록 이름이다(`web`, `profiling`, `chart`, `text`, `db`, `schema`, `ci`, `harness`, `docs`). 표는 `AGENTS.md`에 있다.

## 참고

- 프로젝트 전반 안내는 루트의 [`README.md`](../README.md)
- 졸업작품 제출본은 태그 [`v1.1.0`](https://github.com/2026Graduation-Work/take_a_look/releases/tag/v1.1.0)
