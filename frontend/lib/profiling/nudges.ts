import { SENTIMENT_SHIFT_P90 } from "../providers/sentiment-fixture.ts";
import type { RiskGrade, StyleAxisId } from "../types";
import type { BitResult } from "./bit";

export type NudgeId =
  | "N01" | "N02" | "N03" | "N04" | "N05" | "N06"
  | "N07" | "N08" | "N09" | "N10" | "N11";

export interface NudgeMarket {
  retailNetBuyStreakDays: number;
  retailNetLatest: number; // 최근일 개인 순매수(+)/순매도(-)
  foreignNetLatest: number; // 최근일 외국인 순매수(+)/순매도(-)
  institutionNetBuyDaysOf5: number;
  volatilityPercentile: number; // 0~1, 시장 내 변동성 백분위. 1 = 가장 큼
  drawdownFrom3mHigh: number; // 3개월 고점 대비. -0.15 = -15%
  return3d: number; // 최근 3거래일 누적. 0.10 = +10%
  sentimentChange: number | null; // 뉴스 감성(-1~1) 최근 두 수집일(Live 일별) 변화량. 두 날이 없거나 기사가 적으면 null
  sentimentDayLabel: string; // 최근 수집일이 오늘이면 "오늘", 아니면 "10.08에"
  isTopHolding: boolean;
  isHolding: boolean;
  holdingGain: number | null; // 평단 대비 평가손익(0.12 = +12%). 보유하지 않거나 평단을 모르면 null
  riskGrade: RiskGrade; // 1 매우 위험 ~ 5 매우 안전
}

export interface FiredNudge {
  id: NudgeId;
  text: string;
  axis: StyleAxisId;
  ratio: number;
}

export const MAX_VISIBLE_NUDGES = 2;
const PRIORITY: readonly NudgeId[] = ["N02", "N05", "N11", "N04", "N01"];

