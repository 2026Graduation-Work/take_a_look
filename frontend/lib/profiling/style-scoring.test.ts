import assert from "node:assert/strict";
import { test } from "node:test";
import golden from "./style-golden-cases.json" with { type: "json" };
import { classifyBit } from "./bit.ts";
import {
  answersFromPattern,
  confidencePerAxis,
  detectContradictions,
  questionsForMode,
  reduceToLegacyFields,
  scoreStyleAxes,
  scoreWithQuestions,
  type AssessmentMode,
  type StyleAnswers,
  type StyleQuestion,
} from "./style-scoring.ts";
import type { StyleAxes } from "../types.ts";

const close = (actual: number, expected: number, label: string) =>
  assert.ok(Math.abs(actual - expected) < 1e-9, `${label}: ${actual} ≠ ${expected}`);

for (const goldenCase of golden.cases) {
  test(`골든 ${goldenCase.id}: ${goldenCase.intent}`, () => {
    const mode = goldenCase.mode as AssessmentMode;
    const expected = goldenCase.expected;
    const styleAxes = scoreStyleAxes(goldenCase.answers as unknown as StyleAnswers, mode);

    assert.equal(styleAxes.assessment_mode, expected.style_axes.assessment_mode);
    styleAxes.axes.forEach((axis, index) => {
      const want = expected.style_axes.axes[index];
      assert.equal(axis.axis_id, want.axis_id);
      close(axis.ratio, want.ratio, `${axis.axis_id}.ratio`);
      close(axis.confidence, want.confidence, `${axis.axis_id}.confidence`);
      assert.equal(axis.answered_count, want.answered_count, `${axis.axis_id}.answered_count`);
      assert.equal(axis.question_count, want.question_count, `${axis.axis_id}.question_count`);
    });
    assert.deepEqual(detectContradictions(styleAxes), expected.contradictions);

    const legacy = reduceToLegacyFields(styleAxes);
    for (const [field, value] of Object.entries(expected.legacy)) {
      close(legacy[field as keyof typeof legacy], value, field);
    }
    for (const [field, value] of Object.entries(confidencePerAxis(styleAxes))) {
      close(value, expected.confidence_per_axis[field as keyof typeof expected.confidence_per_axis], field);
    }
  });
}

test("골든 케이스가 BIT 4구간을 모두 덮는다", () => {
  const types = new Set(
    golden.cases.map(({ expected }) => classifyBit(expected.style_axes as StyleAxes).type),
  );
  assert.deepEqual([...types].sort(), ["ACCUMULATOR", "FOLLOWER", "INDEPENDENT", "PRESERVER"]);
});

test("빠른 진단은 24문항, 축당 3문항이고 축마다 역채점 문항이 있다", () => {
  const quick = questionsForMode("quick");
  assert.equal(quick.length, 24);
  assert.equal(questionsForMode("detailed").length, 40);
  const byAxis = Map.groupBy(quick, (question) => (question.type === "likert" ? question.axis : ""));
  for (const [axis, questions] of byAxis) {
    assert.equal(questions.length, 3, axis);
    assert.ok(questions.some((question) => question.type === "likert" && question.direction === -1), axis);
  }
});

test("패턴 조립 → 채점하면 패턴의 축 방향이 그대로 나온다(역채점 문항 포함)", () => {
  const pattern = {
    market_participation: -1,
    loss_tolerance: 2,
    turnover: -2,
    concentration: 1,
    rule_adherence: 0,
    information_reliance: -2,
    urgency: 1,
    drawdown_reaction: 2,
  } as const;
  const styleAxes = scoreStyleAxes(answersFromPattern(pattern, "quick"), "quick");
  for (const axis of styleAxes.axes) {
    close(axis.ratio, pattern[axis.axis_id] / 2, axis.axis_id);
  }
});

