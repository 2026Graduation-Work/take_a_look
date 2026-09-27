// 설문 응답 → schema profiling_output v1.1 변환. 8축 채점은 lib/profiling/style-scoring.ts가 정본이다.
// 결정론이며 LLM을 쓰지 않는다. 종목을 거르는 값은 avoided_assets(사용자가 직접 고른 항목)뿐이다.

import { BIT_LABEL, BIT_SUMMARY, classifyBit } from "./profiling/bit.ts";
import type {
  ActionIntent,
  InvestorProfileSummary,
  ProfilingOutput,
  RiskFlag,
  StyleAxes,
  StyleAxisId,
} from "./types";
import {
  confidencePerAxis,
  detectContradictions,
  reduceToLegacyFields,
  scoreStyleAxes,
  STYLE_AXIS_IDS,
  type StyleAnswers,
} from "./profiling/style-scoring.ts";

export { STYLE_AXIS_IDS };

export const EXPERIENCE_CHOICES = [
  { id: "under_6m", label: "6개월 미만", years: 0.3 },
  { id: "6m_2y", label: "6개월~2년", years: 1 },
  { id: "2y_5y", label: "2~5년", years: 3.5 },
  { id: "over_5y", label: "5년 이상", years: 7 },
] as const;
export type ExperienceChoice = (typeof EXPERIENCE_CHOICES)[number]["id"];

export const AVOIDED_ASSET_LABELS: Record<RiskFlag, string> = {
  spac: "SPAC",
  managed_stock: "관리종목",
  low_liquidity: "저유동성 종목",
  penny_stock: "동전주",
  high_volatility: "고변동성 종목",
  preferred_stock: "우선주",
};

export const AVOIDED_ASSET_DESCRIPTIONS: Record<RiskFlag, string> = {
  spac: "합병 대상 기업이 아직 정해지지 않은 상장 서류상의 회사예요.",
  managed_stock: "부실 위험으로 거래소가 별도 관리하며 상장폐지될 수 있는 종목이에요.",
  low_liquidity: "거래량이 적어 원하는 가격에 사고팔기 어려운 종목이에요.",
  penny_stock: "주가가 매우 낮고 변동성과 투기성이 큰 종목이에요.",
  high_volatility: "짧은 기간에 주가가 크게 오르내리는 종목이에요.",
  preferred_stock: "의결권 대신 배당을 우선 받는 주식으로 보통주와 가격 흐름이 다를 수 있어요.",
};

// 8축에 원천 문항이 없는 v1.0 필드. 구 설문의 투자 기간 → 유동성 필요도 표를 기간 구간으로 이어 쓴다.
const LIQUIDITY_BY_MONTHS = [
  { maxMonths: 12, ratio: 0.7 },
  { maxMonths: 60, ratio: 0.25 },
  { maxMonths: Infinity, ratio: 0.1 },
] as const;
const TARGET_RETURN_ANNUAL = 0.08;
const CURRENT_MARKET_ANXIETY_INITIAL = 0.5; // text 블록이 채운다
const OVERHEATING_CAUTION_INITIAL = 0.61; // chart·text 블록이 채운다
const OVERHEATING_CAUTION_CONFIDENCE = 0.55;

const FREE_TEXT_SIGNAL_RULES = [
  { field: "fomo_index", keywords: ["남들 다 버는데", "뒤처지는", "놓칠까"], value: 0.8 },
  { field: "panic_sell_tendency", keywords: ["마이너스", "손실", "잠을 못"], value: 0.75 },
] as const;

export interface SurveyAnswers {
  user_id: string;
  session_id: string;
  timestamp: string;
  style: StyleAnswers; // 리커트 응답(mode의 문항)
  mode?: "short" | "quick"; // 기본 quick. short = 온보딩 16문항
  experience: ExperienceChoice;
  avoided_assets: RiskFlag[];
  free_text?: string;
  // 결과 확인 단계에서 사용자가 직접 옮긴 축. 있으면 채점값 대신 이 ratio를 쓴다.
  adjusted_axes?: Partial<Record<StyleAxisId, number>>;
  preferred_sectors?: string[];
  portfolio?: ProfilingOutput["portfolio"];
  investment_amount_krw?: number;
  action_intent?: ActionIntent;
  target_ticker?: string;
  market_regime_hint?: string;
  benchmark_index?: string;
}

