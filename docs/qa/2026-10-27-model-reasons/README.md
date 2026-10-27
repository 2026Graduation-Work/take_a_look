# 모델 근거 설명과 영향 비중 개선

관련 이슈: #328, #420. 사용자와 팀 피드백에 따라 기존 이름과 '크게/조금' 본문 문구, 오른쪽 정렬과 상대 막대를 유지한다. 쉬운 설명은 공통 ⓘ 팝업으로, 영향 비중 %는 계산 근거로 옮긴다.

## 전후 비교 조건

- 개선 전 기준: `5543f640` (작업 시작 시 origin/main), 개선 후: 이 PR의 코드.
- 두 화면 모두 로컬 Next.js에서 같은 `capture-fixture.json` 응답을 사용했다. 종목 화면은 삼성전자이며 실제 계좌, 보유 수량이나 개인 정보는 사용하지 않았다.
- 공개 과거 preview의 구조에 합성 입력을 넣었다. 하락 클래스, 전체 절댓값 합 1, 표시 기여값 +0.12/-0.10/+0.06, 입력값 0.03/0.65/0.2로 고정했다. 실제 종목 예측이나 성능 비교가 아니다. 나머지 두 항목도 고정해 전후에 같은 응답을 사용했다.
- 데스크톱 1200×1000, 모바일 390×1000 CSS viewport, Chromium, 배율 1. 패널 전체를 캡처했다. 앱의 고정 헤더와 개발 도구 배지는 캡처할 때만 숨겨 패널을 가리지 않게 했다.
- 확인 경로: `/stocks/005930` → '모델이 본 이유' → '계산 근거'. 로컬 확인 시 E2E 가짜 데이터 서버와 브라우저 응답 대체가 필요하다. 운영 화면에는 이 합성 응답을 저장하지 않는다.

