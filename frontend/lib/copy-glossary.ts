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
  "설문에서 '얼마나 자주 사고파는지' 답과 '손실을 견디고 몇 종목에 모으는지' 답을 평균해 -1~+1 점수로 만들고, " +
  "-0.5 아래는 자산 보존형 · 0 아래는 추종형 · +0.5 아래는 독립 분석형 · 그 위는 적극 축적형으로 나눴어요.";

// 스펙트럼 양 끝(감정적 편향)과 가운데(인지적 편향)
export const BIAS_MODE_WORD = {
  emotional: "양 끝 유형이라 기분에 흔들리기 쉬운 쪽",
  cognitive: "가운데 유형이라 익숙한 생각에 기대기 쉬운 쪽",
} as const;

// 가격 흐름 분위기 = (20거래일 수익 ÷ 그동안의 흔들림, 60거래일 평균 매입가 대비 지금 가격의 위치)의 평균
export const PSYCHOLOGY_RULE =
  "최근 20거래일 수익을 그동안의 흔들림으로 나눈 값과, 최근 60거래일 동안 사람들이 평균적으로 산 가격 대비 지금 가격의 위치를 평균했어요.";

// 뉴스 분위기: 하루 기사가 이보다 적은 날은 차트 점을 흐리게, 툴팁에 "참고만"
export const FEW_ARTICLES = 3;
export const FEW_ARTICLES_RULE = `하루 기사가 ${FEW_ARTICLES}건 미만인 날은 한두 기사의 말투가 그날 분위기를 정해 버려서, 차트에 흐린 점으로 그리고 참고만 하도록 적었어요.`;

export const CHECKPOINT_RULE = "설문 답이 한쪽으로 0.3 넘게 기울고, 지금 이 종목의 시장 조건이 맞을 때만 보여요.";

export const STYLE_TYPE_SOURCE = "행동재무학의 투자자 유형 연구(Pompian)에서 착안해 설문으로 가늠한 분류예요.";