// ── 3축 요약: 대시보드 성향 카드와 결과 화면이 같은 8축에서 읽는다 ─────
// 위험 감수 = mean(loss_tolerance, concentration), 흔들림 민감도 = mean(urgency,
// drawdown_reaction, information_reliance), 투자 기간 = turnover. 값은 ratio를 0~100으로 옮긴 것이다.
export interface ThreeAxisSummary {
  riskTaking: number; // 0 원금 보전·분산 ~ 100 수익 기회·집중
  sensitivity: number; // 0 흔들림 적음 ~ 100 흔들림 큼
  horizonScore: number; // 0 장기 보유 ~ 100 단기 매매
  horizon: "short" | "mid" | "long";
}

const toScore = (ratio: number) => Math.round(((ratio + 1) / 2) * 100);
const mean = (values: number[]) => values.reduce((sum, value) => sum + value, 0) / values.length;

function horizonForScore(horizonScore: number): ThreeAxisSummary["horizon"] {
  return horizonScore >= 67 ? "short" : horizonScore >= 34 ? "mid" : "long";
}

export function threeAxisSummary(styleAxes: StyleAxes): ThreeAxisSummary {
  const ratio = (id: StyleAxisId) => styleAxes.axes.find(({ axis_id }) => axis_id === id)!.ratio;
  const horizonScore = toScore(ratio("turnover"));
  return {
    riskTaking: toScore(mean([ratio("loss_tolerance"), ratio("concentration")])),
    sensitivity: toScore(
      mean([ratio("urgency"), ratio("drawdown_reaction"), ratio("information_reliance")]),
    ),
    horizonScore,
    horizon: horizonForScore(horizonScore),
  };
}

// 성향 카드 표시값. 유형명은 BIT만 쓴다(금융회사 투자자 등급명과 겹치는 이름을 쓰지 않는다).
// 8축이 없는 프로필(v1.0)은 유형을 단정하지 않는다.
export function summaryFromStyleAxes(
  styleAxes: StyleAxes | null | undefined,
  identity: Pick<InvestorProfileSummary, "displayName" | "avatarLabel" | "surveyedAt">,
): InvestorProfileSummary {
  if (!styleAxes) {
    return {
      ...identity,
      profileTypeLabel: "8축 진단 전",
      personaLabel: "설문을 다시 하면 유형이 나와요",
      riskTolerance: 50,
      sentimentSensitivity: 50,
      horizon: "mid",
    };
  }
  const bit = classifyBit(styleAxes);
  const summary = threeAxisSummary(styleAxes);
  return {
    ...identity,
    profileTypeLabel: bit.lowConfidence ? "유형 확인 중" : BIT_LABEL[bit.type],
    personaLabel: bit.lowConfidence ? "응답이 엇갈려 유형을 단정하지 않았어요" : BIT_SUMMARY[bit.type],
    riskTolerance: summary.riskTaking,
    sentimentSensitivity: summary.sensitivity,
    horizon: summary.horizon,
  };
}

export function summaryFromProfilingOutput(
  output: ProfilingOutput,
  identity: Pick<InvestorProfileSummary, "displayName" | "avatarLabel">,
): InvestorProfileSummary {
  const completedAt = new Date(output.timestamp);
  const surveyedAt = Number.isNaN(completedAt.getTime())
    ? ""
    : `${completedAt.getFullYear()}.${String(completedAt.getMonth() + 1).padStart(2, "0")}`;
  return summaryFromStyleAxes(output.style_axes, { ...identity, surveyedAt });
}

// 결과 확인 단계의 수동 조정을 반영한다. 신뢰도·응답 수는 채점값 그대로 둔다.
export function applyAdjustments(
  styleAxes: StyleAxes,
  adjusted: Partial<Record<StyleAxisId, number>> = {},
): StyleAxes {
  return {
    ...styleAxes,
    axes: styleAxes.axes.map((axis) => ({ ...axis, ratio: adjusted[axis.axis_id] ?? axis.ratio })),
  };
}

