import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import path from "node:path";
import { test } from "node:test";
import { investorProfile, investorStyleAxes } from "./mock-data.ts";
import {
  convertSurveyAnswers,
  summaryFromProfilingOutput,
  threeAxisSummary,
} from "./profiling-rules.ts";
import { answersFromPattern } from "./profiling/style-scoring.ts";

const SCHEMA = JSON.parse(
  readFileSync(path.resolve(import.meta.dirname, "../../schema/profiling_output.schema.json"), "utf8"),
);

const INPUT = {
  user_id: "u_test",
  session_id: "s_test",
  timestamp: "2026-09-19T12:00:00+09:00",
  style: answersFromPattern({ loss_tolerance: -1, turnover: -1, urgency: 1, drawdown_reaction: 1 }, "quick"),
  experience: "6m_2y",
  avoided_assets: ["spac", "spac", "managed_stock"],
  free_text: "남들 다 버는데 뒤처지는 것 같아요",
};

// schema의 required를 재귀로 따라가며 빠진 키를 모은다.
function missingRequired(schema: Record<string, unknown>, value: unknown, at = "$"): string[] {
  if (!value || typeof value !== "object" || Array.isArray(value)) return [];
  const record = value as Record<string, unknown>;
  const required = (schema.required as string[] | undefined) ?? [];
  const properties = (schema.properties as Record<string, Record<string, unknown>> | undefined) ?? {};
  return [
    ...required.filter((key) => !(key in record)).map((key) => `${at}.${key}`),
    ...Object.entries(properties).flatMap(([key, child]) => missingRequired(child, record[key], `${at}.${key}`)),
  ];
}

test("설문 응답 → schema v1.1 출력: 필수 필드를 모두 채우고 8축·모순을 싣는다", () => {
  const output = convertSurveyAnswers(INPUT);
  assert.deepEqual(missingRequired(SCHEMA, output), []);
  assert.equal(output.meta.schema_version, "1.1.0");
  assert.equal(output.style_axes?.axes.length, 8);
  assert.ok(Array.isArray(output.contradictions));
  assert.deepEqual(output.constraints.avoided_assets, ["spac", "managed_stock"]);
  assert.equal(output.investor_profile.investment_experience_years, 1);
  // v1.0 축약: risk_tolerance = (loss_tolerance + 1) / 2 = 0.25 → stable
  assert.equal(output.investor_profile.risk_tolerance, 0.25);
  assert.equal(output.investor_profile.profile_type, "stable");
  assert.equal(output.investor_profile.time_horizon_days, 1800);
  assert.equal(output.investor_profile.time_horizon_months, 60);
  assert.deepEqual(output.free_text_signal.extracted_signals, { fomo_index: 0.8 });
});

test("결과 확인 단계의 조정값이 축 ratio와 v1.0 필드에 반영되고, 신뢰도는 채점값 그대로다", () => {
  const scored = convertSurveyAnswers(INPUT);
  const adjusted = convertSurveyAnswers({ ...INPUT, adjusted_axes: { loss_tolerance: 0.6 } });
  const axis = (output: typeof scored) =>
    output.style_axes!.axes.find(({ axis_id }) => axis_id === "loss_tolerance")!;
  assert.equal(axis(adjusted).ratio, 0.6);
  assert.equal(axis(adjusted).confidence, axis(scored).confidence);
  assert.equal(adjusted.investor_profile.risk_tolerance, 0.8);
  assert.equal(adjusted.investor_profile.profile_type, "aggressive");
  assert.throws(() => convertSurveyAnswers({ ...INPUT, adjusted_axes: { loss_tolerance: 2 } }), /adjusted_axes/);
  assert.throws(() => convertSurveyAnswers({ ...INPUT, adjusted_axes: { unknown_axis: 0 } }), /adjusted_axes/);
});

test("성향 카드 3축은 8축 묶음 요약이고, 유형명은 BIT만 쓴다", () => {
  // 김민지: loss -0.3, concentration -0.4 → -0.35 → 33 / urgency 0.44, drawdown 0.3, info 0.16 → 0.3 → 65
  const { ratios, ...scores } = threeAxisSummary(investorStyleAxes);
  assert.deepEqual(scores, { riskTaking: 33, sensitivity: 65, horizonScore: 38, horizon: "mid" });
  // 화면 5칸 막대는 반올림 전 −1~1 값을 쓴다(점수 60에 걸친 0.205가 가운데 칸으로 내려가지 않게)
  assert.ok(Math.abs(ratios.riskTaking + 0.35) < 1e-9 && Math.abs(ratios.sensitivity - 0.3) < 1e-9 && ratios.horizon === -0.25);
  assert.equal(investorProfile.profileTypeLabel, "추종형");
  assert.equal(investorProfile.riskTolerance, 33);

  const output = convertSurveyAnswers(INPUT);
  const summary = summaryFromProfilingOutput(output, { displayName: "테스트", avatarLabel: "테" });
  const three = threeAxisSummary(output.style_axes!);
  assert.equal(summary.riskTolerance, three.riskTaking);
  assert.equal(summary.sentimentSensitivity, three.sensitivity);
  assert.doesNotMatch(summary.profileTypeLabel, /안정|수익추구|공격/);
});

test("필수 응답이 빠지면 거부한다", () => {
  assert.throws(() => convertSurveyAnswers({ ...INPUT, experience: "forever" }), /투자 경험/);
  assert.throws(() => convertSurveyAnswers({ ...INPUT, style: undefined }), /style/);
  assert.throws(() => convertSurveyAnswers({ ...INPUT, avoided_assets: ["crypto"] }), /제외할 종목 유형/);
});