| 화면 | 개선 전 | 개선 후 |
|---|---|---|
| 데스크톱 | ![데스크톱 개선 전](https://raw.githubusercontent.com/2026Graduation-Work/take_a_look/0f64898f98ba8bcfe6dbd58d0213760f4c8107fc/2026-10-27-model-reasons/before-desktop.png) | ![데스크톱 개선 후](https://raw.githubusercontent.com/2026Graduation-Work/take_a_look/0f64898f98ba8bcfe6dbd58d0213760f4c8107fc/2026-10-27-model-reasons/after-desktop.png) |
| 모바일 | ![모바일 개선 전](https://raw.githubusercontent.com/2026Graduation-Work/take_a_look/0f64898f98ba8bcfe6dbd58d0213760f4c8107fc/2026-10-27-model-reasons/before-mobile.png) | ![모바일 개선 후](https://raw.githubusercontent.com/2026Graduation-Work/take_a_look/0f64898f98ba8bcfe6dbd58d0213760f4c8107fc/2026-10-27-model-reasons/after-mobile.png) |
| 데스크톱 계산 근거 | ![계산 근거 개선 전](https://raw.githubusercontent.com/2026Graduation-Work/take_a_look/0f64898f98ba8bcfe6dbd58d0213760f4c8107fc/2026-10-27-model-reasons/before-desktop-basis.png) | ![계산 근거 개선 후](https://raw.githubusercontent.com/2026Graduation-Work/take_a_look/0f64898f98ba8bcfe6dbd58d0213760f4c8107fc/2026-10-27-model-reasons/after-desktop-basis.png) |
| 모바일 계산 근거 | ![모바일 계산 근거 개선 전](https://raw.githubusercontent.com/2026Graduation-Work/take_a_look/0f64898f98ba8bcfe6dbd58d0213760f4c8107fc/2026-10-27-model-reasons/before-mobile-basis.png) | ![모바일 계산 근거 개선 후](https://raw.githubusercontent.com/2026Graduation-Work/take_a_look/0f64898f98ba8bcfe6dbd58d0213760f4c8107fc/2026-10-27-model-reasons/after-mobile-basis.png) |

| 설명 팝업 | 변경 전 본문에 표시 | 변경 후 공통 ⓘ 팝업 |
|---|---|---|
| 데스크톱 | 위 개선 전 이미지 참조 | ![데스크톱 피처 설명](https://raw.githubusercontent.com/2026Graduation-Work/take_a_look/0f64898f98ba8bcfe6dbd58d0213760f4c8107fc/2026-10-27-model-reasons/after-desktop-info.png) |
| 모바일 | 위 개선 전 이미지 참조 | ![모바일 피처 설명](https://raw.githubusercontent.com/2026Graduation-Work/take_a_look/0f64898f98ba8bcfe6dbd58d0213760f4c8107fc/2026-10-27-model-reasons/after-mobile-info.png) |

## 표시와 계산

- 기존 항목명과 상대 막대 길이를 유지한다. 모바일 이름은 한 줄로 표시하며, 한 행에 함께 들어가지 않는 영향 문구만 다음 줄 오른쪽으로 보낸다. 본문 오른쪽에는 '하락 점수를 크게/조금 높였어요'를 표시한다. 전체 피처 절댓값 합의 10% 이상이면 크게, 미만이면 조금이다. 분모가 없거나 0이면 방향만 표시한다.
- 설명은 본문에서 제거하고 다른 UI와 같은 공통 ⓘ 팝업으로 옮긴다. 모델 피처만 마우스 호버를 허용하며 클릭/터치/Enter도 지원한다. 설명 위로 이동해 읽을 수 있고 Escape/바깥 클릭으로 닫을 수 있다. 다른 용어 설명의 클릭 전용 동작은 바꾸지 않는다.
- '계산 근거'는 기존 두 열 표다. '+0.1200' 같은 내부 원점수 대신 '+12%' / '−10%'처럼 부호와 영향 비중을 표시한다. 원점수를 단순히 100배 해 %로 바꾸는 것이 아니다.
- 영향 비중 = 이번 대상 클래스의 해당 기여값 절댓값 / 전체 피처 기여값 절댓값 합 × 100. 보이지 않는 항목을 포함하고 모델 기준값은 제외한다. 확률이나 점수 증가율이 아니다.
- 소수 첫째 자리까지 반올림하되 끝의 0은 생략한다. 비중의 크기가 0.1% 미만이면 '+(0.1% 미만)' / '−(0.1% 미만)', 전체 합 누락/0이면 '미제공'으로 표시한다.
- 본문은 최대 3개, 계산 근거는 서버가 제공한 상위 최대 5개다. 전체 모델 입력 목록으로 부르지 않으며, 비중 합이 100%가 아닐 수 있음을 안내한다.
- 관측값과 원래 계산식은 화면에 표시하지 않는다. 모델 입력/기여값과 서버 설명 메타데이터는 변경하지 않는다.

- 막대 아래에는 기존처럼 대상 점수를 높이고 낮춘 정도이며 예측 확률이나 수익률이 아니라는 짧은 안내만 둔다.
- 계산 근거 아래에는 사용자가 정한 세 문단을 줄바꿈해 표시한다. 영향 비중의 뜻, 확률/점수 증감률이 아니라는 설명, 전체 비중과 일부 항목 표시의 차이, 영향 비중 10% 이상은 크게/미만은 조금이라는 기준을 안내한다. 막대 길이 비교 기준도 여기서 안내한다.

## 설명 사전

- [48종 설명 패턴 전체 전후 비교](FEATURE-DESCRIPTIONS.md)
- [기간별 170개 전체 전후 비교, 서버 이름 포함](FEATURE-DESCRIPTIONS-170.md)

이름과 서버 메타데이터, 계산식과 모델은 그대로다. 피처 정의는 공유 builder와 수급 계산을 참고해 작성했다. 가격 수준/변화율, 오른 날/오른 폭, 고저 범위 위치/마감 순위를 구분했다. 캔들 고가/저가 간격을 장중 이동 순서로 설명하지 않는다. 서버 설명 메타데이터와 계산은 변경하지 않는다.

## 검증

- `corepack pnpm test:unit`: 176개 통과. 170개 설명 누락/기간 치환/금지 표현, 전체 분모, 양/음/0, 분모 누락/0, 원점수와 비중의 차이, 작은 비중 표기를 검사한다.
- `corepack pnpm lint`, `corepack pnpm build`: 통과.
- 관련 Playwright: 모델 근거 15개 통과, 기존 공통 설명 3개도 이전 변경에서 통과했다(공통 팝업 코드는 이번에 변경하지 않음). 호버 열기/팝업 유지/닫기, Escape와 Enter, 터치와 화면 경계, 기존 클릭 전용 동작, 오른쪽 정렬, 상대 막대, 상세 영향 비중을 확인한다.
- 같은 합성 응답으로 기존 전후 이미지 8장을 유지하고 변경 후 4장을 갱신한다. ⓘ 팝업 이미지도 별도로 추가한다.
- 실제 사용자 이해도 평가와 실제 iOS/Android 기기 검증은 하지 않았다. Python, 모델/pack, DB, 운영 설정은 변경하지 않았다.
