// BIT(Behavioral Investor Type) 분류. 순수 함수, 외부 의존성 없음.
//
// Pompian 행동알파 프로세스 1~2단계를 8축에 적용한 것이며,
// 원전의 면담 기반 판별을 설문 축으로 대체한 근사다.
//   능동성   = turnover.ratio
//   위험감수 = (loss_tolerance.ratio + concentration.ratio) / 2
//   composite = (능동성 + 위험감수) / 2
// composite를 1차원 스펙트럼 PRESERVER → FOLLOWER → INDEPENDENT → ACCUMULATOR 4구간으로 나눈다.
// 스펙트럼 양 끝은 감정적 편향, 가운데 둘은 인지적 편향이 지배적이다(biasMode).
// 결과는 소프트 틸트다. 카드 순서와 넛지에만 쓰고 종목을 제거하지 않는다.

import type { StyleAxes, StyleAxisId } from "../types";

export type BitType = "PRESERVER" | "FOLLOWER" | "INDEPENDENT" | "ACCUMULATOR";
export type BiasMode = "emotional" | "cognitive";
export type CardId = "nudge" | "risk" | "financial" | "contribution" | "supply" | "sentiment";

// 회의에서 조정할 초기값. 첫 칸은 항상 넛지(사각지대 우선).
export const CARD_ORDER: Record<BitType, readonly CardId[]> = {
  PRESERVER: ["nudge", "risk", "financial", "contribution", "supply", "sentiment"],
  FOLLOWER: ["nudge", "supply", "sentiment", "risk", "contribution", "financial"],
  INDEPENDENT: ["nudge", "contribution", "financial", "sentiment", "risk", "supply"],
  ACCUMULATOR: ["nudge", "contribution", "sentiment", "supply", "risk", "financial"],
};

export const LOW_CONFIDENCE_THRESHOLD = 0.5;

// 유형 분류에 쓰지 않는 축. "주의할 편향 프로필"로 따로 돌려준다.
export const BIAS_PROFILE_AXES: readonly StyleAxisId[] = [
  "market_participation",
  "rule_adherence",
  "information_reliance",
  "urgency",
  "drawdown_reaction",
];

export interface BitResult {
  type: BitType;
  biasMode: BiasMode;
  activeness: number;
  riskTaking: number;
  composite: number;
  confidence: number; // turnover·loss_tolerance·concentration confidence 평균
  lowConfidence: boolean; // true면 화면에서 유형명을 단정하지 않는다
  ratios: Record<StyleAxisId, number>;
  biasProfile: { axisId: StyleAxisId; ratio: number; confidence: number }[];
  cardOrder: readonly CardId[];
}

export function classifyBit(styleAxes: StyleAxes): BitResult {
  const byId = new Map(styleAxes.axes.map((axis) => [axis.axis_id, axis]));
  const axis = (id: StyleAxisId) => {
    const found = byId.get(id);
    if (!found) throw new Error(`style_axes에 ${id} 축이 없어요.`);
    return found;
  };

  const turnover = axis("turnover");
  const lossTolerance = axis("loss_tolerance");
  const concentration = axis("concentration");
  const activeness = turnover.ratio;
  const riskTaking = (lossTolerance.ratio + concentration.ratio) / 2;
  const composite = (activeness + riskTaking) / 2;
  const type: BitType =
    composite < -0.5
      ? "PRESERVER"
      : composite < 0
        ? "FOLLOWER"
        : composite < 0.5
          ? "INDEPENDENT"
          : "ACCUMULATOR";
  const confidence =
    (turnover.confidence + lossTolerance.confidence + concentration.confidence) / 3;

  return {
    type,
    biasMode: type === "PRESERVER" || type === "ACCUMULATOR" ? "emotional" : "cognitive",
    activeness,
    riskTaking,
    composite,
    confidence,
    lowConfidence: confidence < LOW_CONFIDENCE_THRESHOLD,
    ratios: Object.fromEntries(
      styleAxes.axes.map(({ axis_id, ratio }) => [axis_id, ratio]),
    ) as Record<StyleAxisId, number>,
    biasProfile: BIAS_PROFILE_AXES.map((id) => {
      const { ratio, confidence: axisConfidence } = axis(id);
      return { axisId: id, ratio, confidence: axisConfidence };
    }),
    cardOrder: CARD_ORDER[type],
  };
}

// 화면 표시 이름. 금융회사 투자자 정보 확인서의 5단계 등급명(안정형~공격투자형)과 겹치지 않게 짓는다.
export const BIT_LABEL: Record<BitType, string> = {
  PRESERVER: "자산 보존형",
  FOLLOWER: "추종형",
  INDEPENDENT: "독립 분석형",
  ACCUMULATOR: "적극 축적형",
};

// 대시보드 성향 줄의 "놓치기 쉬운 것"(성우 개선 포인트 2). 유형별 고정 문구 4개, 종목을 거르거나 순서를 바꾸지 않는다.
export const BIT_BLIND_SPOT: Record<BitType, string> = {
  PRESERVER: "떨어진 종목을 오래 들고 있느라 회사 상황이 바뀐 걸 놓치기 쉬워요.",
  FOLLOWER: "많이들 산다는 이유만으로 근거 확인을 건너뛰기 쉬워요.",
  INDEPENDENT: "내 생각과 다른 근거를 가볍게 넘기기 쉬워요.",
  ACCUMULATOR: "한 번에 크게 움직이다 손실이 커질 수 있는 걸 놓치기 쉬워요.",
};

export const BIT_SUMMARY: Record<BitType, string> = {
  PRESERVER: "잃지 않는 것을 먼저 생각하고, 산 종목을 오래 들고 가는 편이에요.",
  FOLLOWER: "시장 흐름과 주변 의견을 참고해 조심스럽게 움직이는 편이에요.",
  INDEPENDENT: "직접 확인한 근거로 판단하고, 필요하면 적극적으로 움직이는 편이에요.",
  ACCUMULATOR: "기회를 적극적으로 찾고, 큰 변동도 감수하며 빠르게 움직이는 편이에요.",
};

export const BIT_TYPES: readonly BitType[] = ["PRESERVER", "FOLLOWER", "INDEPENDENT", "ACCUMULATOR"];

// "다른 성향으로 보기" 프리셋. 분류 3축(turnover·loss_tolerance·concentration)을 각 구간의
// 한가운데 값으로 두고 나머지 축은 내 응답을 그대로 둔다. 화면 state에만 쓰고 저장하지 않는다.
const PRESET_RATIO: Record<BitType, number> = {
  PRESERVER: -0.75,
  FOLLOWER: -0.25,
  INDEPENDENT: 0.25,
  ACCUMULATOR: 0.75,
};
const CLASSIFYING_AXES: readonly StyleAxisId[] = ["turnover", "loss_tolerance", "concentration"];

export function presetStyleAxes(base: StyleAxes, type: BitType): StyleAxes {
  return {
    ...base,
    axes: base.axes.map((axis) =>
      CLASSIFYING_AXES.includes(axis.axis_id)
        ? { ...axis, ratio: PRESET_RATIO[type], confidence: 1 }
        : axis,
    ),
  };
}