export function convertSurveyAnswers(input: unknown): ProfilingOutput {
  const answers = parseSurveyAnswers(input);
  const styleAxes = applyAdjustments(
    scoreStyleAxes(answers.style, answers.mode === "short" ? "short" : "quick"),
    answers.adjusted_axes,
  );
  const legacy = reduceToLegacyFields(styleAxes);
  const axis = (id: StyleAxisId) => styleAxes.axes.find(({ axis_id }) => axis_id === id)!;
  const experience = EXPERIENCE_CHOICES.find(({ id }) => id === answers.experience)!;

  const rawText = answers.free_text?.trim() ?? "";
  const extractedSignals: Record<string, number> = {};
  for (const rule of FREE_TEXT_SIGNAL_RULES) {
    if (rule.keywords.some((keyword) => rawText.includes(keyword))) {
      extractedSignals[rule.field] = rule.value;
    }
  }

  return {
    user_id: requireText(answers.user_id, "user_id"),
    session_id: requireText(answers.session_id, "session_id"),
    timestamp: requireText(answers.timestamp, "timestamp"),
    investor_profile: {
      risk_tolerance: legacy.risk_tolerance,
      time_horizon_months: legacy.time_horizon_months,
      time_horizon_days: legacy.time_horizon_days,
      liquidity_need_ratio: LIQUIDITY_BY_MONTHS.find(
        ({ maxMonths }) => legacy.time_horizon_months <= maxMonths,
      )!.ratio,
      target_return_annual: TARGET_RETURN_ANNUAL,
      investment_experience_years: experience.years,
      // risk_tolerance 0.6 이상이면 aggressive 모델(chart model_type과 매칭)
      profile_type: legacy.risk_tolerance >= 0.6 ? "aggressive" : "stable",
    },
    psychological_state: {
      fomo_index: legacy.fomo_index,
      panic_sell_tendency: legacy.panic_sell_tendency,
      herding_score: legacy.herding_score,
      // 본인 판단 ↔ 시장·타인 추종 축의 반대편. 구 설문의 정보 출처 문항을 대신한다.
      self_confidence: round6((1 - axis("information_reliance").ratio) / 2),
      current_market_anxiety: CURRENT_MARKET_ANXIETY_INITIAL,
      overheating_caution: OVERHEATING_CAUTION_INITIAL,
    },
    constraints: {
      avoided_assets: [...new Set(answers.avoided_assets)],
      preferred_sectors: [...(answers.preferred_sectors ?? [])],
    },
    portfolio: answers.portfolio ?? { holdings: [], watchlist: [] },
    free_text_signal: {
      raw_text: rawText,
      extracted_signals: extractedSignals,
      conflict_with_survey: false,
    },
    confidence_per_field: {
      ...confidencePerAxis(styleAxes),
      time_horizon_months: axis("turnover").confidence,
      liquidity_need_ratio: axis("turnover").confidence,
      self_confidence: axis("information_reliance").confidence,
      overheating_caution: OVERHEATING_CAUTION_CONFIDENCE,
    },
    style_axes: styleAxes,
    contradictions: detectContradictions(styleAxes),
    context: {
      investment_amount_krw: answers.investment_amount_krw ?? 0,
      action_intent: answers.action_intent ?? "buy_consideration",
      ...(answers.target_ticker ? { target_ticker: answers.target_ticker } : {}),
      ...(answers.market_regime_hint ? { market_regime_hint: answers.market_regime_hint } : {}),
      ...(answers.benchmark_index ? { benchmark_index: answers.benchmark_index } : {}),
    },
    meta: {
      schema_version: "1.1.0",
      source: "profiling_block",
      confidence: round6(mean(styleAxes.axes.map(({ confidence }) => confidence))),
    },
  };
}

function parseSurveyAnswers(input: unknown): SurveyAnswers {
  if (!isRecord(input)) throw new Error("설문 응답이 존재하지 않습니다.");

  const timestamp = requireText(input.timestamp, "timestamp");
  if (Number.isNaN(Date.parse(timestamp))) {
    throw new Error("timestamp는 ISO 8601 날짜여야 합니다.");
  }
  if (!isRecord(input.style)) throw new Error("8축 문항 응답(style)이 필요합니다.");
  if (!EXPERIENCE_CHOICES.some(({ id }) => id === input.experience)) {
    throw new Error("투자 경험 응답이 올바르지 않습니다.");
  }
  const avoided = input.avoided_assets ?? [];
  if (!Array.isArray(avoided) || avoided.some((flag) => !(flag in AVOIDED_ASSET_LABELS))) {
    throw new Error("제외할 종목 유형 응답이 올바르지 않습니다.");
  }

  if (input.mode !== undefined && input.mode !== "short" && input.mode !== "quick") {
    throw new Error("진단 모드(mode)는 short 또는 quick이어야 합니다.");
  }

  return {
    user_id: requireText(input.user_id, "user_id"),
    session_id: requireText(input.session_id, "session_id"),
    timestamp,
    style: input.style as StyleAnswers,
    mode: input.mode as SurveyAnswers["mode"],
    experience: input.experience as ExperienceChoice,
    avoided_assets: avoided as RiskFlag[],
    free_text: optionalText(input.free_text, "free_text"),
    adjusted_axes: parseAdjustedAxes(input.adjusted_axes),
    preferred_sectors: parseStringArray(input.preferred_sectors ?? [], "preferred_sectors"),
    portfolio: parsePortfolio(input.portfolio),
    investment_amount_krw: optionalNonNegativeInteger(
      input.investment_amount_krw,
      "investment_amount_krw",
    ),
    action_intent: parseActionIntent(input.action_intent),
    target_ticker: optionalText(input.target_ticker, "target_ticker"),
    market_regime_hint: optionalText(input.market_regime_hint, "market_regime_hint"),
    benchmark_index: optionalText(input.benchmark_index, "benchmark_index"),
  };
}

