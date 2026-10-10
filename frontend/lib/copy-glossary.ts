// 쉬운 말 사전. 화면 문구는 여기서 가져다 쓰고, 개발 용어를 화면에 직접 쓰지 않는다.
// 금지어 검사는 copy-rules.ts. 개발 용어는 "계산 근거" 영역에서만 쓴다.

import type { HorizonAgreement, HorizonDirection, RiskGrade } from "./types";

export type HorizonKey = "h5" | "h10" | "h20";

// 모델의 예측 기간. 5·10·20거래일 ≈ 1·2·4주
export const HORIZON_LABEL: Record<HorizonKey, string> = {
  h5: "1주 뒤",
  h10: "2주 뒤",
  h20: "4주 뒤",
};

// 화면에서 쓰는 이름. 왼쪽은 코드·문서 용어
export const TERM = {
  contribution: "모델이 본 이유",
  supply: "누가 사고팔았나",
  sentiment: "뉴스 분위기",
  volatility: "가격 흔들림",
  nudge: "체크포인트",
  market: "시장 분위기",
  financial: "회사 체력",
  horizonAgreement: "기간마다 같은 방향인가요?",
} as const;

// 예상 수익률 밴드(신뢰구간) → 과거 비슷한 경우의 빈도 문장
export function bandSentence(horizon: HorizonKey, ciLevel: number): string {
  const times = Math.round(ciLevel * 10);
  return `과거 비슷한 경우, ${HORIZON_LABEL[horizon]} 수익률은 10번 중 ${times}번 이 범위였어요`;
}

// 신호 강도 순위(0~1, 1이 최상위) → "오늘 분석한 종목 중 상위 N%"
export function topPercentLabel(rankPercentile: number): string {
  return `오늘 분석한 종목 중 상위 ${Math.max(1, Math.round((1 - rankPercentile) * 100))}%`;
}

export const DIRECTION_WORD: Record<HorizonDirection, string> = {
  up: "오르는 쪽",
  flat: "뚜렷하지 않음",
  down: "내리는 쪽",
};

export const AGREEMENT_ANSWER: Record<HorizonAgreement, string> = {
  aligned: "네, 세 기간 모두 같은 방향이에요",
  mixed: "대체로 같지만 한 기간은 달라요",
  conflict: "아니요, 기간마다 엇갈려요",
};

// 재무 지표는 이름을 그대로 두고 괄호로 풀어 쓴다
export const FINANCIAL_TERM: Record<string, string> = {
  per: "PER(주가가 1년 이익의 몇 배인지)",
  pbr: "PBR(주가가 회사 순자산의 몇 배인지)",
  roe: "ROE(자기 돈으로 1년에 얼마를 벌었는지)",
  operating_margin: "영업이익률(매출 100원에서 남긴 영업이익)",
  debt_ratio: "부채비율(빚이 자기 돈의 몇 %인지)",
  revenue_growth: "매출 증가율(1년 전보다 매출이 늘어난 정도)",
};

export type RiskLevel = "낮음" | "보통" | "높음";

// 위험등급(5 = 매우 안전)은 숫자가 뒤집혀 헷갈린다. 화면에는 단어 + 5칸(찬 칸이 많을수록 위험)으로 쓴다.
export function riskLevel(grade: RiskGrade): { word: RiskLevel; filled: number } {
  return {
    word: grade >= 4 ? "낮음" : grade === 3 ? "보통" : "높음",
    filled: 6 - grade,
  };
}

// ── 계산 근거(종목 상세 "더 알아보기") 쉬운 말. 한 줄 = 무엇을 · 어떤 자료로 · 어떻게 계산했나 · 이번 값 ──
// 계산 정의: lib/profiling/bit.ts(유형), lib/profiling/nudges.ts(체크포인트), backend market_psychology.py(가격 흐름 분위기)

// 유형 점수 = (보유 기간 답 + (손실 감내 답 + 집중 답) ÷ 2) ÷ 2, -1~+1을 4구간으로 나눈다
export const STYLE_TYPE_RULE =
  "'얼마나 자주 사고파는지' 답과 '손실을 견디고 몇 종목에 모으는지' 답을 평균한 -1~+1 점수를 -0.5 · 0 · +0.5에서 네 유형으로 나눴어요.";

// 스펙트럼 양 끝(감정적 편향)과 가운데(인지적 편향)
export const BIAS_MODE_WORD = {
  emotional: "양 끝 유형이라 기분에 흔들리기 쉬운 쪽",
  cognitive: "가운데 유형이라 익숙한 생각에 기대기 쉬운 쪽",
} as const;

