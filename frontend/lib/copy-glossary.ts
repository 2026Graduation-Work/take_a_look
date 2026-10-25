// 쉬운 말 사전. 화면 문구는 여기서 가져다 쓰고, 개발 용어를 화면에 직접 쓰지 않는다.
// 금지어 검사는 copy-rules.ts. 개발 용어는 "계산 근거" 영역에서만 쓴다.

import { HOLDING_GAIN } from "./profiling/nudges.ts";
import type { FiredNudge, NudgeMarket } from "./profiling/nudges.ts";

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

// 과거 비슷한 경우가 언제, 몇 번인지(chart pack distribution의 실제 기간과 표본 수). 비슷함 = 상승 점수 ±0.01, 가격 흔들림 ±5%
export function similarCasesLine(start: string, end: string, count: number, stocks: number): string {
  const month = (iso: string) => `${iso.slice(0, 4)}년 ${Number(iso.slice(5, 7))}월`;
  return `${month(start)}~${month(end)} 중 오늘과 점수가 비슷했던 ${count.toLocaleString("ko-KR")}번(${stocks.toLocaleString("ko-KR")}개 종목)의 결과예요.`;
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

// 용어 설명 단계(DESIGN.md '용어 설명 단계'). 라벨 = 쉬운 이름 + 약어 괄호, ⓘ = 정의 한 문장 + 읽는 법 한 문장.
// 약어와 전문 용어만 ⓘ(tip)를 단다. 매출, 영업이익처럼 일상어에 가까운 말은 라벨만으로 읽힌다.
// 모든 용어에 쉬운 이름, 정의, 읽는 법이 있는지 copy-rules.test.ts가 지킨다.
export interface TermInfo {
  label: string;
  define: string;
  read: string;
  tip: boolean;
}
export const TERM_INFO = {
  per: { label: "이익 대비 주가(PER)", tip: true,
    define: "주가가 회사 1년 이익의 몇 배인지예요.",
    read: "업종마다 보통 수준이 달라, 코스피 전체와 견준 값은 대략적인 위치로만 봐요." },
  pbr: { label: "순자산 대비 주가(PBR)", tip: true,
    define: "주가가 회사가 가진 순자산(자산에서 빚을 뺀 것)의 몇 배인지예요.",
    read: "1배보다 낮으면 주가가 순자산보다 낮게 매겨졌다는 뜻이에요. 이익을 못 내는 회사도 낮게 나와요." },
  roe: { label: "자기자본 수익률(ROE)", tip: true,
    define: "회사가 자기 돈으로 1년에 몇 %를 벌었는지예요.",
    read: "꾸준히 높으면 가진 돈을 잘 굴린다는 뜻이에요. 한 해만 보지 말고 흐름을 함께 봐요." },
  operating_margin: { label: "영업이익률", tip: false,
    define: "매출 100원 중 본업으로 남긴 이익이에요.",
    read: "같은 업종끼리 비교해야 뜻이 있어요." },
  debt_ratio: { label: "부채비율", tip: true,
    define: "빚이 자기 돈의 몇 %인지예요.",
    read: "높을수록 빚에 기대는 정도가 크다는 뜻이에요. 은행처럼 빚이 사업인 업종은 원래 높아요." },
  revenue_growth: { label: "매출 증가율", tip: false,
    define: "1년 전보다 매출이 늘어난 정도예요.",
    read: "한 해 값은 크게 흔들릴 수 있어 몇 해 흐름을 함께 봐요." },
  volatility: { label: "가격 흔들림", tip: true,
    define: "하루하루 가격이 오르내린 폭을 1년 기준으로 환산한 변동성이에요.",
    read: "높을수록 짧은 기간에 크게 오르거나 내릴 수 있어요." },
  model_signal: { label: "모델 신호", tip: true,
    define: "앞으로 4주 안에 주가가 위 기준선에 먼저 닿을지(상승), 아래 기준선에 닿을지(하락), 둘 다 아닐지(중립) 세 점수를 내고 가장 큰 쪽을 보여 줘요.",
    read: "따로 정한 문턱값은 없고, 기준선의 원 값은 더 알아보기의 계산 근거에 있어요." },
  sigma: { label: "평소 흔들림 폭(σ)", tip: true,
    define: "최근 하루하루 가격이 오르내린 폭의 표준적인 크기예요.",
    read: "모델 기준선은 이 폭의 몇 배로 정해서, 많이 흔들리는 종목일수록 기준선이 멀어요." },
  trading_value: { label: "거래대금", tip: true,
    define: "하루 동안 사고판 주식의 금액을 모두 더한 값이에요.",
    read: "평소보다 크면 그날 관심이 몰렸다는 뜻이에요." },
  net_buy: { label: "순매수", tip: true,
    define: "산 주식 수에서 판 주식 수를 뺀 값이에요.",
    read: "+면 판 것보다 많이 샀고, −면 많이 팔았어요. 거래량과 견줘 보면 크기를 알 수 있어요." },
} as const satisfies Record<string, TermInfo>;
export type TermKey = keyof typeof TERM_INFO;

// 비교 기준 한 줄. 높아요, 낮아요, 비슷해요까지만 쓰고 싸다, 비싸다 같은 판정은 쓰지 않는다(#372).
// 차이가 기준값의 10% 안이면 비슷해요.
export function compareLine(value: number, median: number, basis: string, unit: string): string {
  const level = Math.abs(value - median) <= Math.abs(median) * 0.1 ? "비슷해요" : value > median ? "높아요" : "낮아요";
  const shown = median.toLocaleString("ko-KR", { maximumFractionDigits: 1 });
  return level === "비슷해요"
    ? `${basis} 중간값 ${shown}${unit}와 비슷해요.`
    : `${basis} 중간값 ${shown}${unit}보다 ${level}.`;
}

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

export const STYLE_TYPE_BASIS = "보유 기간, 손실을 견디는 정도, 종목을 모아 담는 성향을 종합하면";

// 뉴스 분위기: 하루 기사가 이보다 적은 날은 툴팁과 계산 근거에 주의 안내
export const FEW_ARTICLES = 3;

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
// 1주일 때만 기간 전환 왼쪽에 붙는 설명(13px). 4주(기본)는 설명 없음(10/20 사용자 피드백)
export const SHORT_HORIZON_NOTE = "짧은 흔들림에 더 민감해요.";
// 왜 1주와 4주인가(지인 재테스트 10/21). 근거는 AGENTS.md '성향별 2모델'(stable ↔ H20, aggressive ↔ H5)과
// docs/research/psychology-ab-2019-2025(H5, H20을 같은 방식으로 평가). 길이 자체를 고른 실험 문서는 아직 없어 그 말은 쓰지 않는다
export const HORIZON_WHY = "1주 모델은 짧게 사고파는 성향, 4주 모델은 오래 들고 가는 성향에 맞춰 따로 학습했어요. 기본은 4주이고, 1주로 바꾸면 화면 전체가 같은 기간을 따라요.";
export const HORIZON_GUIDE = "모델은 두 개예요. 1주(5거래일) 모델은 짧게 사고파는 성향, 4주(20거래일) 모델은 오래 들고 가는 성향에 맞춰 따로 학습했어요. 두 모델 모두 2019~2025년 연도별 비교 실험에서 같은 방식으로 평가했고, 결과는 모델 성적표에 있어요.";

export const STYLE_TYPE_SOURCE = "분류 참고: Pompian의 행동재무학 연구";

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
export const LIVE_NEWS_SCOPE = "기업 소식과 관련 산업과 시장 뉴스를 함께 반영해요.";
// 뉴스 감성과 별도로 계산하는 가격 지표 안내.
export const PRICE_CONTEXT_CAPTION = "뉴스 분위기와 함께 보는 주가 흐름";

// 계산 근거 묶음의 숫자 문장. 화면 본문은 단계 말만 쓰고, 점수는 여기서만 범위와 함께 쓴다(DESIGN.md 화면 숫자 규칙).
const signedScore = (value: number) => `${value > 0 ? "+" : value < 0 ? "−" : ""}${Math.abs(value).toFixed(2)}`;

// 유형 점수 = (보유 기간 답 + (손실 감내 답 + 집중 답) ÷ 2) ÷ 2 (lib/profiling/bit.ts)
export function typeRule(composite: number): string {
  return `투자 유형 점수 ${signedScore(composite)}(범위 −1~+1)를 −0.5, 0, +0.5에서 네 유형으로 나눴어요.`;
}

export const AXIS_STAGE_RULE = "설문 답은 축마다 −1~+1 점수예요. −0.6, −0.2, +0.2, +0.6에서 다섯 칸으로 나눠 보여 줘요.";

// 모델 신호 기준선(chart pack inference.barriers = 종가 × (1 ± 배수 × σ)). 원과 배수는 계산 근거에만 쓴다.
export function barrierRule(close: number, up: number, down: number, sigma: number, horizonWeeks: number): string {
  const won = (value: number) => `${Math.round(value).toLocaleString("ko-KR")}원`;
  const times = (price: number) => (Math.abs(price / close - 1) / sigma).toFixed(2).replace(/\.?0+$/, "");
  return `모델 신호 기준선: 위 ${won(up)}, 아래 ${won(down)}. 오늘 종가 ${won(close)}에서 평소 흔들림 폭(σ, 하루 수익률의 표준편차 ${(sigma * 100).toFixed(1)}%)의 ${times(up)}배 위, ${times(down)}배 아래예요. 앞으로 ${horizonWeeks}주 안에 고가가 위 기준선에 먼저 닿으면 상승, 종가가 아래 기준선에 먼저 닿으면 하락, 둘 다 아니면 중립으로 배운 모델이고, 세 점수 중 가장 큰 쪽을 신호로 보여 줘요.`;
}

export const PSYCHOLOGY_NOTE = "최근 20거래일 수익과 흔들림, 60거래일 평균 매입가 대비 지금 가격을 함께 봤어요.";

// 제공된 합산 점수만 설명하고 개별 가격 지표의 방향은 추측하지 않는다.
export function psychologyReason(axis: number): string {
  return `가격 흐름 분위기 점수 ${signedScore(axis)}(범위 −1 움츠러듦~+1 들뜸). 20거래일 수익과 흔들림, 60거래일 평균 매입가 대비 가격을 합친 값을 같은 다섯 칸으로 나눴어요.`;
}

// 선택된 체크포인트의 실제 발화 조건만 설명한다. 조건·정렬·점수는 바꾸지 않는다.
export function checkpointReason(nudge: FiredNudge, market: NudgeMarket): string {
  const percent = (value: number) => `${Math.abs(value * 100).toFixed(1)}%`;
  switch (nudge.id) {
    case "N01": return `다른 사람의 판단을 따르는 쪽으로 답했고, 개인이 ${market.retailNetBuyStreakDays}거래일 연속 순매수해 표시했어요.`;
    case "N02": return "다른 사람의 판단을 따르는 쪽으로 답했고, 개인은 순매수, 외국인은 순매도여서 표시했어요.";
    case "N03": return `다른 사람의 판단을 따르는 쪽으로 답했고, 최근 5거래일 중 ${market.institutionNetBuyDaysOf5}일 기관이 순매수해 표시했어요.`;
    case "N04": return "하락할 때 정리하는 쪽으로 답했고, 이 종목의 가격 흔들림이 시장 상위 10% 안이라 표시했어요.";
    case "N05": {
      const gain = market.holdingGain;
      const fact = gain !== null && Math.abs(gain) >= HOLDING_GAIN
        ? `현재가가 평균 매입가보다 ${percent(gain)} ${gain < 0 ? "낮아" : "높아"}`
        : `현재가가 최근 3개월 최고가보다 ${percent(market.drawdownFrom3mHigh)} 낮아`;
      return `하락할 때 정리하는 쪽으로 답했고, ${fact} 표시했어요.`;
    }
    case "N06": return `결정을 서두르는 쪽으로 답했고, 최근 3거래일 수익률이 +${percent(market.return3d)}여서 표시했어요.`;
    case "N07": return `결정을 서두르는 쪽으로 답했고, ${market.sentimentDayLabel} 뉴스 점수가 직전 수집일과 크게 달라져 표시했어요.`;
    case "N08": return "소수 종목에 모아 담는 쪽으로 답했고, 보유 종목 중 이 종목의 비중이 가장 커 표시했어요.";
    case "N09": return "설문에서 보유 기간이 짧은 쪽으로 답해 표시했어요.";
    case "N10": return "설문에서 정해 둔 매매 기준보다 상황에 따라 판단하는 쪽으로 답해 표시했어요.";
    case "N11": return "원금 보전을 중시하는 쪽으로 답했고, 이 종목의 위험도가 높은 편이라 표시했어요.";
  }
}
