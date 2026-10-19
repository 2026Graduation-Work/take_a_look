// 8축 스코어링·신뢰도·모순 검출·v1.0 필드 축약. 채점 로직의 정본이다.
// (backend/profiling/survey/style_scoring.py를 옮겼다. style-golden-cases.json이 그 결과를 고정한다.)
//
// 전부 결정론이다. 같은 응답이면 항상 같은 값이 나오고 LLM을 쓰지 않는다.
// 산출물은 소프트 틸트이며 종목 제거에 쓰지 않는다.
//
// 축 점수: 응답을 축 방향 점수(-2~+2)로 옮기고 가중평균을 극단값 2로 나눠 ratio(-1~+1)를 얻는다.
//   - 리커트: (응답값 - 3) × direction
//   - 시나리오: 고른 선택지의 scores[축] (선택지가 그 축을 적지 않았으면 0)
// 신뢰도: 일관성 × 응답률. 일관성은 축 안 응답들의 가중 평균절대편차를 2로 나눠 뒤집는다.

import type { StyleAxes, StyleAxis, StyleAxisId } from "../types.ts";
import bank from "./style-questions.json" with { type: "json" };

export type AssessmentMode = StyleAxes["assessment_mode"];
// short(16문항)는 온보딩용 문항 선택일 뿐 채점 규칙은 같다. 스키마 v1.x의 assessment_mode enum이
// quick·detailed로 고정(freeze)돼 있어, 저장할 때는 quick으로 기록한다. 축별 question_count(2)로 구분된다.
export type SurveyMode = "short" | AssessmentMode;

interface LikertQuestion {
  id: string;
  type: "likert";
  axis: StyleAxisId;
  direction: 1 | -1;
  weight: number;
  quick: boolean;
  short?: boolean;
  text: string;
}

export interface ScenarioOption {
  id: string;
  label: string;
  scores: Partial<Record<StyleAxisId, number>>; // 축 방향 점수 -2~+2
}

interface ScenarioQuestion {
  id: string;
  type: "scenario";
  weight: number;
  quick: boolean;
  text: string;
  options: ScenarioOption[];
}

export type StyleQuestion = LikertQuestion | ScenarioQuestion;

export interface AxisDefinition {
  id: StyleAxisId;
  negative_label: string;
  positive_label: string;
  section: string;
  help: string;
}

// 리커트는 1~5, 시나리오는 선택지 id
export type StyleAnswers = Record<string, number | string>;

export const LIKERT_OPTIONS: readonly { value: number; label: string }[] = bank.likert.options;
const LIKERT_NEUTRAL = bank.likert.neutral;
const LIKERT_EXTREME = bank.likert.extreme;
export const AXES = bank.axes as AxisDefinition[];
export const STYLE_AXIS_IDS: readonly StyleAxisId[] = AXES.map(({ id }) => id);
const QUESTIONS = bank.questions as StyleQuestion[];
const TURNOVER_DAY_RULES: readonly { max_ratio: number; days: number }[] =
  bank.turnover_day_rules;

export function questionsForMode(mode: SurveyMode): StyleQuestion[] {
  if (mode === "detailed") return QUESTIONS;
  if (mode === "short") return QUESTIONS.filter((question) => question.type === "likert" && question.short);
  return QUESTIONS.filter(({ quick }) => quick);
}

function axesOf(question: StyleQuestion): StyleAxisId[] {
  if (question.type === "likert") return [question.axis];
  return [...new Set(question.options.flatMap(({ scores }) => Object.keys(scores) as StyleAxisId[]))];
}

// 응답을 축 방향 점수로. 미응답이면 null, 계약 위반이면 에러.
function orientedScores(
  question: StyleQuestion,
  raw: number | string | undefined,
): Partial<Record<StyleAxisId, number>> | null {
  if (raw === undefined) return null;
  if (question.type === "likert") {
    if (!LIKERT_OPTIONS.some(({ value }) => value === raw)) {
      throw new Error(`${question.id} 응답은 1~5여야 합니다.`);
    }
    return { [question.axis]: ((raw as number) - LIKERT_NEUTRAL) * question.direction };
  }
  const option = question.options.find(({ id }) => id === raw);
  if (!option) throw new Error(`${question.id} 응답이 선택지에 없습니다.`);
  return Object.fromEntries(axesOf(question).map((axis) => [axis, option.scores[axis] ?? 0]));
}

export function scoreStyleAxes(answers: StyleAnswers, mode: SurveyMode): StyleAxes {
  return scoreWithQuestions(answers, mode === "detailed" ? "detailed" : "quick", questionsForMode(mode));
}

