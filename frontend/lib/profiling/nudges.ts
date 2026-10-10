// 편향 넛지 11종과 화면 안내 1종. 순수 함수, 외부 의존성 없음.
// 문구는 2026-09-22 쉬운 말·해요체로 다듬었다(팀 승인). 판정 조건·근거 축은 그대로다.
// 형식 규칙: 사실 + 사실 병렬. 인과 주장·추종 유도·매수/매도 권유 금지.

import { SENTIMENT_SHIFT_P90 } from "../providers/sentiment-fixture.ts";
import type { RiskGrade, StyleAxisId } from "../types";
import type { BitResult, BitType } from "./bit";

export type NudgeId =
  | "N01" | "N02" | "N03" | "N04" | "N05" | "N06"
  | "N07" | "N08" | "N09" | "N10" | "N11";

// 종목·시장 사실. 수급·감성·시세 어댑터 결과에서 계산해 넣는다.
export interface NudgeMarket {
  retailNetBuyStreakDays: number; // 최근일부터 센 개인 연속 순매수 일수
  retailNetLatest: number; // 최근일 개인 순매수(+)/순매도(-)
  foreignNetLatest: number; // 최근일 외국인 순매수(+)/순매도(-)
  institutionNetBuyDaysOf5: number; // 최근 5거래일 중 기관 순매수 일수
  volatilityPercentile: number; // 0~1, 시장 내 변동성 백분위. 1 = 가장 큼
  drawdownFrom3mHigh: number; // 3개월 고점 대비. -0.15 = -15%
  return3d: number; // 최근 3거래일 누적. 0.10 = +10%
  sentimentChange: number | null; // 뉴스 감성(-1~1) 최근 두 수집일(Live 일별) 변화량. 두 날이 없거나 기사가 적으면 null
  sentimentDayLabel: string; // 최근 수집일 말: 오늘 수집이면 "오늘", 아니면 "10.08에" — 지난 날을 "오늘"이라 부르지 않는다
  isTopHolding: boolean; // 보유 종목 중 비중 1위
  riskGrade: RiskGrade; // 1 매우 위험 ~ 5 매우 안전
}

export interface FiredNudge {
  id: NudgeId;
  text: string;
  axis: StyleAxisId; // 근거가 된 성향 축
  ratio: number; // 그 축의 실제 값. 화면에서 발화 이유를 검증할 수 있게 함께 넘긴다
}

export const MAX_VISIBLE_NUDGES = 2;
// 앞에 있을수록 먼저 노출. 여기 없는 id는 id 순으로 뒤에 붙는다.
const PRIORITY: readonly NudgeId[] = ["N02", "N05", "N11", "N04", "N01"];

// 성향 임계. 경계 포함: side 1이면 ratio >= +0.3, side -1이면 ratio <= -0.3.
export const AXIS_THRESHOLD = 0.3;
const STREAK_DAYS = 5;
const INSTITUTION_BUY_DAYS = 4;
const VOLATILITY_TOP_10 = 0.9;
const DRAWDOWN_LIMIT = -0.15;
const RALLY_3D = 0.1;
// 감성 "급변" 임계 = news_corpus 일별 감성 변화량 |Δ|의 p90.
// 계산: frontend/scripts/build_sentiment_fixture.py. 산출값·표본·감성 백엔드는 sentiment-fixture.ts 헤더에 있다.
const SENTIMENT_SHIFT = SENTIMENT_SHIFT_P90;

interface NudgeRule {
  id: NudgeId;
  axis: StyleAxisId;
  side: 1 | -1;
  market: (m: NudgeMarket) => boolean;
  text: string | ((m: NudgeMarket) => string);
}

const always = () => true;

