import { readFile } from "node:fs/promises";
import path from "node:path";
import { performanceResults } from "./mock-performance.ts";
import type {
  ComparisonDeltaRow,
  ComparisonMetricRow,
  ComparisonProfile,
  ComparisonResults,
  ComparisonSample,
  ComparisonVariant,
  PerformanceExperiment,
} from "./performance-types";

export interface PerformanceDataBundle {
  data: ComparisonResults;
  isSample: boolean;
  conclusion: string;
}

const RESULTS_DIRECTORY = path.join(
  process.cwd(),
  "artifacts",
  "performance",
);
const DEFAULT_RESULTS_FILE = "comparison_results.json";

const PROFILES = ["stable", "aggressive"] as const;
const VARIANTS = ["A", "B"] as const;
const SAMPLES = ["all", "volatile_top_20pct"] as const;
const METRIC_NUMBER_FIELDS = [
  "positive_rate",
  "hit_rate",
  "calibration_brier",
  "calibration_ece",
] as const;
const BACKTEST_FIELDS = ["sharpe", "mdd", "cumulative_return"] as const;
const DELTA_METRIC_MAP = [
  ["auc", "delta_B_minus_A_auc"],
  ["hit_rate", "delta_B_minus_A_hit_rate"],
  ["calibration_brier", "delta_B_minus_A_calibration_brier"],
  ["calibration_ece", "delta_B_minus_A_calibration_ece"],
  ["sharpe", "delta_B_minus_A_sharpe"],
  ["mdd", "delta_B_minus_A_mdd"],
  ["cumulative_return", "delta_B_minus_A_cumulative_return"],
  ["trade_count", "delta_B_minus_A_trade_count"],
] as const;

const SAMPLE_CONCLUSION =
  "현재 수치는 화면 구조 검증용 샘플이에요. 실제 비교 실험 결과가 들어오기 전에는 A/B 성능 차이에 대한 연구 결론으로 사용하지 않아요.";

export async function loadPerformanceData(): Promise<PerformanceDataBundle> {
  const configuredFile = process.env.PERFORMANCE_RESULTS_FILE?.trim();
  if (configuredFile && path.basename(configuredFile) !== configuredFile) {
    throw new Error(
      "PERFORMANCE_RESULTS_FILE은 artifacts/performance 아래의 파일명만 지정할 수 있어요.",
    );
  }
  const resultsPath = path.join(
    RESULTS_DIRECTORY,
    configuredFile || DEFAULT_RESULTS_FILE,
  );

  let serialized: string;
  try {
    serialized = await readFile(resultsPath, "utf8");
  } catch (error) {
    if (!configuredFile && isMissingFile(error)) {
      return {
        data: performanceResults,
        isSample: true,
        conclusion: SAMPLE_CONCLUSION,
      };
    }
    throw new Error(
      `비교실험 결과를 읽지 못했습니다 (${path.basename(resultsPath)}): ${errorMessage(error)}`,
      { cause: error },
    );
  }

  let parsed: unknown;
  try {
    parsed = JSON.parse(serialized);
  } catch (error) {
    throw new Error(`비교실험 결과 JSON 파싱 실패: ${errorMessage(error)}`, {
      cause: error,
    });
  }

  const data = validatePerformanceResults(parsed);
  return {
    data,
    isSample: false,
    conclusion: NO_MEANINGFUL_GAIN,
  };
}

export function validatePerformanceResults(value: unknown): ComparisonResults {
  assertRecord(value, "root");
  const fourRuns = validateMetricRows(
    value.four_run_metrics,
    "four_run_metrics",
    "all",
  );
  const volatileRuns = validateMetricRows(
    value.volatile_subsample_metrics,
    "volatile_subsample_metrics",
    "volatile_top_20pct",
  );
  const deltas = validateDeltaRows(value.comparison_deltas);

  validateDeltaConsistency(fourRuns, volatileRuns, deltas);
  return {
    ...(value.experiment === undefined ? {} : { experiment: validateExperiment(value.experiment) }),
    four_run_metrics: sortMetricRows(fourRuns),
    volatile_subsample_metrics: sortMetricRows(volatileRuns),
    comparison_deltas: sortDeltaRows(deltas),
  };
}