// 가격 흐름 분위기 = (20거래일 수익 ÷ 그동안의 흔들림, 60거래일 평균 매입가 대비 지금 가격의 위치)의 평균
export const PSYCHOLOGY_RULE =
  "최근 20거래일 수익을 그동안의 흔들림으로 나눈 값과, 최근 60거래일 동안 사람들이 평균적으로 산 가격 대비 지금 가격의 위치를 평균했어요.";

// 뉴스 분위기: 하루 기사가 이보다 적은 날은 툴팁과 계산 근거에 주의 안내
export const FEW_ARTICLES = 3;
export const FEW_ARTICLES_RULE = `하루 관련 기사가 ${FEW_ARTICLES}건 미만이면 한두 기사의 말투가 그날 점수를 크게 움직일 수 있어요. 이 값은 참고만 해 주세요.`;

export const CHECKPOINT_RULE = "설문 답이 한쪽으로 0.3 넘게 기울고, 지금 이 종목의 시장 조건이 맞을 때만 보여요.";

export const STYLE_TYPE_SOURCE = "행동재무학의 투자자 유형 연구(Pompian)에서 착안해 설문으로 가늠한 분류예요.";

// 공시 유형(docs/disclosure-kinds.md) → 화면 이름과 쉬운 풀이
export const DISCLOSURE_KIND: Record<string, { label: string; explain: string }> = {
  market_action: { label: "거래 주의", explain: "거래소가 투자 주의·경고, 관리종목 지정, 거래 정지 같은 조치를 알린 공시예요." },
  business_risk: { label: "경영 위험", explain: "횡령·배임, 자본잠식, 생산 중단처럼 회사 운영에 큰 문제가 생겼다는 공시예요." },
  inquiry: { label: "조회 공시", explain: "소문이나 보도에 대해 거래소가 사실인지 묻고, 회사가 답한 공시예요." },
  periodic: { label: "정기보고서", explain: "분기·반기·1년마다 내는 실적과 재무 상태 보고서예요." },
  earnings: { label: "실적 발표", explain: "확정 전 실적(잠정치)이나 매출·이익이 크게 바뀐 사실을 알린 공시예요." },
  contract: { label: "공급 계약", explain: "큰 규모의 판매·공급 계약을 맺었다는 공시예요. 계약 금액이 매출 대비 얼마인지 보세요." },
  capital_raise: { label: "유상증자", explain: "새 주식을 팔아 돈을 모으는 결정이에요. 주식 수가 늘어 한 주의 가치가 낮아질 수 있어요." },
  bonus_issue: { label: "무상증자", explain: "돈을 받지 않고 주주에게 새 주식을 나눠 주는 결정이에요. 회사 가치 자체는 그대로예요." },
  bond: { label: "사채 발행", explain: "나중에 주식으로 바꿀 수 있는 채권 등을 발행한 공시예요. 주식으로 바뀌면 주식 수가 늘 수 있어요." },
  buyback: { label: "자사주", explain: "회사가 자기 주식을 사거나 팔거나 없앤다는 공시예요." },
  dividend: { label: "배당", explain: "이익의 일부를 주주에게 나눠 주는 결정이에요." },
  restructure: { label: "합병·분할", explain: "회사를 합치거나 나누거나 사업을 사고판다는 공시예요." },
  ownership: { label: "지분 변동", explain: "대주주·임원이나 큰 투자자가 가진 주식 수가 바뀌었다는 공시예요." },
  lawsuit: { label: "소송", explain: "회사가 관련된 소송이 시작되거나 결과가 나왔다는 공시예요." },
  investment: { label: "투자·보증", explain: "다른 회사 주식을 사거나 남의 빚을 대신 갚기로 보증한 공시예요." },
  shareholder_meeting: { label: "주주총회", explain: "주주총회 소집이나 결과, 의결권 관련 공시예요." },
  investor_relations: { label: "기업설명회", explain: "회사가 투자자에게 실적·사업을 설명하는 자리를 열거나 실적 발표 날짜를 알린 공시예요." },
  securities_filing: { label: "증권 발행 서류", explain: "주식·채권 등을 발행하면서 내는 신고서·설명서예요. 대부분 절차 서류예요." },
  other: { label: "기타", explain: "위 유형에 들지 않는 공시예요. 제목을 눌러 원문을 확인해 보세요." },
};