// 경계 포함: side 1이면 ratio >= +0.3, side -1이면 ratio <= -0.3.
export const AXIS_THRESHOLD = 0.3;
const STREAK_DAYS = 5;
const INSTITUTION_BUY_DAYS = 4;
const VOLATILITY_TOP_10 = 0.9;
const DRAWDOWN_LIMIT = -0.15;
export const HOLDING_GAIN = 0.1;
const RALLY_3D = 0.1;
// 감성 "급변" 임계 = news_corpus 일별 감성 변화량 |Δ|의 p90.
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
    axis: "information_reliance",
    side: 1,
    market: (m) => m.retailNetBuyStreakDays >= STREAK_DAYS,
    text: "개인 투자자가 5일 연속 더 많이 샀어요. 시장 분위기와 다른 사람의 판단을 근거로 삼는 편이라고 답하셨어요. 지금 판단이 그 흐름을 따라가는 것인지 확인해 보세요.",
  },
  {
    id: "N02",
    axis: "information_reliance",
    side: 1,
    market: (m) => m.retailNetLatest > 0 && m.foreignNetLatest < 0,
    text: "개인은 사고 외국인은 파는 중이에요. 두 집단의 판단이 갈리고 있어요. 어느 쪽 근거를 보고 계신지 짚어 보세요.",
  },
  {
    id: "N03",
    axis: "information_reliance",
    side: 1,
    market: (m) => m.institutionNetBuyDaysOf5 >= INSTITUTION_BUY_DAYS,
    text: "최근 5일 중 4일은 기관이 더 많이 샀어요. 다만 기관이 왜 샀는지는 공개되지 않아요. 내가 보고 있는 근거는 무엇인지 짚어 보세요.",
  },
  {
    id: "N04",
    axis: "drawdown_reaction",
    side: 1,
    market: (m) => m.volatilityPercentile >= VOLATILITY_TOP_10,
    text: "이 종목의 최근 가격 흔들림은 시장에서 상위 10% 안이에요. 가격이 떨어질 때 계획보다 일찍 파는 편이라고 답하셨어요.",
  },
  {
    id: "N05",
    axis: "drawdown_reaction",
    side: 1,
    market: (m) => m.drawdownFrom3mHigh <= DRAWDOWN_LIMIT || Math.abs(m.holdingGain ?? 0) >= HOLDING_GAIN,
    text: (m) => {
      const gain = m.holdingGain ?? 0;
      const percent = `${Math.abs(gain * 100).toFixed(1)}%`;
      if (gain <= -HOLDING_GAIN) return `평균 매입가보다 ${percent} 낮은 상태예요. 처음 살 때 봤던 근거가 지금도 맞는지 확인해 보세요.`;
      if (gain >= HOLDING_GAIN) return `평균 매입가보다 ${percent} 높은 상태예요. 처음 산 이유를 다시 확인해 보세요.`;
      return m.isHolding
        ? "지금 가격이 최근 3개월 최고가보다 크게 낮아요. 처음 살 때 봤던 근거가 지금도 맞는지 확인해 보세요."
        : "지금 가격이 최근 3개월 최고가보다 크게 낮아요. 왜 떨어졌는지 근거를 먼저 확인해 보세요.";
    },
  },
  {
    id: "N06",
    axis: "urgency",
    side: 1,
    market: (m) => m.return3d >= RALLY_3D,
    text: "최근 3거래일 동안 크게 올랐어요. 결정을 빨리 내리는 편이라고 답하셨어요.",
  },
  {
    id: "N07",
    axis: "urgency",
    side: 1,
    market: (m) => m.sentimentChange !== null && Math.abs(m.sentimentChange) >= SENTIMENT_SHIFT,
    text: (m) => `${m.sentimentDayLabel} 이 종목의 뉴스 분위기가 직전 수집일과 크게 달라졌어요. 여러 기사가 같은 일을 다루고 있을 수 있어요.`,
  },
  {
    id: "N08",
    axis: "concentration",
    side: 1,
    market: (m) => m.isTopHolding,
    text: "가진 종목 중 이 종목의 비중이 가장 커요. 몇 종목에 모아 담는 편이라고 답하셨어요.",
  },
  {
    id: "N09",
    axis: "turnover",
    side: 1,
    market: always,
    text: "보유 기간이 짧은 편이라고 답하셨어요. 이 종목을 얼마나 들고 갈지 정해 두셨다면 지금 다시 확인해 보세요.",
  },
  {
    id: "N10",
    // rule_adherence는 이름과 반대로 +가 "규칙을 덜 지킨다"(상황별 재량)는 뜻이다.
    axis: "rule_adherence",
    side: 1,
    market: always,
    text: "미리 정한 매매 기준을 지키기 어려운 편이라고 답하셨어요. 이 종목에 적어 둔 판단 메모가 있다면 지금 다시 읽어 보세요.",
  },
  {
    id: "N11",
    axis: "loss_tolerance",
    side: -1,
    market: (m) => m.riskGrade <= 2,
    text: "이 종목의 위험도는 높은 편이에요. 원금이 줄어드는 데 민감한 편이라고 답하셨어요.",
  },
];

export function checkpointItems(nudges: FiredNudge[], riskNote: string | null): { key: string; text: string }[] {
  const items = nudges.map(({ id, text }) => (id === "N11" && riskNote ? { key: "risk", text: riskNote } : { key: id, text }));
  if (riskNote && !nudges.some(({ id }) => id === "N11")) items.push({ key: "risk", text: riskNote });
  return items.slice(0, MAX_VISIBLE_NUDGES);
}

function rank(id: NudgeId) {
  const index = PRIORITY.indexOf(id);
  return index === -1 ? PRIORITY.length : index;
}

export function selectNudges(
  bit: BitResult,
  market: NudgeMarket,
  limit = MAX_VISIBLE_NUDGES,
): FiredNudge[] {
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
