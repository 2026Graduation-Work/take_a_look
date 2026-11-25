# CONTRIBUTING.md — 협업 규칙

[AGENTS.md](../AGENTS.md)는 공통 지침이다. 브랜치, PR, 머지, 훅 변경 절차는 여기에서 관리한다.

## 작업 흐름

1. `git fetch origin`을 실행하고 `git switch -c feat/기능명 origin/main`처럼 최신 `origin/main`에서 작업 브랜치를 만든다.
2. 변경 블록을 로컬에서 검증한 뒤 커밋·push한다. 브랜치 접두는 `feat/`, `fix/`, `docs/`, `chore/`, `refactor/`, `test/`를 쓴다.
3. [PR 템플릿](../.github/pull_request_template.md)을 채운다. 기능 추가·수정이면 변경 요약, 로컬 검증 결과와 해당하는 확인용 주소를 남긴다.
4. 팀 방침은 필수 체크를 통과한 PR의 작성자 셀프 머지를 허용한다. PR까지만 요청받았다면 거기서 끝낸다. 머지할 PR 번호를 `pr_number`에 지정해 아래 명령을 실행한다.

```sh
gh pr checks "${pr_number:?PR 번호를 지정하세요}" --required --watch --fail-fast &&
  gh pr merge "$pr_number" --squash --delete-branch
```

필수 체크 이름은 `lint-and-build`, `profiling-test`, `chart-test`, `text-test`다. 영향이 없는 블록은 CI에서 건너뛴다. 실제 머지 요건은 GitHub의 main Ruleset을 따른다.

## 팀 밖에서 기여할 때

1. 저장소를 포크하고, 포크에서 위 접두 규칙대로 브랜치를 만든다.
2. 바꾼 블록만 로컬에서 검증한다. 웹은 `frontend/`에서 `pnpm install` 뒤 `pnpm build`, 화면 문구를 바꿨으면 `pnpm test:unit`도 실행한다. Python 블록은 해당 폴더에서 `ruff check .`와 `pytest`를 실행한다.
3. 원 저장소 `main`으로 PR을 열고 [PR 템플릿](../.github/pull_request_template.md)을 채운다. 관련 이슈 번호를 적는다.
4. 처음 기여하는 계정의 PR은 팀원이 승인해야 CI와 Vercel 미리보기가 돈다. 머지는 팀원이 리뷰한 뒤에 한다. 위의 셀프 머지는 팀원에게만 해당한다.

맡을 만한 일은 [good first issue](https://github.com/2026Graduation-Work/take_a_look/labels/good%20first%20issue)와 [help wanted](https://github.com/2026Graduation-Work/take_a_look/labels/help%20wanted) 라벨에 모아 둔다. 시작 전에 이슈에 댓글을 남기면 담당자로 함께 지정한다. 실제 계좌나 보유 종목이 보이는 캡처는 올리지 않는다.

## 블록과 커밋

| 블록·커밋 범위 | 경로 |
|---|---|
| `web` | `frontend/` |
| `profiling` | `backend/profiling/` |
| `chart` | `backend/analysis/chart/` (serving 포함) |
| `text` | `backend/analysis/text/` |
| `db` | `supabase/` |
| `schema` | `schema/` |
| `ci` | `.github/` |
| `harness` | `.claude/settings.json`, `.claude/hooks/`, Codex와 공용 훅 설정 |
| `docs` | `docs/`, 루트 Markdown, `.claude/skills/README.md` |

- 누구나 어느 블록이든 고칠 수 있다. 여러 블록을 바꾸면 PR을 나누고 먼저 머지할 순서대로 올린다. 각 PR이 단독으로 머지돼도 main이 동작해야 한다.
- 계약을 맞추려면 동시에 바뀌어야 하는 짝은 같은 PR에 담고 본문에 이유를 한 줄 적는다. 예를 들어 스키마와 파생 타입, 마이그레이션과 문서 표, 에이전트 지침과 그 규칙을 넘겨받는 블록 문서가 해당한다. 블록 아래의 문서는 해당 블록에 속한다.
- 커밋 메시지는 한국어 `타입(블록): 설명` 형식을 쓴다. 예시는 `fix(web): 차트 축 라벨 겹침 수정`이다. 이동·리네임과 로직 수정은 커밋을 나눈다.
- 스키마 변경 PR 제목에 `[schema]`를 붙이고 팀 전원을 멘션한다.

## 훅과 권한 변경

- 훅과 권한 설정은 별도 harness PR로 올린다. Claude Code와 Codex 양쪽에서 작동하는 데 필요한 공용 훅·CI 설정은 같은 PR에 담고 이유를 적는다.
- 비밀 파일 접근처럼 실행 전에 막아야 하는 동작은 두 도구에서 실행 시점에 차단한다. 머지 전 검증은 두 도구 공용 CI 필수 체크로 둘 수 있다. PR에 두 도구에서 각각 직접 확인한 결과를 남긴다.

## 운영 경로 변경

- 워크플로, 비밀키, 인증, 차트 서빙 팩, DB 마이그레이션을 바꾸면 머지 전에 main 대비 diff만 보안 검토한다. 지원하는 도구에서는 `/security-review`로 검토한다.
- 되돌리기 힘든 설계 문서(스키마, 계약, 운영 경로)와 인수인계 문서는 구현 전에 작성에 참여하지 않은 새 세션에 문서만 주고 "이 문서만으로 구현할 때 막히는 곳"을 묻는다. 지적은 문서를 고쳐서 닫는다.
- 정기 작업은 해당 워크플로가 지원하는 `dry_run`으로 검증한다. 지원하지 않는 작업은 테스트 DB나 모의 클라이언트에서 해당 경로를 검증한다. 뉴스·공시·재무 워크플로의 수동 `mode`는 운영에 적재한다. 검증 방법과 결과를 PR에 남긴다.
