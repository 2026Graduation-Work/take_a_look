import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import { validatePerformanceResults } from "./performance-data.ts";
import { METRICS, formatDeltaValue } from "./performance-display.ts";

const artifact = () => JSON.parse(readFileSync("artifacts/performance/comparison_results.json", "utf8"));
test("실제 성적표는 네 실행·동일 표본·B-A를 검증하고 급변 구간 미산출 값을 유지한다", () => {
  const data = validatePerformanceResults(artifact());
  assert.equal(data.experiment?.primary_metric, "annual_mean_roc_auc");
  assert.equal(data.four_run_metrics.length, 4);
  assert.ok(data.volatile_subsample_metrics.every((row) => row.sharpe === null && row.trade_count === null));
  const auc = METRICS.find((metric) => metric.key === "auc")!;
  assert.equal(formatDeltaValue(0.000336, auc), "+0.000336");
  const brokenDelta = artifact();
  brokenDelta.comparison_deltas[0].delta_B_minus_A_auc += 0.1;
  assert.throws(() => validatePerformanceResults(brokenDelta), /B-A/);
  const brokenSample = artifact();
  brokenSample.four_run_metrics[0].sample_rows += 1;
  assert.throws(() => validatePerformanceResults(brokenSample), /공통 표본/);
  const brokenDate = artifact();
  brokenDate.experiment.end = "2025-02-31";
  assert.throws(() => validatePerformanceResults(brokenDate), /날짜/);
});


test("작은 Brier·ECE 차이의 부호와 크기를 숨기지 않는다", () => {
  for (const key of ["calibration_brier", "calibration_ece"]) {
    const metric = METRICS.find((item) => item.key === key)!;
    assert.equal(formatDeltaValue(-0.000123, metric), "-0.000123");
    assert.equal(formatDeltaValue(0.000123, metric), "+0.000123");
  }
});