// 문항 목록을 직접 받는 채점기. 시나리오형 문항이 은행에 들어오기 전에 테스트가 쓴다.
export function scoreWithQuestions(
  answers: StyleAnswers,
  mode: AssessmentMode,
  questions: StyleQuestion[],
): StyleAxes {
  const allowed = new Set(questions.map(({ id }) => id));
  const outOfMode = QUESTIONS.filter(({ id }) => id in answers && !allowed.has(id)).map(({ id }) => id);
  if (outOfMode.length) {
    throw new Error(`이 모드에 없는 문항 응답이 있습니다: ${outOfMode.join(", ")}`);
  }

  const entries = new Map(STYLE_AXIS_IDS.map((id) => [id, [] as { oriented: number; weight: number }[]]));
  const totals = new Map(STYLE_AXIS_IDS.map((id) => [id, 0]));
  const counts = new Map(STYLE_AXIS_IDS.map((id) => [id, 0]));

  for (const question of questions) {
    const scores = orientedScores(question, answers[question.id]);
    for (const axis of axesOf(question)) {
      totals.set(axis, totals.get(axis)! + question.weight);
      counts.set(axis, counts.get(axis)! + 1);
      if (scores) entries.get(axis)!.push({ oriented: scores[axis]!, weight: question.weight });
    }
  }

  return {
    assessment_mode: mode,
    axes: STYLE_AXIS_IDS.map((axisId) =>
      axisResult(axisId, entries.get(axisId)!, totals.get(axisId)!, counts.get(axisId)!),
    ),
  };
}

function axisResult(
  axisId: StyleAxisId,
  entries: { oriented: number; weight: number }[],
  totalWeight: number,
  questionCount: number,
): StyleAxis {
  if (!entries.length || totalWeight <= 0) {
    return { axis_id: axisId, ratio: 0, confidence: 0, answered_count: 0, question_count: questionCount };
  }
  const answeredWeight = entries.reduce((sum, { weight }) => sum + weight, 0);
  const mean = entries.reduce((sum, { oriented, weight }) => sum + oriented * weight, 0) / answeredWeight;
  const deviation =
    entries.reduce((sum, { oriented, weight }) => sum + Math.abs(oriented - mean) * weight, 0) /
    answeredWeight;
  const consistency = 1 - deviation / LIKERT_EXTREME;
  const coverage = answeredWeight / totalWeight;
  return {
    axis_id: axisId,
    ratio: round6(clamp(mean / LIKERT_EXTREME, -1, 1)),
    confidence: round6(clamp(consistency * coverage, 0, 1)),
    answered_count: entries.length,
    question_count: questionCount,
  };
}

// 프리셋(축 방향 강도 -2~+2)을 리커트 응답으로 조립한다. 역채점 문항에는 반대 부호가 들어간다.
export function answersFromPattern(
  pattern: Partial<Record<StyleAxisId, number>>,
  mode: SurveyMode,
): StyleAnswers {
  const answers: StyleAnswers = {};
  for (const question of questionsForMode(mode)) {
    if (question.type !== "likert") continue;
    answers[question.id] = LIKERT_NEUTRAL + (pattern[question.axis] ?? 0) * question.direction;
  }
  return answers;
}

// ── 모순 검출 ─────────────────────────────────────────────────────────
// observation은 관측 서술만 담는다. 행동 제안·권유 문구를 넣지 않는다.
export interface Contradiction {
  id: string;
  axes: StyleAxisId[];
  severity: "caution" | "high";
  observation: string;
  follow_up_question: string;
}

const MIN_CONFIDENCE_FOR_CONTRADICTION = 0.3;

