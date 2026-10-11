import { readFile } from "node:fs/promises";
import path from "node:path";
import { performanceResults } from "./mock-performance";
import type {
  ComparisonDeltaRow,
  ComparisonMetricRow,
  ComparisonProfile,
  ComparisonResults,
  ComparisonSample,
  ComparisonVariant,
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
  "sharpe",
  "mdd",
  "cumulative_return",
] as const;
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
  "현재 수치는 화면 구조 검증용 샘플입니다. 실제 비교 실험 결과가 들어오기 전에는 A/B 성능 차이에 대한 연구 결론으로 사용하지 않습니다.";

export async function loadPerformanceData(): Promise<PerformanceDataBundle> {
  const configuredFile = process.env.PERFORMANCE_RESULTS_FILE?.trim();
  if (configuredFile && path.basename(configuredFile) !== configuredFile) {
    throw new Error(
      "PERFORMANCE_RESULTS_FILE은 artifacts/performance 아래의 파일명만 지정할 수 있습니다.",
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
    conclusion: buildExperimentConclusion(data),
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
  if (!Array.isArray(value)) throw new Error(`${label}는 배열이어야 합니다.`);
  if (value.length !== 4) throw new Error(`${label}는 정확히 4런이어야 합니다.`);

  const rows = value.map((candidate, index) => {
    const rowPath = `${label}[${index}]`;
    assertRecord(candidate, rowPath);
    assertEnum(candidate.profile, PROFILES, `${rowPath}.profile`);
    assertEnum(candidate.variant, VARIANTS, `${rowPath}.variant`);
    assertEnum(candidate.sample, SAMPLES, `${rowPath}.sample`);
    if (candidate.sample !== expectedSample) {
      throw new Error(`${rowPath}.sample은 ${expectedSample}이어야 합니다.`);
    }
    const expectedFeatureSet = candidate.variant === "A" ? "baseline" : "treatment";
    if (candidate.feature_set !== expectedFeatureSet) {
      throw new Error(
        `${rowPath}.feature_set은 ${candidate.variant} 런에서 ${expectedFeatureSet}이어야 합니다.`,
      );
    }

    assertInteger(candidate.feature_count, `${rowPath}.feature_count`, 1);
    assertInteger(candidate.sample_rows, `${rowPath}.sample_rows`, 1);
    assertInteger(candidate.sample_dates, `${rowPath}.sample_dates`, 1);
    assertInteger(candidate.trade_count, `${rowPath}.trade_count`, 0);
    assertNullableFiniteNumber(candidate.auc, `${rowPath}.auc`);
    for (const field of METRIC_NUMBER_FIELDS) {
      assertFiniteNumber(candidate[field], `${rowPath}.${field}`);
    }
    for (const field of [
      "positive_rate",
      "hit_rate",
      "calibration_brier",
      "calibration_ece",
    ] as const) {
      assertRange(candidate[field], `${rowPath}.${field}`, 0, 1);
    }
    if (candidate.auc !== null) assertRange(candidate.auc, `${rowPath}.auc`, 0, 1);
    assertRange(candidate.mdd, `${rowPath}.mdd`, -1, 0);
    return candidate as unknown as ComparisonMetricRow;
  });

  assertCompleteMetricPairs(rows, label);
  return rows;
}

function validateDeltaRows(value: unknown): ComparisonDeltaRow[] {
  const label = "comparison_deltas";
  if (!Array.isArray(value)) throw new Error(`${label}는 배열이어야 합니다.`);
  if (value.length !== 4) throw new Error(`${label}는 정확히 4행이어야 합니다.`);

  const rows = value.map((candidate, index) => {
    const rowPath = `${label}[${index}]`;
    assertRecord(candidate, rowPath);
    assertEnum(candidate.profile, PROFILES, `${rowPath}.profile`);
    assertEnum(candidate.sample, SAMPLES, `${rowPath}.sample`);
    for (const [, deltaKey] of DELTA_METRIC_MAP) {
      if (deltaKey === "delta_B_minus_A_auc") {
        assertNullableFiniteNumber(candidate[deltaKey], `${rowPath}.${deltaKey}`);
      } else {
        assertFiniteNumber(candidate[deltaKey], `${rowPath}.${deltaKey}`);
      }
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
            `${profile}:${sample} ${deltaKey}가 B-A와 일치하지 않습니다.`,
          );
        }
      }
    }
  }
}

function buildExperimentConclusion(data: ComparisonResults): string {
  const allStable = findDelta(data, "stable", "all");
  const allAggressive = findDelta(data, "aggressive", "all");
  const volatileStable = findDelta(data, "stable", "volatile_top_20pct");
  const volatileAggressive = findDelta(data, "aggressive", "volatile_top_20pct");

  return `1차 지표 Sharpe의 B-A 차이는 전체 구간에서 안정형 ${signedDecimal(allStable.delta_B_minus_A_sharpe)}, 공격형 ${signedDecimal(allAggressive.delta_B_minus_A_sharpe)}, 급변 구간에서 안정형 ${signedDecimal(volatileStable.delta_B_minus_A_sharpe)}, 공격형 ${signedDecimal(volatileAggressive.delta_B_minus_A_sharpe)}였습니다. MDD 차이(양수=낙폭 완화)는 급변 구간에서 각각 ${signedPercentPoint(volatileStable.delta_B_minus_A_mdd)}, ${signedPercentPoint(volatileAggressive.delta_B_minus_A_mdd)}였습니다. 이는 관측 차이의 기술적 요약이며 통계적 유의성을 의미하지 않습니다.`;
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

function findDelta(
  data: ComparisonResults,
  profile: ComparisonProfile,
  sample: ComparisonSample,
): ComparisonDeltaRow {
  const row = data.comparison_deltas.find(
    (candidate) => candidate.profile === profile && candidate.sample === sample,
  );
  if (!row) throw new Error(`델타 행을 찾지 못했습니다: ${profile}:${sample}`);
  return row;
}

function assertRecord(
  value: unknown,
  pathLabel: string,
): asserts value is Record<string, unknown> {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    throw new Error(`${pathLabel}는 객체여야 합니다.`);
  }
}

function assertEnum<const T extends readonly string[]>(
  value: unknown,
  choices: T,
  pathLabel: string,
): asserts value is T[number] {
  if (typeof value !== "string" || !choices.includes(value)) {
    throw new Error(`${pathLabel} 값이 올바르지 않습니다.`);
  }
}

function assertFiniteNumber(value: unknown, pathLabel: string): asserts value is number {
  if (typeof value !== "number" || !Number.isFinite(value)) {
    throw new Error(`${pathLabel}는 유한한 숫자여야 합니다.`);
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
    throw new Error(`${pathLabel}는 ${minimum} 이상의 정수여야 합니다.`);
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
    throw new Error(`${pathLabel}는 ${min}~${max} 범위여야 합니다.`);
  }
}

function sameNumber(actual: number | null, expected: number | null): boolean {
  if (actual === null || expected === null) return actual === expected;
  return Math.abs(actual - expected) <= 1e-8;
}

function signedDecimal(value: number): string {
  return `${value > 0 ? "+" : ""}${value.toFixed(2)}`;
}

function signedPercentPoint(value: number): string {
  return `${value > 0 ? "+" : ""}${(value * 100).toFixed(1)}%p`;
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
