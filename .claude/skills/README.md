# 검토한 디자인 스킬 (허용 목록)

`AGENTS.md` "검토한 디자인 스킬 허용 목록"의 실물이다. 원본 레포의 `SKILL.md`를 **고치지 않고** 복사했고
(각 README가 허용하는 설치 방법), 라이선스(MIT)를 같은 폴더에 둔다. 미러·포크본은 쓰지 않는다.

| 스킬 | 원본 | 커밋 SHA | 쓰는 곳 |
|---|---|---|---|
| `redesign-existing-projects` | https://github.com/Leonxlnx/taste-skill `skills/redesign-skill` | `5217fb45be2c0b302f29c9cd31cbd3237501c684` | 기존 화면 진단 |
| `minimalist-ui` | https://github.com/Leonxlnx/taste-skill `skills/minimalist-skill` | `5217fb45be2c0b302f29c9cd31cbd3237501c684` | 절제된 표면·타이포 원칙 |
| `baseline-ui` | https://github.com/ibelick/ui-skills `skills/baseline-ui` | `b1cc8e0073ac64b09b3d38cd604407aa20c2b7ad` | 간격·위계·빈 상태 점검 |
| `fixing-motion-performance` | https://github.com/ibelick/ui-skills `skills/fixing-motion-performance` | `b1cc8e0073ac64b09b3d38cd604407aa20c2b7ad` | 모션 점검 |
| `frontend-design` | https://github.com/anthropics/skills `skills/frontend-design` (Apache-2.0) | `33375500bcea98d610eb30ce10ac4e59b89c390d` | 새 화면 기획(브리프 → 토큰 계획 → 기본값 점검 → 구현 → 스크린샷 자기 비판) |

## 우선순위

**AGENTS.md > frontend/DESIGN.md > 스킬.** 스킬 지시가 우리 규칙(표현 규칙, 색의 의미, 화이트박스, 결정론)과
부딪히면 우리 규칙을 따른다. 알려진 충돌과 판정:

| 스킬 지시 | 판정 | 이유 |
|---|---|---|
| minimalist-ui: 스크롤 등장·순차 등장 애니메이션, 배경 이미지·그레인·그라데이션 광원 | 기각 | DESIGN.md 5장 — 모션은 펼치기/닫기 피드백에만 |
| minimalist-ui: 세리프 제목, Inter 금지, Phosphor 아이콘 | 기각 | 한글 본문은 Pretendard 하나. 아이콘 라이브러리 추가 없음 |
| minimalist-ui: 파스텔 알약 배지 | 기각 | 알약 배지 남발 금지, 색은 가격 방향에만 |
| redesign: 폰트 교체(Geist 등), 노이즈·스포트라이트 테두리, 3열 카드 금지 | 기각 | 한글 폰트·금융 대시보드 맥락과 맞지 않음 |
| redesign: 글래스모피즘 | 부분 채택(2026-09-26) | 탐색 층(헤더·하단 탭 막대·팝오버)에만. 데이터 면은 불투명 유지. DESIGN.md 4-1 |
| frontend-design: "제품을 드러내는 과감한 선택 하나", 브리프 대조, 스크린샷 자기 비판, 가짜 01/02/03 금지, 전부 대문자 라벨 금지 | 채택 | 과감함은 유리 탭 막대 한 곳에 쓰고 나머지는 조용히 |
| frontend-design: 메타 문자열을 가운뎃점(`A · B`)으로 잇지 말 것, 제목 위 eyebrow 라벨 줄이기 | 기각 / 부분 채택 | 가운뎃점 회색 한 줄은 알약 배지 남발을 막는 우리 규칙(DESIGN.md 4장). eyebrow는 섹션 머리에만 |
| frontend-design: 기본값이 아닌 서체 고르기 | 기각 | 한글 본문은 Pretendard 하나 |
| redesign: 가짜 숫자를 "자연스럽게" 흩트리기 | 기각 | 없는 데이터를 만들지 않는다. 예시는 예시로 표시 |
| baseline-ui: motion/react·cn·Radix/Base UI 도입 | 기각 | 새 의존성 추가 없이 기존 스택(Tailwind v4 + 네이티브 요소)으로 |
| baseline-ui: 자간 변경 금지 | 채택(2026-10-09) | 제목 자간 -0.02em 보정도 걷어 내고 기본값으로(DESIGN.md 2-2) |
| 공통: 강조색 하나, 그라데이션·글로우 금지, 빈 상태에 다음 행동 하나, tabular-nums, 200ms 이하 ease-out, prefers-reduced-motion | 채택 | DESIGN.md v2에 반영 |

taste-skill의 다이얼(DESIGN_VARIANCE·MOTION_INTENSITY·VISUAL_DENSITY)은 본체 스킬(`design-taste-frontend`) 설정이라
설치하지 않았다. 판단 기준으로만 **DESIGN_VARIANCE=3, MOTION_INTENSITY=2, VISUAL_DENSITY=5**를 쓴다
(가운데 정렬·절제된 레이아웃, 호버·펼치기 정도의 모션, 대시보드치고 여유 있는 밀도).
`high-end-visual-design`, `industrial-brutalist-ui`는 금융 대시보드와 맞지 않아 쓰지 않는다.

## 검토했지만 설치하지 않은 도구 (2026-09-23)