const CONTRADICTION_RULES: readonly (Contradiction & {
  conditions: Partial<Record<StyleAxisId, ["<=" | ">=", number]>>;
})[] = [
  {
    id: "loss_averse_but_concentrated",
    axes: ["loss_tolerance", "concentration"],
    conditions: { loss_tolerance: ["<=", -0.2], concentration: [">=", 0.3] },
    severity: "high",
    observation: "'원금을 지키는 게 먼저'라고 답했지만 '몇 종목에 몰아서 투자'하는 쪽도 골랐어요.",
    follow_up_question: "한 종목이 전체의 몇 %를 넘으면 부담스럽게 느끼시나요?",
  },
  {
    id: "long_horizon_but_reactive",
    axes: ["turnover", "urgency", "drawdown_reaction"],
    conditions: { turnover: ["<=", -0.2], urgency: [">=", 0.3], drawdown_reaction: [">=", 0.2] },
    severity: "caution",
    observation: "투자 기간은 길게 잡았지만, 조급함과 하락 때 팔고 나가고 싶은 마음도 크게 나왔어요.",
    follow_up_question: "하락 폭이 어느 정도일 때 계획을 다시 보고 싶으신가요?",
  },
  {
    id: "discretionary_but_loss_averse",
    axes: ["rule_adherence", "loss_tolerance"],
    conditions: { rule_adherence: [">=", 0.3], loss_tolerance: ["<=", -0.3] },
    severity: "caution",
    observation: "손실은 크게 부담스럽다고 답했지만, 미리 정한 기준보다 그때의 판단을 따르는 쪽을 골랐어요.",
    follow_up_question: "다시 점검할 기준을 미리 정해두는 것과 그때 판단하는 것 중 어느 쪽이 편하신가요?",
  },
  {
    id: "herding_but_concentrated",
    axes: ["information_reliance", "concentration"],
    conditions: { information_reliance: [">=", 0.4], concentration: [">=", 0.4] },
    severity: "high",
    observation: "주변 의견과 시장 분위기를 판단 근거로 삼는 편인데, 몇 종목에 몰아서 투자하는 쪽도 골랐어요.",
    follow_up_question: "그 종목을 담은 이유를 직접 확인한 자료로 설명할 수 있으신가요?",
  },
  {
    id: "benchmark_focused_but_short_horizon",
    axes: ["market_participation", "turnover"],
    conditions: { market_participation: ["<=", -0.3], turnover: [">=", 0.3] },
    severity: "caution",
    observation: "시장 지수만큼의 성과를 중요하게 보면서, 보유 기간은 짧게 가져가려 해요.",
    follow_up_question: "성과를 어느 기간 단위로 지수와 비교해 보고 싶으신가요?",
  },
];

// 화면 문장: 관측 + 확인 질문 한 줄(해요체). 예전에 저장된 결과도 지금 문장으로 보이게 id로 다시 찾는다.
export function contradictionText(item: Pick<Contradiction, "id" | "observation" | "follow_up_question">): string {
  const rule = CONTRADICTION_RULES.find(({ id }) => id === item.id) ?? item;
  return `${rule.observation} ${rule.follow_up_question}`;
}

export function detectContradictions(styleAxes: StyleAxes): Contradiction[] {
  const byId = new Map(styleAxes.axes.map((axis) => [axis.axis_id, axis]));
  return CONTRADICTION_RULES.filter(
    ({ axes, conditions }) =>
      axes.every((id) => byId.get(id)!.confidence >= MIN_CONFIDENCE_FOR_CONTRADICTION) &&
      Object.entries(conditions).every(([id, [operator, bound]]) => {
        const ratio = byId.get(id as StyleAxisId)!.ratio;
        return operator === "<=" ? ratio <= bound : ratio >= bound;
      }),
  ).map(({ id, axes, severity, observation, follow_up_question }) => ({
    id,
    axes: [...axes],
    severity,
    observation,
    follow_up_question,
  }));
}

// ── v1.0 필드 축약 (schema style_axes 설명과 같은 규칙) ────────────────
const LEGACY_RATIO_FIELDS = [
  ["risk_tolerance", "loss_tolerance"],
  ["fomo_index", "urgency"],
  ["panic_sell_tendency", "drawdown_reaction"],
  ["herding_score", "information_reliance"],
] as const;

export function reduceToLegacyFields(styleAxes: StyleAxes) {
  const ratio = (id: StyleAxisId) => styleAxes.axes.find(({ axis_id }) => axis_id === id)!.ratio;
  const unit = (id: StyleAxisId) => round6((ratio(id) + 1) / 2);
  const days = daysForTurnover(ratio("turnover"));
  return {
    risk_tolerance: unit("loss_tolerance"),
    fomo_index: unit("urgency"),
    panic_sell_tendency: unit("drawdown_reaction"),
    herding_score: unit("information_reliance"),
    time_horizon_days: days,
    time_horizon_months: Math.round(days / 30),
  };
}

export function confidencePerAxis(styleAxes: StyleAxes): Record<string, number> {
  const confidence = (id: StyleAxisId) =>
    styleAxes.axes.find(({ axis_id }) => axis_id === id)!.confidence;
  return Object.fromEntries(LEGACY_RATIO_FIELDS.map(([field, axis]) => [field, confidence(axis)]));
}

// turnover ratio → 투자 기간(일). 회전율이 낮을수록 길다.
export function daysForTurnover(ratio: number): number {
  if (ratio < -1 || ratio > 1) throw new Error("turnover ratio는 -1~1이어야 합니다.");
  const rule = TURNOVER_DAY_RULES.find(({ max_ratio }) => ratio < max_ratio);
  if (!rule) throw new Error("보유기간 구간표가 -1~1 전체를 덮어야 합니다.");
  return rule.days;
}

function clamp(value: number, low: number, high: number) {
  return Math.max(low, Math.min(high, value));
}

// Python round(x, 6)과 같은 자릿수. 음수 -0은 0으로 둔다.
function round6(value: number) {
  return Math.round(value * 1_000_000) / 1_000_000 + 0;
}