function parseAdjustedAxes(value: unknown): SurveyAnswers["adjusted_axes"] {
  if (value === undefined) return undefined;
  if (
    !isRecord(value) ||
    Object.entries(value).some(
      ([id, ratio]) => !STYLE_AXIS_IDS.includes(id as StyleAxisId) || !inRange(ratio, -1, 1),
    )
  ) {
    throw new Error("adjusted_axes는 축 id별 -1~1 값이어야 합니다.");
  }
  return value as SurveyAnswers["adjusted_axes"];
}

// schema v1.1 style_axes 계약 검사: 8축 전부, ratio -1~1, confidence 0~1.
export function isStyleAxes(value: unknown): value is StyleAxes {
  if (
    !isRecord(value) ||
    (value.assessment_mode !== "quick" && value.assessment_mode !== "detailed") ||
    !Array.isArray(value.axes) ||
    value.axes.length !== STYLE_AXIS_IDS.length
  ) {
    return false;
  }
  const axes: unknown[] = value.axes;
  const ids = new Set(axes.map((axis) => (isRecord(axis) ? axis.axis_id : null)));
  return (
    STYLE_AXIS_IDS.every((id) => ids.has(id)) &&
    axes.every(
      (axis) =>
        isRecord(axis) &&
        inRange(axis.ratio, -1, 1) &&
        inRange(axis.confidence, 0, 1) &&
        Number.isInteger(axis.answered_count) &&
        Number.isInteger(axis.question_count),
    )
  );
}

function inRange(value: unknown, min: number, max: number) {
  return typeof value === "number" && value >= min && value <= max;
}

function round6(value: number) {
  return Math.round(value * 1_000_000) / 1_000_000 + 0;
}

function parseStringArray(value: unknown, field: string): string[] {
  if (!Array.isArray(value) || value.some((item) => typeof item !== "string")) {
    throw new Error(`${field} 응답은 문자열 배열이어야 합니다.`);
  }
  return [...new Set(value)];
}

function parsePortfolio(value: unknown): ProfilingOutput["portfolio"] | undefined {
  if (value === undefined) return undefined;
  if (!isRecord(value) || !Array.isArray(value.holdings)) {
    throw new Error("portfolio 응답이 올바르지 않습니다.");
  }
  const holdings = value.holdings.map((holding, index) => {
    if (!isRecord(holding)) {
      throw new Error(`portfolio.holdings[${index}] 응답이 올바르지 않습니다.`);
    }
    return {
      ticker: requireText(holding.ticker, `holdings[${index}].ticker`),
      name: requireText(holding.name, `holdings[${index}].name`),
      quantity: requireNonNegativeInteger(
        holding.quantity,
        `holdings[${index}].quantity`,
      ),
      avg_buy_price: requireNonNegativeInteger(
        holding.avg_buy_price,
        `holdings[${index}].avg_buy_price`,
      ),
    };
  });
  return {
    holdings,
    watchlist: parseStringArray(value.watchlist ?? [], "portfolio.watchlist"),
  };
}

function parseActionIntent(value: unknown): ActionIntent | undefined {
  if (value === undefined) return undefined;
  const allowed: ActionIntent[] = [
    "buy_consideration",
    "sell_consideration",
    "hold_consideration",
  ];
  if (typeof value !== "string" || !allowed.includes(value as ActionIntent)) {
    throw new Error("action_intent 응답이 올바르지 않습니다.");
  }
  return value as ActionIntent;
}

function optionalText(value: unknown, field: string): string | undefined {
  if (value === undefined) return undefined;
  if (typeof value !== "string") throw new Error(`${field} 값은 문자열이어야 합니다.`);
  return value.trim();
}

function optionalNonNegativeInteger(
  value: unknown,
  field: string,
): number | undefined {
  return value === undefined ? undefined : requireNonNegativeInteger(value, field);
}

function requireNonNegativeInteger(value: unknown, field: string): number {
  if (!Number.isInteger(value) || (value as number) < 0) {
    throw new Error(`${field} 값은 0 이상의 정수여야 합니다.`);
  }
  return value as number;
}

export function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}



function requireText(value: unknown, field: string) {
  if (typeof value !== "string") throw new Error(`${field} 값은 문자열이어야 합니다.`);
  const normalized = value.trim();
  if (!normalized) throw new Error(`${field} 값이 필요합니다.`);
  return normalized;
}