export const NUDGES: readonly NudgeRule[] = [
  {
    id: "N01",
    // information_reliance: -1=본인 판단, +1=시장·타인 추종
    axis: "information_reliance",
    side: 1,
    market: (m) => m.retailNetBuyStreakDays >= STREAK_DAYS,
    text: "개인 투자자가 5일 연속 더 많이 샀어요. 시장 분위기와 다른 사람의 판단을 근거로 삼는 편이라고 답하셨어요. 지금 판단이 그 흐름을 따라가는 것인지 확인해 보세요.",
  },
  {
    id: "N02",
    // information_reliance: -1=본인 판단, +1=시장·타인 추종
    axis: "information_reliance",
    side: 1,
    market: (m) => m.retailNetLatest > 0 && m.foreignNetLatest < 0,
    text: "개인은 사고 외국인은 파는 중이에요. 두 집단의 판단이 갈리고 있어요. 어느 쪽 근거를 보고 계신지 짚어 보세요.",
  },
  {
    id: "N03",
    // information_reliance: -1=본인 판단, +1=시장·타인 추종
    axis: "information_reliance",
    side: 1,
    market: (m) => m.institutionNetBuyDaysOf5 >= INSTITUTION_BUY_DAYS,
    text: "최근 5일 중 4일은 기관이 더 많이 샀어요. 다만 기관이 왜 샀는지는 공개되지 않아요. 내가 보고 있는 근거는 무엇인지 짚어 보세요.",
  },
  {
    id: "N04",
    // drawdown_reaction: -1=하락 시 유지, +1=하락 시 이탈
    axis: "drawdown_reaction",
    side: 1,
    market: (m) => m.volatilityPercentile >= VOLATILITY_TOP_10,
    text: "이 종목의 최근 가격 흔들림은 시장에서 상위 10% 안이에요. 가격이 떨어질 때 계획보다 일찍 파는 편이라고 답하셨어요.",
  },
  {
    id: "N05",
    // drawdown_reaction: -1=하락 시 유지, +1=하락 시 이탈
    axis: "drawdown_reaction",
    side: 1,
    market: (m) => m.drawdownFrom3mHigh <= DRAWDOWN_LIMIT,
    text: "지금 가격이 최근 3개월 최고가보다 크게 낮아요. 처음 살 때 봤던 근거가 지금도 맞는지 확인해 보세요.",
  },
  {
    id: "N06",
    // urgency: -1=여유, +1=조급함
    axis: "urgency",
    side: 1,
    market: (m) => m.return3d >= RALLY_3D,
    text: "최근 3거래일 동안 크게 올랐어요. 결정을 빨리 내리는 편이라고 답하셨어요.",
  },
  {
    id: "N07",
    // urgency: -1=여유, +1=조급함
    axis: "urgency",
    side: 1,
    market: (m) => m.sentimentChange !== null && Math.abs(m.sentimentChange) >= SENTIMENT_SHIFT,
    text: (m) => `${m.sentimentDayLabel} 이 종목의 뉴스 분위기가 직전 수집일과 크게 달라졌어요. 여러 기사가 같은 일을 다루고 있을 수 있어요.`,
  },
  {
    id: "N08",
    // concentration: -1=폭넓은 분산, +1=소수 집중
    axis: "concentration",
    side: 1,
    market: (m) => m.isTopHolding,
    text: "가진 종목 중 이 종목의 비중이 가장 커요. 몇 종목에 모아 담는 편이라고 답하셨어요.",
  },
  {
    id: "N09",
    // turnover: -1=장기 보유, +1=단기 매매
    axis: "turnover",
    side: 1,
    market: always,
    text: "보유 기간이 짧은 편이라고 답하셨어요. 이 종목을 얼마나 들고 갈지 정해 두셨다면 지금 다시 확인해 보세요.",
  },
  {
    id: "N10",
    // rule_adherence: -1=사전 규칙 준수, +1=상황별 재량.
    // 이름과 반대로 +가 "규칙을 덜 지킨다"는 뜻이다. "지키기 어려운 편"은 + 쪽이다.
    axis: "rule_adherence",
    side: 1,
    market: always,
    text: "미리 정한 매매 기준을 지키기 어려운 편이라고 답하셨어요. 이 종목에 적어 둔 판단 메모가 있다면 지금 다시 읽어 보세요.",
  },
  {
    id: "N11",
    // loss_tolerance: -1=원금 보전, +1=수익 기회. risk_grade: 1=매우 위험 ~ 5=매우 안전
    axis: "loss_tolerance",
    side: -1,
    market: (m) => m.riskGrade <= 2,
    text: "이 종목의 위험도는 높은 편이에요. 원금이 줄어드는 데 민감한 편이라고 답하셨어요.",
  },
];

// 체크포인트 줄(최대 MAX_VISIBLE_NUDGES). 위험도 안내는 한 줄만(#256): 성향 숫자가 들어간 riskNote가 있으면
// N11 자리를 대신하고, N11이 없으면 뒤에 붙는다.
export function checkpointItems(nudges: FiredNudge[], riskNote: string | null): { key: string; text: string }[] {
  const items = nudges.map(({ id, text }) => (id === "N11" && riskNote ? { key: "risk", text: riskNote } : { key: id, text }));
  if (riskNote && !nudges.some(({ id }) => id === "N11")) items.push({ key: "risk", text: riskNote });
  return items.slice(0, MAX_VISIBLE_NUDGES);
}

// 넛지가 아니라 화면 하단 안내 배너(기존 N12). BIT 스펙트럼 수동 쪽 두 유형에만 보인다.
export const SCREEN_GUIDE_NOTICE: { appliesTo: readonly BitType[]; text: string } = {
  appliesTo: ["PRESERVER", "FOLLOWER"],
  text: "이 화면의 지표 중 처음 보시는 것이 있을 수 있어요. 각 근거 아래 '왜 봐야 하나요?'에 보는 이유를 적어 두었어요.",
};

function rank(id: NudgeId) {
  const index = PRIORITY.indexOf(id);
  return index === -1 ? PRIORITY.length : index;
}

export function selectNudges(
  bit: BitResult,
  market: NudgeMarket,
  limit = MAX_VISIBLE_NUDGES,
): FiredNudge[] {
  // 같은 축 근거 넛지는 우선순위가 높은 하나만 남긴다.
  // 같은 사실을 두 번 말하지 않고, 노출 슬롯에 서로 다른 관점이 오게 하려는 것이다.
  const seenAxes = new Set<StyleAxisId>();
  return NUDGES.filter(
    (rule) => rule.side * bit.ratios[rule.axis] >= AXIS_THRESHOLD && rule.market(market),
  )
    .sort((left, right) => rank(left.id) - rank(right.id) || left.id.localeCompare(right.id))
    .filter((rule) => {
      if (seenAxes.has(rule.axis)) return false;
      seenAxes.add(rule.axis);
      return true;
    })
    .slice(0, limit)
    .map(({ id, text, axis }) => ({ id, text: typeof text === "function" ? text(market) : text, axis, ratio: bit.ratios[axis] }));
}
