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
    description: "상승 라벨(2)과 나머지 라벨(0·1)의 판별력입니다. 0.5는 무작위 순위 수준, 1에 가까울수록 높습니다.",
  },
  {
    key: "hit_rate",
    deltaKey: "delta_B_minus_A_hit_rate",
    label: "상승 여부 일치율",
    direction: "higher",
    format: "decimal3",
    description: "상승 점수 0.5 이상을 상승으로 분류했을 때 실제 상승 라벨(2) 여부와 일치한 비율입니다. 세 방향 정확도는 아닙니다.",
  },
  {
    key: "calibration_brier",
    deltaKey: "delta_B_minus_A_calibration_brier",
    label: "Brier",
    direction: "lower",
    format: "decimal3",
    description: "예측 확률과 실제 결과 사이의 오차를 측정하며, 값이 작을수록 확률 예측이 정교합니다.",
  },
  {
    key: "calibration_ece",
    deltaKey: "delta_B_minus_A_calibration_ece",
    label: "ECE",
    direction: "lower",
    format: "decimal3",
    description: "모델이 제시한 확률이 실제 발생 빈도와 얼마나 어긋나는지 나타내는 보정 오차로, 값이 작을수록 확률을 신뢰할 수 있습니다.",
  },
  {
    key: "sharpe",
    deltaKey: "delta_B_minus_A_sharpe",
    label: "Sharpe",
    direction: "higher",
    format: "decimal2",
    description: "감수한 변동성 대비 초과 수익의 크기로, 값이 클수록 위험 대비 성과가 좋습니다.",
  },
  {
    key: "mdd",
    deltaKey: "delta_B_minus_A_mdd",
    label: "MDD",
    direction: "higher",
    format: "percent",
    description: "평가 기간 중 고점 대비 최대 하락폭으로, 0에 가까울수록(하락폭이 작을수록) 안정적입니다.",
  },
  {
    key: "cumulative_return",
    deltaKey: "delta_B_minus_A_cumulative_return",
    label: "연도 수익률 평균",
    direction: "higher",
    format: "percent",
    description: "매년 자금을 초기화한 독립 평가의 연도별 수익률 단순평균입니다. 연속 운용 누적 수익률은 아닙니다.",
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
