## 작업 내용 요약

<!-- 한두 줄로 이 PR이 무엇을 하는지 적습니다. -->

## 관련 이슈 / 노션 링크

<!-- 이 PR로 해결하는 이슈마다 아래에 `Closes #번호`를 한 줄씩 적습니다.
예시는 `Closes #12`입니다. 후속 작업이 남은 이슈는 `Refs #12`처럼 참조합니다.
관련 노션 링크가 있으면 함께 적습니다. -->

## 변경 사항 (무엇을, 왜)

- **무엇을**:
- **왜**:

## 블록

<!-- PR 하나에 블록 하나. 두 개 이상 체크했다면 아래에 묶은 이유를 한 줄 적습니다(AGENTS.md "PR 규칙"). -->

- [ ] web (`frontend/`)
- [ ] profiling (`backend/profiling/`)
- [ ] chart (`backend/analysis/chart/`)
- [ ] text (`backend/analysis/text/`)
- [ ] db (`supabase/`)
- [ ] schema (`schema/`) — 제목에 `[schema]`, 전원 멘션
- [ ] ci (`.github/`)
- [ ] harness (훅·권한 설정) — Claude Code와 Codex 양쪽 확인 결과 첨부
- [ ] docs

묶은 이유:

## 확인한 방법

<!-- 로컬에서 어떻게 동작을 확인했는지 구체적으로 적습니다. -->

- [ ] web: `cd frontend && pnpm build`
- [ ] Python: 해당 블록에서 `ruff check .` · `pytest`
- [ ] (해당 시) 화면 확인 주소 또는 전후 스크린샷
- [ ] (해당 시) 운영 경로 변경: `/security-review`, 정기 작업은 `dry_run`

## 체크리스트

- [ ] `.env` · API 키 · 비밀번호 등 비밀 정보를 포함하지 않는다
- [ ] 커밋 메시지가 `타입(블록): 설명` 형식이다
- [ ] 화면에 표시되는 수치는 실제 데이터·실제 수식 기반이다 (더미 값이 아니다)
- [ ] (해당 시) 관련 문서를 함께 고쳤다
