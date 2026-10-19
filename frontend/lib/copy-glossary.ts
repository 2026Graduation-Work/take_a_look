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
  relatedNewsSentiment: "종목 관련 뉴스 분위기",
  volatility: "가격 흔들림",
  nudge: "확인할 것",
  market: "시장 분위기",
  financial: "재무 상태",
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
  "'얼마나 자주 사고파는지' 답과 '손실을 견디고 몇 종목에 모으는지' 답을 평균한 -1~+1 점수를 -0.5, 0, +0.5에서 네 유형으로 나눴어요.";

// 스펙트럼 양 끝(감정적 편향)과 가운데(인지적 편향)
export const BIAS_MODE_WORD = {
  emotional: "양 끝 유형이라 그때그때 기분에 판단이 흔들리기 쉬운 편",
  cognitive: "가운데 유형이라 이미 알던 정보만 믿고 새 정보를 덜 보기 쉬운 편",
} as const;

// 가격 흐름 분위기 = (20거래일 수익 ÷ 그동안의 흔들림, 60거래일 평균 매입가 대비 지금 가격의 위치)의 평균
export const PSYCHOLOGY_RULE =
  "최근 20거래일 수익을 그동안의 흔들림으로 나눈 값과, 최근 60거래일 동안 사람들이 평균적으로 산 가격 대비 지금 가격의 위치를 평균했어요.";

// 뉴스 분위기: 하루 기사가 이보다 적은 날은 툴팁과 계산 근거에 주의 안내
export const FEW_ARTICLES = 3;
export const FEW_ARTICLES_RULE = `하루 관련 기사가 ${FEW_ARTICLES}건 미만이면 한두 기사의 말투가 그날 점수를 크게 움직일 수 있어요. 이 값은 참고만 해 주세요.`;

// 모델 신호 방향의 화면 이름. 사전 참가자·지도교수 모두 '상방·하방'을 헷갈려 B안으로 바꿨다(10/15 면담·E2).
// 화면의 신호 방향 단어는 모두 여기서 가져온다. 내부 값(up/flat/down)과 DB는 그대로.
// B안 '상승 쪽·하락 쪽'에서 '쪽'을 뺐다(10/18 사용자 피드백: 상승·중립·하락으로 통일)
export const SIGNAL_WORD = { up: "상승", flat: "중립", down: "하락" } as const;
export type SignalWord = (typeof SIGNAL_WORD)[HorizonDirection];
// 기간별 방향도 신호 이름과 같은 말(상승·중립·하락)로 통일(10/18)
export const DIRECTION_WORD: Record<HorizonDirection, string> = SIGNAL_WORD;

// 모델 신호 단어 옆에 붙이는 기간. 신호 방향을 "지난 가격이 올랐다"로 읽지 않게 앞으로의 방향임을 바로 보인다(사전 참가자 P0 10/13)
export const HORIZON_AHEAD = { 5: "앞으로 1주", 20: "앞으로 4주" } as const;

// 보유 맵 아래·오늘 신호 목록 각주가 같은 문장을 쓴다(#278 QA). 기간은 위 상수와 같다.
// 대시보드 신호 기간(앞으로 4주 기본, 1주로 바꿔 볼 수 있다 — 지도교수 10/15 "왜 4주?")
export type SignalHorizon = keyof typeof HORIZON_AHEAD;
export const SHORT_HORIZON_NOTE = "1주 신호는 짧은 흔들림에 더 크게 반응해요.";

export const CHECKPOINT_RULE = "설문 답이 한쪽으로 0.3 넘게 기울고, 지금 이 종목의 시장 조건이 맞을 때만 보여요.";

export const STYLE_TYPE_SOURCE = "행동재무학의 투자자 유형 연구(Pompian)에서 착안해 설문으로 가늠한 분류예요.";

// 공시 유형(docs/disclosure-kinds.md) → 화면 이름. 풀이(ⓘ) 없이 이름만으로 이해되게 쓴다(화면 규칙 v2)
export const DISCLOSURE_KIND: Record<string, { label: string }> = {
  market_action: { label: "거래소 투자 주의" },
  business_risk: { label: "경영 위험" },
  inquiry: { label: "거래소 질문에 답변" },
  periodic: { label: "정기 실적 보고서" },
  earnings: { label: "실적 발표" },
  contract: { label: "공급 계약" },
  capital_raise: { label: "유상증자(새 주식 발행)" },
  bonus_issue: { label: "무상증자(주식 나눠 주기)" },
  bond: { label: "채권 발행" },
  buyback: { label: "자기 주식 사고팔기" },
  dividend: { label: "배당" },
  restructure: { label: "합병과 분할" },
  ownership: { label: "대주주 지분 변동" },
  lawsuit: { label: "소송" },
  investment: { label: "다른 회사 투자와 보증" },
  shareholder_meeting: { label: "주주총회" },
  investor_relations: { label: "기업설명회" },
  securities_filing: { label: "증권 발행 서류" },
  other: { label: "그 밖의 공시" },
};

// Live 문맥 필터 적용 범위. 과거/기타 종목에 동일 기준을 안내하지 않는다.
export const CONTEXTUAL_LIVE_NEWS_CODES = new Set(["005930", "005380", "035720", "035420", "068270", "247540"]);
export const LIVE_NEWS_SCOPE = "기업 소식과 관련 산업과 시장 뉴스를 함께 반영합니다.";
// 뉴스 감성과 별도로 계산하는 가격 지표 안내.
export const PRICE_CONTEXT_CAPTION = "뉴스 분위기와 함께 보는 주가 흐름";