function validateMetricRows(
  value: unknown,
  label: string,
  expectedSample: ComparisonSample,
): ComparisonMetricRow[] {
  if (!Array.isArray(value)) throw new Error(`${label}는 배열이어야 해요.`);
  if (value.length !== 4) throw new Error(`${label}는 정확히 4런이어야 해요.`);

  const rows = value.map((candidate, index) => {
    const rowPath = `${label}[${index}]`;
    assertRecord(candidate, rowPath);
    assertEnum(candidate.profile, PROFILES, `${rowPath}.profile`);
    assertEnum(candidate.variant, VARIANTS, `${rowPath}.variant`);
    assertEnum(candidate.sample, SAMPLES, `${rowPath}.sample`);
    if (candidate.sample !== expectedSample) {
      throw new Error(`${rowPath}.sample은 ${expectedSample}이어야 해요.`);
    }
    const expectedFeatureSet = candidate.variant === "A" ? "baseline" : "treatment";
    if (candidate.feature_set !== expectedFeatureSet) {
      throw new Error(
        `${rowPath}.feature_set은 ${candidate.variant} 런에서 ${expectedFeatureSet}이어야 해요.`,
      );
    }

    assertInteger(candidate.feature_count, `${rowPath}.feature_count`, 1);
    assertInteger(candidate.sample_rows, `${rowPath}.sample_rows`, 1);
    assertInteger(candidate.sample_dates, `${rowPath}.sample_dates`, 1);
    if (candidate.trade_count !== null) assertInteger(candidate.trade_count, `${rowPath}.trade_count`, 0);
    assertNullableFiniteNumber(candidate.auc, `${rowPath}.auc`);
    for (const field of METRIC_NUMBER_FIELDS) {
      assertFiniteNumber(candidate[field], `${rowPath}.${field}`);
    }
    for (const field of BACKTEST_FIELDS) assertNullableFiniteNumber(candidate[field], `${rowPath}.${field}`);
    for (const field of [
      "positive_rate",
      "hit_rate",
      "calibration_brier",
      "calibration_ece",
    ] as const) {
      assertRange(candidate[field], `${rowPath}.${field}`, 0, 1);
    }
    if (candidate.auc !== null) assertRange(candidate.auc, `${rowPath}.auc`, 0, 1);
    if (candidate.mdd !== null) assertRange(candidate.mdd, `${rowPath}.mdd`, -1, 0);
    return candidate as unknown as ComparisonMetricRow;
  });

  assertCompleteMetricPairs(rows, label);
  for (const profile of PROFILES) {
    const a = findMetric(rows, profile, "A");
    const b = findMetric(rows, profile, "B");
    if (a.sample_rows !== b.sample_rows || a.sample_dates !== b.sample_dates || !sameNumber(a.positive_rate, b.positive_rate)) {
      throw new Error(`${label}:${profile}의 A/B 공통 표본이 일치하지 않아요.`);
    }
  }
  return rows;
}

function validateDeltaRows(value: unknown): ComparisonDeltaRow[] {
  const label = "comparison_deltas";
  if (!Array.isArray(value)) throw new Error(`${label}는 배열이어야 해요.`);
  if (value.length !== 4) throw new Error(`${label}는 정확히 4행이어야 해요.`);

  const rows = value.map((candidate, index) => {
    const rowPath = `${label}[${index}]`;
    assertRecord(candidate, rowPath);
    assertEnum(candidate.profile, PROFILES, `${rowPath}.profile`);
    assertEnum(candidate.sample, SAMPLES, `${rowPath}.sample`);
    for (const [, deltaKey] of DELTA_METRIC_MAP) {
      assertNullableFiniteNumber(candidate[deltaKey], `${rowPath}.${deltaKey}`);
    }
    return candidate as unknown as ComparisonDeltaRow;
  });

  const expected = new Set(
    PROFILES.flatMap((profile) => SAMPLES.map((sample) => `${profile}:${sample}`)),
  );
  for (const row of rows) {
    const key = `${row.profile}:${row.sample}`;
    if (!expected.delete(key)) throw new Error(`${label}에 중복되거나 알 수 없는 행: ${key}`);
  }
  if (expected.size) throw new Error(`${label}에 누락된 행: ${[...expected].join(", ")}`);
  return rows;
}

function validateDeltaConsistency(
  fourRuns: ComparisonMetricRow[],
  volatileRuns: ComparisonMetricRow[],
  deltas: ComparisonDeltaRow[],
): void {
  for (const profile of PROFILES) {
    for (const sample of SAMPLES) {
      const metrics = sample === "all" ? fourRuns : volatileRuns;
      const baseline = findMetric(metrics, profile, "A");
      const treatment = findMetric(metrics, profile, "B");
      const delta = deltas.find(
        (candidate) => candidate.profile === profile && candidate.sample === sample,
      );
      if (!delta) throw new Error(`델타 행을 찾지 못했습니다: ${profile}:${sample}`);

      for (const [metricKey, deltaKey] of DELTA_METRIC_MAP) {
        const baselineValue = baseline[metricKey] as number | null;
        const treatmentValue = treatment[metricKey] as number | null;
        const actual = delta[deltaKey] as number | null;
        const expected =
          baselineValue === null || treatmentValue === null
            ? null
            : treatmentValue - baselineValue;
        if (!sameNumber(actual, expected)) {
          throw new Error(
            `${profile}:${sample} ${deltaKey}가 B-A와 일치하지 않아요.`,
          );
        }
      }
    }
  }
}

// 결론 판정 로직은 없다: 지금 결과(B − A가 AUC 0.001 미만, 수익률은 오히려 낮음)에 맞춘 '의미 있는 개선 아님' 문장이다.
// 수치는 화면이 comparison_deltas에서 두 줄로 따로 읽는다.
const NO_MEANINGFUL_GAIN = "시장 분위기 지표를 더해도 거의 달라지지 않았어요.";

