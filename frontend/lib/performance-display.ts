import type {
  ComparisonDeltaRow,
  ComparisonMetricRow,
  ComparisonProfile,
} from "./performance-types";

export type MetricKey =
  | "auc"
  | "hit_rate"
  | "calibration_brier"
  | "calibration_ece"
  | "sharpe"
  | "mdd"
  | "cumulative_return"
  | "trade_count";

export type DeltaMetricKey = Exclude<
  keyof ComparisonDeltaRow,
  "profile" | "sample"
>;

export type DeltaOutcome =
  | "improved"
  | "worsened"
  | "unchanged"
  | "neutral"
  | "unavailable";

export interface MetricDefinition {
  key: MetricKey;
  deltaKey: DeltaMetricKey;
  label: string;
  direction: "higher" | "lower" | "neutral";
  format: "decimal6" | "decimal3" | "decimal2" | "percent" | "integer";
  description?: string;
}

export const METRICS: MetricDefinition[] = [
  {
    key: "auc",
    deltaKey: "delta_B_minus_A_auc",
    label: "ROC-AUC",
    direction: "higher",
    format: "decimal6",
    description: "오를 종목에 더 높은 점수를 주는지 보는 값이에요. 0.5면 동전 던지기 수준, 1에 가까울수록 잘 가려요.",
  },
  {
    key: "hit_rate",
    deltaKey: "delta_B_minus_A_hit_rate",
    label: "상승 여부 일치율",
    direction: "higher",
    format: "decimal6",
    description: "상승 점수가 0.5 이상이면 '상승'으로 보고, 실제로 상승이었는지 맞은 비율이에요.",
  },
  {
    key: "calibration_brier",
    deltaKey: "delta_B_minus_A_calibration_brier",
    label: "Brier",
    direction: "lower",
    format: "decimal6",
    description: "예측한 확률과 실제 결과의 차이예요. 작을수록 확률이 정확해요.",
  },
  {
    key: "calibration_ece",
    deltaKey: "delta_B_minus_A_calibration_ece",
    label: "ECE",
    direction: "lower",
    format: "decimal6",
    description: "'70%'라고 한 일이 실제로 70% 일어났는지의 어긋남이에요. 작을수록 확률을 믿을 만해요.",
  },
  {
    key: "sharpe",
    deltaKey: "delta_B_minus_A_sharpe",
    label: "Sharpe",
    direction: "higher",
    format: "decimal2",
    description: "가격 흔들림 대비 수익이에요. 클수록 같은 위험에서 더 벌었어요.",
  },
  {
    key: "mdd",
    deltaKey: "delta_B_minus_A_mdd",
    label: "MDD",
    direction: "higher",
    format: "percent",
    description: "고점에서 가장 크게 떨어진 폭이에요. 0에 가까울수록 덜 떨어졌어요.",
  },
  {
    key: "cumulative_return",
    deltaKey: "delta_B_minus_A_cumulative_return",
    label: "연도 수익률 평균",
    direction: "higher",
    format: "percent",
    description: "해마다 같은 돈으로 새로 시작해 낸 수익률의 평균이에요. 이어서 굴린 누적 수익률은 아니에요.",
  },
  {
    key: "trade_count",
    deltaKey: "delta_B_minus_A_trade_count",
    label: "거래 수",
    direction: "neutral",
    format: "integer",
  },
];

export const PROFILE_LABEL: Record<ComparisonProfile, string> = {
  stable: "안정형",
  aggressive: "공격형",
};

export function formatMetricValue(
  value: ComparisonMetricRow[MetricKey],
  metric: MetricDefinition,
): string {
  if (value === null || !Number.isFinite(value)) return "미산출";
  if (metric.format === "integer") return Math.round(value).toLocaleString("ko-KR");
  if (metric.format === "percent") return `${(value * 100).toFixed(1)}%`;
  if (metric.format === "decimal2") return value.toFixed(2);
  if (metric.format === "decimal6") return value.toFixed(6);
  return value.toFixed(3);
}

export function formatDeltaValue(
  value: ComparisonDeltaRow[DeltaMetricKey],
  metric: MetricDefinition,
): string {
  if (value === null || !Number.isFinite(value)) return "미산출";
  const sign = value > 0 ? "+" : "";
  if (metric.format === "integer") return `${sign}${Math.round(value).toLocaleString("ko-KR")}`;
  if (metric.format === "percent") return `${sign}${(value * 100).toFixed(1)}%p`;
  if (metric.format === "decimal2") return `${sign}${value.toFixed(2)}`;
  if (metric.format === "decimal6") return `${sign}${value.toFixed(6)}`;
  return `${sign}${value.toFixed(3)}`;
}

export function deltaOutcome(
  value: ComparisonDeltaRow[DeltaMetricKey],
  metric: MetricDefinition,
): DeltaOutcome {
  if (value === null || !Number.isFinite(value)) return "unavailable";
  if (metric.direction === "neutral") return "neutral";
  if (Math.abs(value) < 1e-12) return "unchanged";
  const improved = metric.direction === "higher" ? value > 0 : value < 0;
  return improved ? "improved" : "worsened";
}
