# 안내·투자 팁 전후 화면

- 변경 전: `86ed26e39f8f70743dfa6219b9581d2223d83e61` (`main`)
- 변경 후: `ba48950a0930b43ae713e16f8f7bc15a7d6e8769` (`feat/tips-reading-pages`)
- 촬영일: 2026-11-27 (Asia/Seoul)
- 크기: 데스크톱 1280×950, 모바일 390×844. Light 모드, Chrome. 변경 전은 기본 모션 설정에 캡처 애니메이션 비활성화, 변경 후는 동작 줄이기 설정.
- 모든 이미지는 실제 로컬 Next.js 프로덕션 화면의 원본 PNG 캡처다.
- 익명 브라우저와 공개 팁 데이터만 사용했다. 계정·보유 화면·비밀 정보는 포함하지 않는다.
- 상세의 `/performance` 복귀 주소는 탐색 시연용이다.

## 변경 전 재현

해당 main 커밋을 임시 디렉터리에 `git archive`로 풀고 설치된 의존성을 연결했다.
`NEXT_PUBLIC_SUPABASE_URL=http://127.0.0.1:54321 NEXT_PUBLIC_SUPABASE_ANON_KEY=e2e-anon-key next build --webpack` 뒤 `next start --hostname 127.0.0.1 --port 3103`으로 실행했다.
임시 스냅샷 밖의 의존성 심볼릭 링크 때문에 webpack 빌드를 사용했다.
`/guide`, `/guide#beginner-tips`, `/guide#terms`를 같은 viewport에서 캡처했다. 팁 섹션에 42개가 있음을 확인했다.

## 변경 후 재현

동일한 mock Supabase 환경에서 `pnpm build` 후 `next start --hostname 127.0.0.1 --port 3102`로 실행했다.
`/guide`, `/tips`, `/tips/loss-recovery?category=all&returnTo=%2Fperformance`, `/glossary`를 캡처했다.
이용 안내는 첫 viewport, 목록·상세·용어는 전체 페이지다. 가로 넘침과 JavaScript page error가 없음을 확인했다.
화면 비교는 개별 route의 정보 구조를 보여 주며 원래 작업의 임의 스크롤·미저장 입력 복원을 뜻하지 않는다.

## 검증

- `pnpm lint`: 통과.
- `pnpm test:unit`: 215개 통과.
- `pnpm build`: 통과.
- `CI=1 PATH=/Users/cracker/Library/pnpm/.tools/pnpm/10.33.0/bin:$PATH node node_modules/@playwright/test/cli.js test --config=playwright.local.config.ts tests/e2e/tips.spec.ts tests/e2e/guide.spec.ts tests/e2e/market-tip-strip.spec.ts tests/e2e/tap-targets.spec.ts`: 27개 통과.
- 임시 Playwright 설정은 저장소 설정을 가져와 Chrome 채널, video off, 기존 mock 서버 재사용을 적용했다. 실행 후 제거했다.
- `git diff --check`: 통과.
- 원래 작업 복원 범위는 화면 주소·선택 탭·기존 저장 설정이다. 팁 목록의 카드 위치·초점도 복원한다.

## 사진

- [after-detail-desktop.png](after-detail-desktop.png)
- [after-detail-mobile.png](after-detail-mobile.png)
- [after-glossary-desktop.png](after-glossary-desktop.png)
- [after-glossary-mobile.png](after-glossary-mobile.png)
- [after-guide-desktop.png](after-guide-desktop.png)
- [after-guide-mobile.png](after-guide-mobile.png)
- [after-tips-desktop.png](after-tips-desktop.png)
- [after-tips-mobile.png](after-tips-mobile.png)
- [before-desktop-guide.png](before-desktop-guide.png)
- [before-desktop-terms.png](before-desktop-terms.png)
- [before-desktop-tips.png](before-desktop-tips.png)
- [before-mobile-guide.png](before-mobile-guide.png)
- [before-mobile-terms.png](before-mobile-terms.png)
- [before-mobile-tips.png](before-mobile-tips.png)
