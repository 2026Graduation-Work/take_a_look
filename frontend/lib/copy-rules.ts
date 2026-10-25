// 사용자 노출 문구 금지 표현 목록. copy-rules.test.ts가 app/·lib/의 문자열을 이 목록으로 검사한다.
// 출처: AGENTS.md "사용자 노출 표현 규칙"(재점검 신호·근거 서술)과 모델 지표 오표기.

export interface CopyRule {
  pattern: RegExp;
  reason: string;
  allowIn?: readonly string[]; // 이 규칙을 지키지 않아도 되는 파일(법으로 이름을 밝혀야 하는 곳)
}

export const FORBIDDEN_COPY: readonly CopyRule[] = [
  { pattern: /지금\s*(사|파)세요/, reason: "매매 지시 (AGENTS.md 재점검 신호)" },
  { pattern: /(매수|매도)\s*하세요/, reason: "매매 지시 (AGENTS.md 재점검 신호)" },
  { pattern: /비중을\s*낮게\s*가져가/, reason: "비중 권고 (AGENTS.md 재점검 신호)" },
  { pattern: /신규\s*진입은\s*신중/, reason: "진입 권고 (AGENTS.md 재점검 신호)" },
  { pattern: /(오를|내릴)\s*것/, reason: "수익률 전망 (AGENTS.md 근거 서술)" },
  { pattern: /적중률/, reason: "모델 지표(ROC-AUC 등)를 적중률로 오표기할 수 있는 용어" },
  { pattern: /정확도\s*[\d{$]/, reason: "'정확도 N%' 표기 (ROC-AUC 오표기)" },
  { pattern: /기여도\s*[\d{$]|기여도[^"'`<]{0,15}%/, reason: "기여값을 '결과의 몇 %'로 읽히게 쓰지 않는다 → '하락 신호를 크게/조금 높임·낮춤'" },
  // 쉬운 말 규칙(copy-glossary.ts). "계산 근거" 영역도 예외 없이 검사한다.
  { pattern: /저평가|고평가|비싸|싸(요|다|게)/, reason: "재무 비교는 높아요, 낮아요, 비슷해요까지만(#372). 싸다, 비싸다는 판정이다" },
  { pattern: /추천/, reason: "모델 신호 순 목록을 '추천'으로 부르지 않는다 → '오늘 신호가 강한 종목'" },
  { pattern: /넛지/, reason: "개발 용어 → '확인할 것'" },
  { pattern: /체크포인트/, reason: "QA #278: 처음 쓰는 사람이 모르는 말 → '확인할 것'" },
  { pattern: /행동투자자|종목을\s*거르/, reason: "QA #278: 내부 용어 → '투자 습관 유형' · '볼 수 있는 종목을 줄이다'" },
  { pattern: /3등분/, reason: "QA #278: 당연한 계산 설명은 쓰지 않는다" },
  { pattern: /\bH(5|10|20)\b/, reason: "개발 용어 → '1주 뒤/2주 뒤/4주 뒤'" },
  { pattern: /상방|하방/, reason: "사전 참가자·지도교수가 헷갈린 말 → '상승'·'하락'(copy-glossary SIGNAL_WORD)" },
  { pattern: /·/, reason: "화면 규칙 v2: 가운데 점 금지(AI 느낌) → 간격 또는 쉼표" },
  { pattern: /니다[.?!]/, reason: "문장 끝은 해요체(DESIGN.md 0장, 10/20) → '~해요.' '~없어요.'" },
  { pattern: /신뢰구간/, reason: "개발 용어 → '10번 중 N번 이 범위'" },
  // 처리방침은 개인정보 보호법상 처리를 맡기는 곳(수탁자)의 이름을 밝혀야 해서 예외
  { pattern: /Supabase(?![A-Za-z_])/, reason: "내부 인프라 이름을 화면에 쓰지 않는다", allowIn: ["app/privacy/page.tsx"] },
  // 화면에 값과 함께 쓴 경우만 잡는다(코드 식별자 bit.composite는 통과)
  { pattern: /composite\s*[+\-\d{=]/, reason: "개발 용어 → '유형 점수'" },
  { pattern: /psych_[a-z]/, reason: "개발 변수명 → '가격 흐름 분위기'" },
  { pattern: /prob_up/, reason: "개발 변수명 → '과거 비슷한 신호 구간'" },
  { pattern: /BIT\b|Pompian 행동투자자 유형\(BIT\)/, reason: "개발 용어 → '투자 유형'" },
  { pattern: /실데이터/, reason: "실데이터가 기본이라 표시하지 않는다. 예시 값에만 '예시'를 단다(DESIGN.md 0장)" },
  { pattern: /시그널랩|signal ?lab(?!el)/i, reason: "옛 서비스명 → Take a Look (docs/CHANGELOG.md)" },
];