| 도구 | 판정 | 이유 |
|---|---|---|
| [ui-ux-pro-max-skill](https://github.com/nextlevelbuilder/ui-ux-pro-max-skill) | 기각 | 스타일 79종·팔레트 192종 중 고르는 도구. 우리는 스타일을 이미 정했다(DESIGN.md). 로고·이미지 생성은 범위 밖 |
| [awesome-claude-design](https://github.com/VoltAgent/awesome-claude-design) | 아이디어만 | Apple DESIGN.md와 대조했다. 절제 원칙(강조색 하나, 카드 그림자 없음, 면으로 구분)은 이미 같다. 빠진 터치 영역 규칙만 DESIGN.md 3장에 추가 |
| [design-md-chrome](https://github.com/bergside/design-md-chrome) | 기각 | 남의 사이트 스타일을 통째로 뽑아 오는 도구. 우리는 성균관대 색 + 자체 규칙이라 뽑아 올 대상이 없다 |
| [design-motion-principles](https://github.com/kylezantos/design-motion-principles) | 기각 | 우리 모션은 펼치기·눌림 피드백뿐(DESIGN.md 5장). `fixing-motion-performance`로 충분 |
| Claude Code `/design` | 사용 | 기본 기능(Pro 이상, 추가 비용 없음). 새 화면은 구현 전에 `/design`으로 시안을 여러 개 뽑아 고른다. 시안도 DESIGN.md를 따른다 |

## 검토했지만 설치하지 않은 도구 (2026-09-26)

| 도구 | 판정 | 이유 |
|---|---|---|
| [superpowers](https://github.com/obra/superpowers) (MIT) | 개인 선택 | 질문 → 설계 승인 → 짧은 계획 → 테스트 먼저. 서환이 이미 개인 설치로 쓰고 있다(`docs/superpowers/`). 단계마다 문서를 만들어 토큰을 많이 쓰므로 레포 공용 설치는 하지 않는다 |
| [ponytail](https://github.com/DietrichGebert/ponytail) (MIT) | 사용 중 | 중현 세션에 이미 켜져 있다(#136 정리). "라이브러리 대신 네이티브 한 줄" 원칙은 DESIGN.md의 새 의존성 금지와 같다 |
| 클레이모피즘·뉴모피즘·스큐어모피즘 | 기각 | 부푼 3D·낮은 대비·실물 흉내는 금융 근거 화면의 가독성·무게와 맞지 않는다. 유리는 탐색 층에만 채택(DESIGN.md 4-1) |

## 검토했지만 설치하지 않은 도구 (2026-10-09)

| 도구 | 판정 | 이유 |
|---|---|---|
| [web-design-guidelines](https://github.com/vercel-labs/agent-skills) (Vercel) | 규칙만 적용 | 스킬 본문이 실행할 때마다 원격 규칙을 새로 받아 와서 SHA 고정 원칙과 안 맞는다. 규칙 원문 [web-interface-guidelines](https://github.com/vercel-labs/web-interface-guidelines)(MIT, `434b7f91364665f2f733b310ec54809bf8f37937`)으로 한 번 점검: `transition: all`·확대 막기·`div onClick`·크기 없는 `img`·붙여넣기 막기 0건, `outline-none`은 모두 `focus:ring` 대체 있음. 빠진 `theme-color`·`touch-action: manipulation`만 반영. 영어 Title Case·Intl 강제 같은 항목은 한글 화면·`lib/display.ts` 규칙이 우선 |
| [emil-design-eng · apple-design](https://github.com/emilkowalski/skills) (MIT) | 아이디어만 | 스프링·제스처·드래그 모션 중심. 우리 모션은 펼치기·눌림뿐(DESIGN.md 5장)이라 `fixing-motion-performance`로 충분. "눌림 피드백은 pointer-down에 바로"는 이미 `.btn-*:active`로 있음 |
| [hallmark](https://github.com/nutlope/hallmark) (MIT) | 기각 | 테마 20여 종 + 프롬프트 게이트 57~65개. 방향은 이미 정했고(DESIGN.md) 점검은 redesign·baseline-ui와 겹친다. 게이트가 길어 토큰 부담 |
| ui-ux-pro-max · frontend-design · Impeccable · Taste | 기존 판정 유지 | 09-23·09-26·10-06 표 참고 |
| [Ruflo](https://github.com/ruvnet/ruflo)(옛 Claude Flow) · [ECC](https://github.com/affaan-m/ECC) | 기각 | 역할별 에이전트 군집·하네스 교체. 토큰을 크게 늘리고 설정·메모리를 따로 관리해야 한다. 우리는 단일 세션 + ponytail + 내장 `/code-review`로 충분 |
| [Graphify](https://github.com/Graphify-Labs/graphify) | 기각 | 코드베이스 지식 그래프 색인. 레포 규모 대비 색인 관리 부담(10/06 Graft·Codebase Memory MCP와 같은 판정) |
| [MarkItDown](https://github.com/microsoft/markitdown) (MIT) | 필요할 때만 | 설치 없이 `pipx run markitdown 파일.docx`처럼 일회성으로. 지금은 PDF·이미지를 Read로 바로 읽어 상시 도입할 이유가 없음 |
| [agent-browser](https://github.com/vercel-labs/agent-browser) · [Agent-Reach](https://github.com/Panniantong/Agent-Reach) | 기각 | 브라우저는 `@playwright/test`로 이미 화면 확인 중. SNS 크롤링은 계정 쿠키가 필요하고 서비스 범위 밖 |
| Remotion · HyperFrames | 기존 판정 유지 | 발표 영상이 필요할 때 HyperFrames(Apache-2.0). Remotion은 일정 규모 이상 회사 라이선스가 따로 있어 후순위 |
| prompts.chat · iFixAi · OpenShell · ai-engineering-from-scratch · AnyPS5 · openGym | 기각 | 프롬프트 모음·에이전트 감사·샌드박스 런타임·학습 자료·무관한 앱으로 이 프로젝트에 쓸 곳이 없음 |

## 검토했지만 설치하지 않은 도구 (2026-10-09 오후)

| 도구 | 판정 | 이유 |
|---|---|---|
| "화면 만드는 프롬프트 8가지"(레퍼런스 분석·색·글자·아이콘·부품·레이아웃·모션·화면 검수 역할 분담, SNS 가이드) | 흐름만 채택 | 원문은 DM 배포라 설치할 실체가 없다. 1~6단계는 `frontend-design`(브리프 → 토큰 → 기본값 점검)·DESIGN.md·`baseline-ui`와 겹치고, 7단계는 DESIGN.md 5장(눌림·펼치기만)과 같다. 실제 캡처를 비교해 영향이 큰 차이부터 고치는 **8단계(화면 검수)** 만 작업 끝 절차로 쓴다 — 첫 적용(#250): 보유 맵 비중 글자 대비 4.18 → 5.07(흰 85% → 흰), 390에서 잘리던 공시 건수를 앞으로 |

## 검토했지만 설치하지 않은 도구 (2026-10-11)

| 도구 | 판정 | 이유 |
|---|---|---|
| [Firecrawl](https://github.com/firecrawl/firecrawl) (AGPL-3.0) | 기각 | 웹 크롤링 API. 호스팅판은 크레딧 과금, 무료로 쓰려면 셀프호스팅(서버 관리). 우리 데이터는 KRX·DART·BigKinds로 정해져 있다 |
| [andrej-karpathy-skills](https://github.com/multica-ai/andrej-karpathy-skills) | 아이디어만 | CLAUDE.md 한 장(가정 밝히기·단순하게·필요한 줄만 고치기·검증 가능한 목표). 라이선스 표기가 없어 원문을 복사하지 않는다. 2·3번은 ponytail·AGENTS.md와 같고, 4번 "단계 → 확인 방법" 계획 형식만 작업 계획에 쓴다 |
| ponytail · ui-ux-pro-max · ECC · prompts.chat | 기존 판정 유지 | 09-23·09-26·10-09 표 참고 |
| [public-apis](https://github.com/public-apis/public-apis) (MIT) | 기각 | 무료 API 목록일 뿐. 한국 주식 원천은 없고(공공데이터포털·출처 불명 K-Data Gate 정도) 우리 원천(KRX·DART·BigKinds)을 바꿀 이유가 없다 |
| Claude Code 팁(오토 모드·`/security-review`·`ultrathink`) | 하나 채택 | 스킵 퍼미션은 쓰지 않고 있고(설정 확인), `think hard` 문구도 지시문에 없다. `/security-review`는 브랜치와 main의 차이만 보는 내장 기능(추가 비용 없음)이라 운영 경로를 바꾸는 PR의 머지 전 점검으로 AGENTS.md PR 규칙에 넣었다 |

## 검토했지만 설치하지 않은 도구 (2026-10-11 오후)

| 도구 | 판정 | 이유 |
|---|---|---|
| Playwright 플러그인(`playwright@claude-plugins-official`) | 사용 중(바뀐 점 없음) | 중현 개인 설정에 이미 켜져 있고, 레포는 `@playwright/test` 1.63으로 e2e·전후 스크린샷(`pr-screenshots` 브랜치 `demo-shots.mjs`)을 찍는다. 플러그인 도구는 필요할 때만 불러와 평소 토큰 부담이 없다. 레포 공용 설치는 하지 않는다 |
| [Taste Skill](https://github.com/Leonxlnx/taste-skill) (MIT) | 기존 판정 유지 | 설치한 2종(`redesign-skill`·`minimalist-skill`)은 고정 SHA `5217fb4` 이후 바뀐 파일이 없다(compare 확인). 본체 `taste-skill`·`brutalist`·`soft` 등은 방향이 DESIGN.md와 달라 계속 제외 |
| Image to Code ([taste-skill `image-to-code-skill`](https://github.com/Leonxlnx/taste-skill/tree/main/skills/image-to-code-skill), MIT) | 기각 | SKILL.md가 "for Codex"이고 **이미지를 먼저 생성**한 뒤 코드로 옮기는 방식이라 이미지 생성 도구가 필요하다. 대상도 랜딩·마케팅 히어로라 우리 근거 화면과 맞지 않는다 |
| [screenshot-to-code](https://github.com/abi/screenshot-to-code) (MIT) | 기각 | 별도 웹앱(React+FastAPI)이고 OpenAI·Anthropic **API 키(종량 과금)** 가 필요하다. 캡처 → 코드는 Claude Code에 이미지를 바로 주는 것으로 충분 |

## 검토했지만 설치하지 않은 도구 (2026-10-13)

| 도구 | 판정 | 이유 |
|---|---|---|
| "네이버에 안 뜬다면 3가지"(서치어드바이저·서치콘솔+사이트맵·페이지별 메타) | 채택 | 무료·설치 없음. Next 기본 기능(`app/robots.ts`·`app/sitemap.ts`·`generateMetadata`)으로 적용. 이때 `metadataBase`가 옛 주소(`stock-prediction-v2-chi`)라 og:image가 옛 주소로 나가던 것도 고침. 두 검색 도구 등록·소유 확인은 계정 로그인이 필요해 사람이 한다(받은 확인 코드를 `layout.tsx` `metadata.verification`에 넣기) |
| [mattpocock/skills](https://github.com/mattpocock/skills) (MIT) grill-me · prototype · handoff | 아이디어만 | grill-me는 별도 `grilling` 스킬을 불러 계획을 한 질문씩 캐묻는다 — 질문이 많아질수록 대화 횟수·토큰이 는다. 계획 확인은 내장 질문 도구로 충분. handoff는 대화 요약 문서 — 자동 요약·메모리·`[인수인계]` 이슈(#265)와 겹친다. prototype(UI)의 "한 경로에서 `?variant=`로 시안 여러 개 비교, main엔 결정만" 방식은 화면 대안을 비교할 때만 아이디어로 쓴다. 디자인 스킬 허용 목록 밖이라 설치하지 않음 |
| andrej-karpathy-skills ("22만 스타 CLAUDE.md") | 기존 판정 유지 | 10-11 표와 같은 레포(forrestchang, 2026-10-13 별 21.9만). 여전히 라이선스 표기 없음 → 원문 복사 안 함, ponytail·AGENTS.md와 내용 겹침 |

## 검토했지만 설치하지 않은 도구 (2026-10-15)

| 도구 | 판정 | 이유 |
| --- | --- | --- |
| [REA](https://github.com/morluto/rea) (MIT, 별 약 24.8만) | 기각(10-13 판정 유지) | 실재하고 별이 이틀 새 5.8만 → 24.8만으로 늘었지만 판단은 같다. 로컬 MCP 상시 연결이라 매 대화 토큰이 늘고, 바이너리 분석엔 Ghidra·IDA·Hopper를 따로 준비해야 한다. 분석 대상은 "내가 권리를 가진 앱"으로 제한되는데 우리 앱은 소스가 이미 있고, 남의 앱 분석은 약관 문제 |
| 입력창 기준(이름표=무엇·placeholder=형식·오류=다음 행동·선택 요소) | 채택 완료(#311) | 같은 스크랩 재수신. 입력칸을 만들 때 이 4가지를 점검한다 |
| [ui-ux-pro-max-skill](https://github.com/nextlevelbuilder/ui-ux-pro-max-skill) · [Taste Skill](https://github.com/Leonxlnx/taste-skill) | 기존 판정 유지 | 09-23·10-11 표 참고. Taste는 2종만 설치(SHA 고정) |
| [awesome-design-md](https://github.com/VoltAgent/awesome-design-md) (MIT) · DESIGN.md 추출 크롬 확장 | 기각 | 유명 서비스 사이트에서 뽑은 DESIGN.md 모음과 남의 사이트 디자인을 파일로 뽑는 도구. 우리는 자체 `frontend/DESIGN.md`가 있고, 남의 브랜드 화면을 베끼면 "AI가 만든 티"를 다른 티로 바꿀 뿐이다. 레포 라이선스와 별개로 각 브랜드 디자인 권리는 그 회사에 있다 |
| [design-motion-principles](https://github.com/kylezantos/design-motion-principles) (MIT, 별 1.3k) | 아이디어만(이미 충족) | 핵심 두 규칙 — 자주 반복되는 동작은 즉시/없음, `prefers-reduced-motion` 필수 — 은 DESIGN.md 5장(펼치기·눌림만, 150~200ms)과 `globals.css` 전역 처리로 이미 지킨다. 보유 맵 팝업(#326)도 애니메이션 없이 즉시 뜬다. 허용 목록의 `fixing-motion-performance`와 겹쳐 설치하지 않음 |
| caveman · caveman-compress · cavecrew | 기각 | 출력 65% 감소는 프로젝트 자체 측정이고, 외부 86개 작업 A/B에선 약 8.5%였다. Claude Code의 Concise 출력 스타일을 이미 쓰고, ponytail(코드 줄이기)은 전역 설치돼 있다. CLAUDE.md는 AGENTS.md를 가리키는 몇 줄뿐이라 압축할 게 없다 |
| ByteDance [Arco Design](https://github.com/arco-design/arco-design) (MIT) | 기각 | React 컴포넌트 라이브러리. 새 UI 라이브러리를 들이면 DESIGN.md 토큰과 충돌하고 번들이 커진다. "디자인 시스템을 어떻게 문서로 묶는가" 참고 자료로만 |
| Toss Benchmark(자체 업무 평가) | 생각만 채택 | 공개 범용 점수보다 "우리 업무를 얼마나 잘하나"로 모델을 고른다. 우리에게 옮기면 **AUC보다 우리 거래 규칙의 백테스트(Sharpe·MDD)와 사람 라벨 감성 정확도**를 모델 선택 기준으로 둔다는 뜻. #325(심리 A/B: AUC↑ 수익↓)·#327(수급: pooled AUC↑ 연평균 Sharpe↓)이 바로 그 사례다. 도구 설치 없음 |
| Salesforce SOQL `FORMULA()` | 해당 없음 | 우리 스택(Supabase Postgres)과 무관. Postgres는 `WHERE a - b > 100`이 원래 된다 |

## 검토했지만 설치하지 않은 도구 (2026-10-18)

| 도구 | 판정 | 이유 |
| --- | --- | --- |
| [Ollama](https://github.com/ollama/ollama) (MIT) | 기각 | 로컬 실행은 무료지만 우리 화면 문장은 LLM 없이 결정론 템플릿이다(`lib/dashboard-summary.ts`). Vercel 서버리스에서는 돌릴 수 없어 쓰려면 모델 서버를 따로 띄워 관리해야 하고, Ollama Cloud는 무료 구간이 작고 이후 월 과금이다. 뉴스 감성은 이미 정해진 모델이 있다 |
| [OpenClaw](https://github.com/openclaw/openclaw) (옛 Clawdbot) | 기각 | 메신저로 PC를 원격 조작하는 상시 실행 에이전트. 2026년 초 인증 없는 원격 코드 실행(CVE-2026-25253)과 스킬 장터(ClawHub) 악성 스킬 사고가 있었다. 컴퓨터 전체 권한을 주는 데몬이라 보안·관리 부담이 크고 우리 작업엔 쓸 곳이 없다 |
| Playwright MCP | 사용 중(10-11 판정 유지) | 플러그인으로 이미 켜져 있다. 다만 MCP 스냅샷은 화면 전체 구조를 매번 돌려줘 토큰이 크다 → 전후 스크린샷·화면 확인은 `@playwright/test` 스크립트를 먼저 쓰고, MCP 도구는 한 번 눌러 보는 정도에만 |
| [ComfyUI](https://github.com/comfyanonymous/ComfyUI) (GPL-3.0) | 기각 | 로컬 GPU 이미지·영상 생성. 서비스에 생성 이미지가 필요 없고, 모델 파일 관리 부담이 있다. 발표 영상은 HyperFrames(10-06 판정) |
| [MarkItDown](https://github.com/microsoft/markitdown) (MIT) | 기존 판정 유지 | 10-09 표와 같다. PDF·이미지는 Read로 바로 읽고, docx·xlsx·pptx를 글로 바꿀 일이 생기면 설치 없이 `pipx run markitdown 파일`로 한 번만 |

## 검토한 스크랩 (2026-10-20)

| 스크랩 | 판정 | 이유 |
| --- | --- | --- |
| "CLAUDE.md 규칙은 부탁이라 어긴다 → 훅으로" (보호 파일 훅, 커밋 전 테스트 훅) | **채택(적용)** | 사실 확인: Claude Code 공식 문서대로 CLAUDE.md는 시스템 프롬프트가 아닌 맥락으로 들어가 엄격한 준수 보장이 없고, PreToolUse 훅은 **종료 코드 2만 막는다**(1은 알림만). 되돌리기 힘든 두 가지만 `.claude/hooks/guard.py`로 옮겼다: ① `.env` 류 수정 차단(`.env.example` 제외) ② `git commit` 전 바뀐 블록의 빠른 검사(프론트 단위 테스트, 파이썬 ruff) 실패 시 차단. pytest 전체와 build는 CI 필수 체크가 막아 훅에 넣지 않았다(커밋마다 느려짐). 스키마는 이미 `ask` 권한으로 묻는다 |
| "에이전트 말고 스킬(업무별 설명서)" (Anthropic 발표 인용) | 생각만 채택(이미 하고 있음) | 우리 구조가 이미 이 방식이다: AI 하나 + 업무별 설명서(`AGENTS.md` 규칙, `frontend/DESIGN.md` 화면, 허용 목록 스킬 5종, 메모리의 '도구 꺼내 쓰기 표'), 완료 기준(PR 규칙의 필수 체크, 화면 PR 3문항), "틀리면 채팅이 아니라 설명서를 고친다"(피드백마다 DESIGN.md·copy-rules 갱신). 새 스킬은 만들지 않음. DM 프롬프트 모음은 받지 않음 |
| [PentAGI](https://github.com/vxcontrol/pentagi) (MIT, 별 3.1만, 10/17 갱신) | 기각 | 실재하고 활발하지만 자체 호스팅(Docker Compose + PostgreSQL/pgvector + 선택 Neo4j)과 LLM(유료 API 또는 27B급 로컬 모델)이 필요해 무료·무관리 원칙에 맞지 않는다. nmap, sqlmap, Metasploit 같은 공격 도구를 운영 중인 Vercel, Supabase 주소에 돌리는 것은 우리 몫의 점검 범위를 넘는다. 이번 점검(`docs/security/2026-10-audit.md`)은 RLS를 DB 안에서 역할을 바꿔 직접 시험했고, 주간 감시가 RLS를 계속 본다 |

## 검토한 스크랩 (2026-10-20, 두 번째)

| 스크랩 | 판정 | 이유 |
| --- | --- | --- |
| "육칠"(AI 6개가 각자 풀고 7번째가 채점해 합침) | 기각(생각만) | 같은 일을 여러 번 돌리는 병렬 에이전트라 토큰이 몇 배로 든다. 우리 세션은 하위 에이전트를 쓰지 않는 규칙이고, 대안 비교가 필요한 곳(새 화면)은 이미 DESIGN.md 0-1 "시안 2~3개를 만들어 비교"로 한다 |
| "크래시 아웃"(답을 스스로 공격해 검증) | 생각만 채택(이미 하고 있음) | 프롬프트 한 줄보다 실제 검증이 낫다: 테스트, 정확도 표(`accuracy.ts`), 운영 화면 실측, `/security-review`, ponytail 점검, 그리고 이번 #385처럼 실제 데이터로 다시 시험한다. 새 도구 없음 |
| "아우라 파밍"(AI 티 나는 디자인 금지) | 이미 충족 | DESIGN.md 8장(그라데이션, 글로우, 이모지, 알약 배지 남발, 상자 안 상자 금지)과 `copy-rules.ts`(가운데 점, 개발 용어, '추천' 등)가 같은 일을 코드로 막는다. 허용 스킬 `baseline-ui`, `minimalist-ui`도 같은 방향 |

## 검토한 스크랩 (2026-10-20, 세 번째)

| 스크랩 | 판정 | 이유 |
| --- | --- | --- |
| "깃허브 인기 클로드 스킬 5개"(Superpowers, Anthropic Skills, UI UX Pro Max, Caveman, Taste Skill) | 기존 판정 유지 | 다섯 개 모두 이미 판정했다. Superpowers는 개인 선택(서환 개인 설치, 레포 공용 아님), Anthropic Skills는 `frontend-design`만 SHA 고정 설치하고 문서(docx, xlsx)는 Claude 기본 기능으로 충분, UI UX Pro Max는 기각(스타일 고르는 도구, 우리는 DESIGN.md로 정함), Caveman은 오늘 첫 번째 표에서 기각, Taste Skill은 2종만 설치. "댓글 남기면 DM으로 설치 가이드"는 받지 않는다(원본 레포 SKILL.md만 본다) |

## 검토한 스크랩 (2026-10-21)

| 스크랩 | 판정 | 이유 |
| --- | --- | --- |
| "깃허브 인기 클로드 스킬 5개"(같은 목록 다시) | 기존 판정 유지 | 10/20 세 번째 표와 같은 다섯 개다. 다시 판정하지 않는다 |
| "별 30만, 스킬 TOP 10은 '멈춰'"(Superpowers, Matt Pocock, Karpathy, Graphify, Ponytail, UI UX Pro Max, Taste, Anthropic, Caveman, Agent Skills) | 9개 기존 판정 유지, Agent Skills 기각 | 9개는 이미 판정했다(Superpowers 개인 선택, Matt Pocock과 Karpathy는 아이디어만, Graphify 기각, Ponytail 사용 중, UI UX Pro Max 기각, Taste 2종 설치, Anthropic은 `frontend-design`만, Caveman 기각). Karpathy 저장소는 `multica-ai/andrej-karpathy-skills`이고 지금도 라이선스가 없어 복사하지 않는다(카파시 본인 저장소가 아니라는 스크랩 말이 맞다). 새로 본 `addyosmani/agent-skills`(MIT, 별 약 10.9만, 스크랩의 별 수와 다름)는 기획부터 배포까지 스킬 24개와 훅, 명령 묶음이다. 우리는 같은 순서를 AGENTS.md PR 규칙, `/code-review`, `/security-review`, ponytail, 완료 기준으로 이미 하고 있어 중복이고, 훅까지 들이면 규칙이 두 벌이 된다 |

## 검토한 스크랩 (2026-10-26)

밀린 스크랩 약 30개. 이미 판정한 것은 표를 가리키고, 새 것과 보안 소식만 적는다.

| 스크랩 | 판정 | 이유 |
| --- | --- | --- |
| Next.js 보안 권고 3건(10/22, 스크랩 아님, 점검 중 발견) | **적용(#411)** | 보안 소식을 보고 `pnpm audit --prod`를 돌리자 치명 2건(이미지 최적화 RCE, `use cache` RCE), 높음 1건(Server Action DoS)이 나왔다. 우리 코드에 `use cache`와 Server Action은 없지만 권고가 즉시 업그레이드를 요구해 16.3.8 → 16.4.3. 파이썬 런타임 의존성 `pip-audit`은 깨끗 |
| 주간 보안 패치(PHP, GitLab, NGINX, Node.js Brotli) · LiteLLM 1.107.0 변조 | 확인만 | PHP, GitLab, NGINX는 우리 스택에 없다. Node.js는 Vercel이 같은 주 버전 안에서 패치를 자동 적용하고, CI(`node-version: 22`)는 실행 때 최신 22.x를 받는다. 로컬 개발 PC만 직접 올린다(24.22.1 이상). LiteLLM은 요구 파일, 로컬 환경 어디에도 없다 |
| [Ponytail 5](https://github.com/DietrichGebert/ponytail) | **적용(전역 플러그인 갱신)** | 4.9.0 → 5.3.2. 이미 쓰는 도구의 새 판이라 판단이 같다. 상태 표시줄 경로도 새 판으로 바꿨다 |
| 공식 플러그인 TOP 5(frontend-design, superpowers, code-review, context7, code-simplifier) | 설치 안 함 | frontend-design은 같은 원본을 `.claude/skills`에 SHA 고정으로 이미 둠(플러그인까지 깔면 같은 스킬이 두 번 뜬다). code-review는 내장 `/code-review`, code-simplifier는 내장 `/simplify`와 ponytail과 겹친다. superpowers는 개인 선택(10/20 표). context7은 MCP 상시 연결이라 매 대화 토큰이 늘고 Next 문서는 Vercel 플러그인이 이미 준다 |
| 공식 `claude-security` · `security-guidance` 플러그인, [Cloudflare security-audit-skill](https://github.com/cloudflare/security-audit-skill)(별 4.6만), [Strix](https://github.com/usestrix/strix) | 기각(필요 시 일회성) | security-guidance는 매 턴 diff를 Opus로 다시 검토해 토큰이 계속 든다. claude-security와 Cloudflare 스킬은 여러 에이전트가 사냥, 반증하는 방식이라 한 번에 토큰이 크다(10/06 판정과 같음). Strix는 PentAGI와 같은 이유(도커, LLM 키, 운영 주소 공격). 우리는 운영 경로 PR에 `/security-review`, 10월 점검 문서, 의존성 감사로 충분하다 |
| [Alibaba Open Code Review](https://github.com/alibaba/open-code-review)(Apache-2.0) | 기각 | LLM 키를 따로 넣는 리뷰 CLI. `/code-review`와 겹친다 |
| [Fabric](https://github.com/danielmiessler/Fabric)(MIT) · MoneyPrinterV2 · Agent S · google-maps-scraper | 기각 | Fabric은 모델 키가 필요한 프롬프트 모음 CLI. 나머지는 스팸 자동화, PC 원격 조작, 약관 위반 수집이라 쓸 곳이 없다 |
| [gitingest](https://github.com/coderamp-labs/gitingest)(MIT) | 필요 시 일회성 | 레포를 글 한 덩어리로. 우리는 Claude Code가 레포를 직접 읽어 필요 없다. 웹 채팅에 남의 레포를 통째로 보여 줄 때만 |
| 셀프호스팅 대안 10개(yt-dlp, Ollama, Whisper, Immich, AppFlowy, Penpot, n8n, Plausible, Cal, Bitwarden) | 기각 | 서버 운영이 필요하거나 우리와 무관. Whisper는 졸업 뒤 음성 입력 후보로만 메모 |
| [TencentDB Agent Memory](https://github.com/TencentCloud/TencentDB-Agent-Memory) · harness2 · Cindy · [Orca](https://github.com/stablyai/orca) · [CLI-Anything](https://github.com/HKUDS/CLI-Anything) · [OmniRoute](https://github.com/cheaper-inference/OmniRoute) | 기각 | 도커와 프록시와 모델 키(Tencent), 벤치 실행 비용(harness2), 하네스 교체나 병렬 에이전트(Cindy, Orca), 쓸 소프트웨어 없음(CLI-Anything), 여러 제공자 키 관리(OmniRoute). 우리 메모리, 스킬 구조로 충분하다 |
| linkedin-skills · notfair-plugin · vercel-labs writing-guidelines | 기각 | SNS 글, 광고 성과는 용도 없음. [vercel-labs/agent-skills](https://github.com/vercel-labs/agent-skills)는 라이선스 표기가 없어 복사하지 않는다 |
| Gemini CLI · Open Design · find-skills · Claude Code Setup | 기각 | Claude Code와 같은 일(Gemini CLI). Open Design은 자기 모델 키가 필요하고, 공식 Claude Design 단독 사이트 종료(12/14)는 사실이지만 우리는 쓰지 않는다. find-skills는 허용 목록 밖 스킬을 끌어온다. Claude Code Setup은 추천만 하는데 이미 다 정해 둠 |
| Graphify · Impeccable · REA · Agent-Reach · Matt Pocock · Karpathy · Superpowers · HyperFrames · 스킬 TOP 10 | 기존 판정 유지 | 10/06~10/21 표 그대로 |
| [diagram-design](https://github.com/cathrynlavery/diagram-design)(MIT, 별 6.1만) | 아이디어만 | 보고서 그림 후보지만 노션 계획이 "그림은 직접, 본문 폰트로"다. 구성도는 mermaid(`docs/erd.md` 방식)나 내장 도식 기능으로 충분 |
| PDF 도구(Stirling-PDF, MinerU, BentoPDF) | 개인 도구로만 | 보고서 PDF 합치기, 줄이기는 설치 없는 BentoPDF(브라우저 안에서 처리, AGPL)로. 레포엔 들이지 않는다 |
| claude-x-jev 등 9선 · 사진 앱 3개 · 7개 저장소(VoiceStudio, Vibe-Trading 등) · 공식 업무 플러그인(Marketing, Legal 등) · FastAPI · Dessa · DeepInfer · Raon | 기각 | 유료 Jev 계열이거나 실체 불명(DM 미끼), 우리와 무관, 유료 요금제 앱 기능. Vibe-Trading(MIT)은 LLM이 매매 전략을 만드는 도구라 '추천하지 않는다'는 우리 원칙과 반대 |
| ai-jailbreaks(라이선스 없음, 별 546) | 기각 | 탈옥 프롬프트 모음. 우리 화면에는 사용자 입력을 받는 LLM이 없다 |
| "공격적으로 질문하는 8가지 기법" | 생각만(이미 하고 있음) | 10/20 '크래시 아웃'과 같다. 프롬프트보다 테스트, 감사, 실측으로 검증한다 |
| "출시 전 클로드에게 시킬 20가지"(분석, CTA, FAQ, 404, alt, robots, 구조화 데이터, 개인정보 처리방침 등) | 일부 이미 충족, 1건 제안 | robots, sitemap, 페이지별 제목과 설명, OG 썸네일, 맞춤 404(`not-found.tsx`)는 있다. **개인정보 처리방침 페이지가 없다** — 가입과 설문, 보유 종목을 저장하므로 넣을 가치가 크다(내용은 팀 확인 필요, 사용자 결정 대기). 분석 도구, 구조화 데이터, 문의 흐름은 졸업작품 범위 밖 |

## 검토한 스크랩 (2026-10-27)

코드 동결일. 레포에 들이는 도구는 없고, 보안 소식 1건과 발표 준비 후보 1건만 남긴다.

| 스크랩 | 판정 | 이유 |
| --- | --- | --- |
| [Tailworm](https://thecybersecguru.com/news/tailworm-tailscale-ssh-unix-socket-forwarding/)(Tailscale SSH 결함 11건, 10/25 공개) | 확인만 | 실재하고 아직 패치와 공식 공지(TS-2026-013까지)가 없다. 이미 승인된 기기를 가진 공격자가 다른 기기로 옮겨 가는 문제라 바깥에서 바로 뚫리는 일은 아니다. 우리 스택(Vercel, Supabase, GitHub Actions)과 개발 WSL에는 Tailscale이 없다. 개인 PC에서 쓴다면 SSH 규칙을 기기 쌍 단위로 좁히고 다음 판으로 올린다 |
| [Claude 형식 검증](https://interestingengineering.com/ai-robotics/claude-formal-verification-software-security)(오픈소스 123개, Theorem과 함께, 10/22) | 생각만 | 실재. 다만 RISC-V 바이너리가 64MB 미만 입력에서 멈추지 않는다는 좁은 약속이다. 우리에게 남는 교훈은 '지켜야 할 약속을 먼저 적고 경계 입력으로 검사한다'인데, #426 숫자 입력 수정(#429)이 이미 그 방식이다 |
| Claude 슬라이드, 독스, 디자인(10/8부터 무료 요금제 포함) | **발표 준비 후보** | 실재(공식 발표 원문은 못 읽었고 2차 글들이 일치). 졸업 발표 자료를 채팅에서 만들고 PPTX나 PDF로 받을 수 있다. 레포 변경은 없다 |
| [Laya](https://github.com/NandhaKishorM/laya)(Apache-2.0, CPU 판단 모델) | 생각만(졸업 뒤) | 실재. 뉴스 관련성 분류(`classify_live_relevance`)를 키 없이 CPU로 돌릴 후보지만, 첫 호출 때 Hugging Face 가중치를 받아야 하고 동결 뒤라 모델을 바꾸지 않는다 |
| [OpenJarvis](https://pypi.org/project/OpenJarvis/)(스탠퍼드, Apache-2.0) | 기각 | 설치가 Ollama와 로컬 모델을 깐다. 10/18 Ollama 판정과 같다(셀프호스팅) |
| [Gemini API CLI](https://github.com/google-gemini/gemini-api-cli)(Google, Apache-2.0, 베타) | 기각 | 이미지, 음성, 영상 생성은 API 키 종량제이고 베타라 명령이 바뀐다. 우리 화면엔 생성 미디어가 없다 |
| [Google Stitch](https://stitch.withgoogle.com) | 아이디어만 | 무료(하루 크레딧)지만 화면 방향은 `frontend/DESIGN.md`로 정해져 있고 동결일이다. 남의 시안을 붙이면 애플식 절제 방향과 어긋난다 |
| Glassy Dashboard V2 | 기각 | 카드 전체를 유리로 만든다. 우리는 유리를 헤더, 탭 막대, 팝오버에만 쓴다. "Code" 댓글 미끼 |
| 무료 플러그인 6가지(superpowers, frontend-design, code-review, security-guidance, [Claude Mem](https://github.com/thedotmack/claude-mem), [gstack](https://github.com/garrytan/gstack)) | 4개 기존 판정 유지, 2개 기각 | 앞의 넷은 10/26 표 그대로. Claude Mem은 내장 메모리, `AGENTS.md`와 겹치고 라이선스 표기가 글마다 다르다(AGPL과 Apache). gstack(MIT)은 스킬 23개라 토큰이 늘고 ponytail, `/code-review`와 겹친다 |
| 고수 도구 4개(Graft는 [Trail-code](https://github.com/trailhq/Trail-Code)로 이름 바뀜, Agency Agents, Codebase Memory MCP, OpenMontage) | 기존 판정 유지 | 10/06 기각 그대로. Trail-code는 처음 실행 때 지난 대화를 읽어 사용량이 나간다 |