function validateExperiment(value: unknown): PerformanceExperiment {
  assertRecord(value, "experiment");
  for (const key of ["id", "run_id", "start", "end", "source", "limitations", "backtest_scope", "volatile_definition"]) {
    if (typeof value[key] !== "string" || !value[key].trim()) throw new Error(`experiment.${key}가 필요해요.`);
  }
  if (value.primary_metric !== "annual_mean_roc_auc" || value.aggregation !== "equal_weight_annual_mean") {
    throw new Error("실험 주지표와 집계 방식이 지원되는 계약과 달라요.");
  }
  if (!Array.isArray(value.years) || !value.years.length || new Set(value.years).size !== value.years.length) {
    throw new Error("평가 연도가 없거나 중복됐어요.");
  }
  value.years.forEach((year) => assertInteger(year, "experiment.years", 2000));
  for (const key of ["start", "end"]) {
    const day = value[key] as string;
    if (!/^\d{4}-\d{2}-\d{2}$/.test(day) || !Number.isFinite(Date.parse(day)) || new Date(day).toISOString().slice(0, 10) !== day) {
      throw new Error(`experiment.${key}의 날짜가 올바르지 않아요.`);
    }
  }
  if ((value.start as string) > (value.end as string)) throw new Error("평가 시작일이 종료일보다 늦어요.");
  assertInteger(value.initial_cash, "experiment.initial_cash", 1);
  for (const key of ["classification_threshold", "strategy_threshold"]) {
    assertFiniteNumber(value[key], `experiment.${key}`);
    assertRange(value[key], `experiment.${key}`, 0, 1);
  }
  return value as unknown as PerformanceExperiment;
}

function assertCompleteMetricPairs(rows: ComparisonMetricRow[], label: string): void {
  const expected = new Set(
    PROFILES.flatMap((profile) => VARIANTS.map((variant) => `${profile}:${variant}`)),
  );
  for (const row of rows) {
    const key = `${row.profile}:${row.variant}`;
    if (!expected.delete(key)) throw new Error(`${label}에 중복되거나 알 수 없는 런: ${key}`);
  }
  if (expected.size) throw new Error(`${label}에 누락된 런: ${[...expected].join(", ")}`);
}

function sortMetricRows(rows: ComparisonMetricRow[]): ComparisonMetricRow[] {
  return [...rows].sort(
    (left, right) =>
      PROFILES.indexOf(left.profile) - PROFILES.indexOf(right.profile) ||
      VARIANTS.indexOf(left.variant) - VARIANTS.indexOf(right.variant),
  );
}

function sortDeltaRows(rows: ComparisonDeltaRow[]): ComparisonDeltaRow[] {
  return [...rows].sort(
    (left, right) =>
      PROFILES.indexOf(left.profile) - PROFILES.indexOf(right.profile) ||
      SAMPLES.indexOf(left.sample) - SAMPLES.indexOf(right.sample),
  );
}

function findMetric(
  rows: ComparisonMetricRow[],
  profile: ComparisonProfile,
  variant: ComparisonVariant,
): ComparisonMetricRow {
  const row = rows.find(
    (candidate) => candidate.profile === profile && candidate.variant === variant,
  );
  if (!row) throw new Error(`실험 런을 찾지 못했습니다: ${profile}:${variant}`);
  return row;
}

function assertRecord(
  value: unknown,
  pathLabel: string,
): asserts value is Record<string, unknown> {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    throw new Error(`${pathLabel}는 객체여야 해요.`);
  }
}

function assertEnum<const T extends readonly string[]>(
  value: unknown,
  choices: T,
  pathLabel: string,
): asserts value is T[number] {
  if (typeof value !== "string" || !choices.includes(value)) {
    throw new Error(`${pathLabel} 값이 올바르지 않아요.`);
  }
}

function assertFiniteNumber(value: unknown, pathLabel: string): asserts value is number {
  if (typeof value !== "number" || !Number.isFinite(value)) {
    throw new Error(`${pathLabel}는 유한한 숫자여야 해요.`);
  }
}

function assertNullableFiniteNumber(
  value: unknown,
  pathLabel: string,
): asserts value is number | null {
  if (value !== null) assertFiniteNumber(value, pathLabel);
}

function assertInteger(value: unknown, pathLabel: string, minimum: number): void {
  if (!Number.isInteger(value) || (value as number) < minimum) {
    throw new Error(`${pathLabel}는 ${minimum} 이상의 정수여야 해요.`);
  }
}

function assertRange(
  value: unknown,
  pathLabel: string,
  min: number,
  max: number,
): asserts value is number {
  assertFiniteNumber(value, pathLabel);
  if (value < min || value > max) {
    throw new Error(`${pathLabel}는 ${min}~${max} 범위여야 해요.`);
  }
}

function sameNumber(actual: number | null, expected: number | null): boolean {
  if (actual === null || expected === null) return actual === expected;
  return Math.abs(actual - expected) <= 1e-8;
}

function isMissingFile(error: unknown): boolean {
  return (
    typeof error === "object" &&
    error !== null &&
    "code" in error &&
    (error as { code: unknown }).code === "ENOENT"
  );
}

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}