test("시나리오형 문항: 고른 선택지의 축 점수가 해당 축에 들어가고, 적지 않은 축은 0으로 센다", () => {
  const scenario: StyleQuestion = {
    id: "sc01",
    type: "scenario",
    weight: 1,
    quick: true,
    text: "보유 종목이 한 주 만에 15% 떨어졌습니다.",
    options: [
      { id: "sell", label: "정리한다", scores: { drawdown_reaction: 2, loss_tolerance: -1 } },
      { id: "hold", label: "계획대로 둔다", scores: { drawdown_reaction: -1 } },
    ],
  };
  const score = (answers: StyleAnswers) => scoreWithQuestions(answers, "quick", [scenario]);
  const axis = (styleAxes: StyleAxes, id: string) => styleAxes.axes.find(({ axis_id }) => axis_id === id)!;

  const held = score({ sc01: "hold" });
  close(axis(held, "drawdown_reaction").ratio, -0.5, "drawdown_reaction");
  close(axis(held, "loss_tolerance").ratio, 0, "loss_tolerance");
  assert.equal(axis(held, "loss_tolerance").answered_count, 1);
  assert.equal(axis(held, "turnover").question_count, 0);
  close(axis(score({ sc01: "sell" }), "loss_tolerance").ratio, -0.5, "sell.loss_tolerance");
  assert.throws(() => score({ sc01: "unknown" }), /선택지에 없어요/);
});

test("모드에 없는 문항 응답과 범위 밖 리커트 값은 거부한다", () => {
  assert.throws(() => scoreStyleAxes({ mp04: 3 }, "quick"), /이 모드에 없는 문항/);
  assert.throws(() => scoreStyleAxes({ mp01: 6 }, "quick"), /1~5/);
});

test("모순 규칙마다 조건을 만족하면 검출되고, 신뢰도가 낮은 축으로는 주장하지 않는다", () => {
  const cases: Record<string, Partial<Record<string, number>>> = {
    loss_averse_but_concentrated: { loss_tolerance: -0.5, concentration: 0.5 },
    long_horizon_but_reactive: { turnover: -0.5, urgency: 0.5, drawdown_reaction: 0.5 },
    discretionary_but_loss_averse: { rule_adherence: 0.5, loss_tolerance: -0.5 },
    herding_but_concentrated: { information_reliance: 0.5, concentration: 0.5 },
    benchmark_focused_but_short_horizon: { market_participation: -0.5, turnover: 0.5 },
  };
  const axesWith = (ratios: Partial<Record<string, number>>, confidence: number): StyleAxes => ({
    assessment_mode: "quick",
    axes: scoreStyleAxes({}, "quick").axes.map((axis) => ({
      ...axis,
      ratio: ratios[axis.axis_id] ?? 0,
      confidence,
    })),
  });
  for (const [id, ratios] of Object.entries(cases)) {
    assert.ok(detectContradictions(axesWith(ratios, 1)).some((found) => found.id === id), id);
    assert.deepEqual(detectContradictions(axesWith(ratios, 0.29)), [], `${id} 저신뢰`);
  }
});

test("짧은 진단은 16문항, 축당 정방향 1 + 역방향 1이고 모두 빠른 진단 문항이다", () => {
  const short = questionsForMode("short");
  assert.equal(short.length, 16);
  const quickIds = new Set(questionsForMode("quick").map(({ id }) => id));
  assert.ok(short.every(({ id }) => quickIds.has(id)));
  for (const [axis, questions] of Map.groupBy(short, (q) => (q.type === "likert" ? q.axis : ""))) {
    assert.deepEqual(
      questions.map((q) => (q.type === "likert" ? q.direction : 0)).sort(),
      [-1, 1],
      axis,
    );
  }
});

// 속성 테스트: 한결같이 답한 페르소나(모든 문항을 축 방향 강도대로 답함)는 16문항과 24문항에서
// 같은 유형으로 분류된다. 분류 3축의 강도 조합 전부와 나머지 축의 여러 값으로 확인한다.
test("짧은 진단: 일관되게 답한 페르소나는 빠른 진단과 같은 유형이 나온다", () => {
  const levels = [-2, -1, 0, 1, 2];
  let checked = 0;
  for (const turnover of levels)
    for (const loss of levels)
      for (const concentration of levels)
        for (const rest of [-2, 0, 1]) {
          const pattern = {
            market_participation: rest,
            loss_tolerance: loss,
            turnover,
            concentration,
            rule_adherence: -rest,
            information_reliance: rest,
            urgency: rest,
            drawdown_reaction: -rest,
          };
          const short = scoreStyleAxes(answersFromPattern(pattern, "short"), "short");
          const quick = scoreStyleAxes(answersFromPattern(pattern, "quick"), "quick");
          assert.equal(short.assessment_mode, "quick"); // 스키마 enum(freeze)을 지킨다
          assert.equal(classifyBit(short).type, classifyBit(quick).type, JSON.stringify(pattern));
          assert.ok(short.axes.every(({ question_count }) => question_count === 2));
          checked += 1;
        }
  assert.equal(checked, 375);
});
