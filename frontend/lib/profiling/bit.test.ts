// node --test "lib/**/*.test.ts" (Node 24 타입 스트리핑, 추가 의존성 없음)
import assert from "node:assert/strict";
import { test } from "node:test";
import type { StyleAxes, StyleAxisId } from "../types.ts";
import { investorStyleAxes } from "../mock-data.ts";
import { BIAS_PROFILE_AXES, CARD_ORDER, classifyBit, type BitType } from "./bit.ts";
import {
  NUDGES,
  SCREEN_GUIDE_NOTICE,
  selectNudges,
  type NudgeMarket,
} from "./nudges.ts";

const AXIS_IDS: StyleAxisId[] = [
  "market_participation",
  "loss_tolerance",
  "turnover",
  "concentration",
  "rule_adherence",
  "information_reliance",
  "urgency",
  "drawdown_reaction",
];

function axes(ratios: Partial<Record<StyleAxisId, number>>, confidence = 0.9): StyleAxes {
  return {
    assessment_mode: "quick",
    axes: AXIS_IDS.map((axis_id) => ({
      axis_id,
      ratio: ratios[axis_id] ?? 0,
      confidence,
      answered_count: 3,
      question_count: 3,
    })),
  };
}

// 분류 3축을 같은 값으로 두면 composite도 그 값이다.
const spectrum = (value: number) =>
  axes({ turnover: value, loss_tolerance: value, concentration: value });

const CALM: NudgeMarket = {
  retailNetBuyStreakDays: 0,
  retailNetLatest: 0,
  foreignNetLatest: 0,
  institutionNetBuyDaysOf5: 0,
  volatilityPercentile: 0.5,
  drawdownFrom3mHigh: -0.02,
  return3d: 0,
  sentimentChange: 0,
  sentimentDayLabel: "오늘",
  isTopHolding: false,
  riskGrade: 3,
};

// 모든 시장 조건이 참인 시장. 성향 조건만으로 발화가 갈린다.
const ALL_MARKET: NudgeMarket = {
  retailNetBuyStreakDays: 5,
  retailNetLatest: 1,
  foreignNetLatest: -1,
  institutionNetBuyDaysOf5: 4,
  volatilityPercentile: 0.95,
  drawdownFrom3mHigh: -0.2,
  return3d: 0.12,
  sentimentChange: 2, // 감성 점수 폭(-1~1)의 최대 변화. N07 임계 산출값과 무관하게 참
  sentimentDayLabel: "오늘",
  isTopHolding: true,
  riskGrade: 2,
};

const ids = (bit: StyleAxes, market: Partial<NudgeMarket> = {}, limit?: number) =>
  selectNudges(classifyBit(bit), { ...CALM, ...market }, limit).map(({ id }) => id);

const TYPE_CASES: [number, BitType, "emotional" | "cognitive"][] = [
  [-0.8, "PRESERVER", "emotional"],
  [-0.3, "FOLLOWER", "cognitive"],
  [0.2, "INDEPENDENT", "cognitive"],
  [0.8, "ACCUMULATOR", "emotional"],
];

for (const [composite, type, biasMode] of TYPE_CASES) {
  test(`${type}: composite ${composite} → ${biasMode}, 유형별 카드 순서`, () => {
    const result = classifyBit(spectrum(composite));
    assert.equal(result.type, type);
    assert.equal(result.biasMode, biasMode);
    assert.deepEqual(result.cardOrder, CARD_ORDER[type]);
    assert.equal(result.cardOrder[0], "nudge");
    assert.equal(new Set(result.cardOrder).size, 6);
  });
}

test("구간 경계값은 위 구간에 속한다", () => {
  assert.equal(classifyBit(spectrum(-0.51)).type, "PRESERVER");
  assert.equal(classifyBit(spectrum(-0.5)).type, "FOLLOWER");
  assert.equal(classifyBit(spectrum(0)).type, "INDEPENDENT");
  assert.equal(classifyBit(spectrum(0.5)).type, "ACCUMULATOR");
});

test("김민지: FOLLOWER, 신뢰도는 분류 3축 confidence 평균", () => {
  const result = classifyBit(investorStyleAxes);
  assert.equal(result.type, "FOLLOWER");
  assert.ok(Math.abs(result.composite - -0.3) < 1e-9);
  assert.ok(Math.abs(result.confidence - (0.95 + 0.92 + 0.81) / 3) < 1e-9);
  assert.equal(result.lowConfidence, false);
});

test("market_participation은 분류에 쓰지 않고 편향 프로필로 간다", () => {
  const low = classifyBit(axes({ market_participation: -1 }));
  const high = classifyBit(axes({ market_participation: 1 }));
  assert.equal(low.type, high.type);
  assert.equal(low.composite, high.composite);
  assert.deepEqual(
    high.biasProfile.map(({ axisId }) => axisId),
    BIAS_PROFILE_AXES,
  );
});

test("confidence 0.5 미만이면 유형과 함께 lowConfidence", () => {
  const result = classifyBit(axes({}, 0.4));
  assert.equal(result.type, "INDEPENDENT");
  assert.equal(result.lowConfidence, true);
});

test("넛지 11종(N12는 화면 안내로 분리), id 중복 없음, 권유 표현 없음", () => {
  const nudgeIds = NUDGES.map(({ id }) => id);
  assert.equal(new Set(nudgeIds).size, 11);
  assert.ok(!(nudgeIds as string[]).includes("N12"));
  for (const text of [...NUDGES.map((rule) => (typeof rule.text === "function" ? rule.text(ALL_MARKET) : rule.text)), SCREEN_GUIDE_NOTICE.text]) {
    assert.doesNotMatch(text, /사세요|파세요|매수하|매도하|권장|추천/);
  }
});

test("화면 안내(기존 N12)는 PRESERVER·FOLLOWER에만", () => {
  assert.deepEqual(SCREEN_GUIDE_NOTICE.appliesTo, ["PRESERVER", "FOLLOWER"]);
});

test("임계는 경계 포함: >= +0.3, <= -0.3", () => {
  const hot = { volatilityPercentile: 0.95 };
  assert.deepEqual(ids(axes({ drawdown_reaction: 0.3 }), hot), ["N04"]);
  assert.deepEqual(ids(axes({ drawdown_reaction: 0.29 }), hot), []);
  assert.ok(ids(axes({ loss_tolerance: -0.3 }), { riskGrade: 2 }).includes("N11"));
  assert.ok(!ids(axes({ loss_tolerance: -0.29 }), { riskGrade: 2 }).includes("N11"));
});

test("N04·N05는 drawdown_reaction + 쪽(하락 시 이탈)에서만", () => {
  assert.deepEqual(ids(axes({ drawdown_reaction: 0.5 }), { volatilityPercentile: 0.95 }), ["N04"]);
  assert.deepEqual(ids(axes({ drawdown_reaction: 0.5 }), { drawdownFrom3mHigh: -0.2 }), ["N05"]);
  assert.deepEqual(
    ids(axes({ drawdown_reaction: -0.5 }), { volatilityPercentile: 0.95, drawdownFrom3mHigh: -0.2 }),
    [],
  );
});

test("같은 축 근거 넛지는 우선순위가 높은 하나만 남는다", () => {
  const hot = { volatilityPercentile: 0.95, drawdownFrom3mHigh: -0.2 };
  // N05·N04는 둘 다 drawdown_reaction. 우선순위 N05 > N04
  assert.deepEqual(ids(axes({ drawdown_reaction: 0.5 }), hot, Infinity), ["N05"]);
  // 축이 다르면 둘 다 남는다
  assert.deepEqual(
    ids(axes({ drawdown_reaction: 0.5, urgency: 0.5 }), { ...hot, return3d: 0.12 }),
    ["N05", "N06"],
  );
});

test("N10은 rule_adherence + 쪽(상황별 재량)에서만", () => {
  assert.deepEqual(ids(axes({ rule_adherence: 0.5 })), ["N10"]);
  assert.deepEqual(ids(axes({ rule_adherence: -0.5 })), []);
});

test("N11은 위험 등급 2 이하(위험 쪽)에서만", () => {
  const averse = axes({ loss_tolerance: -0.5 });
  assert.deepEqual(ids(averse, { riskGrade: 2 }), ["N11"]);
  assert.deepEqual(ids(averse, { riskGrade: 4 }), []);
});

test("N01~N03은 information_reliance >= 0.3 단독 조건. FOLLOWER여도 낮으면 발화 안 함", () => {
  const supplyMarket = {
    retailNetBuyStreakDays: 5,
    retailNetLatest: 1,
    foreignNetLatest: -1,
    institutionNetBuyDaysOf5: 4,
  };
  // 김민지 FOLLOWER, information_reliance +0.16
  assert.deepEqual(ids(investorStyleAxes, supplyMarket, Infinity), []);

  const herding = axes({ information_reliance: 0.3 });
  assert.deepEqual(ids(herding, { retailNetBuyStreakDays: 5 }), ["N01"]);
  assert.deepEqual(ids(herding, { retailNetLatest: 1, foreignNetLatest: -1 }), ["N02"]);
  assert.deepEqual(ids(herding, { institutionNetBuyDaysOf5: 4 }), ["N03"]);
  // 셋 다 참이어도 같은 축이라 우선순위가 가장 높은 N02만 남는다
  const fired = selectNudges(classifyBit(herding), { ...CALM, ...supplyMarket }, Infinity);
  assert.deepEqual(
    fired.map(({ id, axis, ratio }) => [id, axis, ratio]),
    [["N02", "information_reliance", 0.3]],
  );
});

test("김민지 고정: 모든 시장 조건이 참일 때 성향상 발화 가능한 넛지(축당 1개)", () => {
  // drawdown_reaction +0.30(N05 > N04), loss_tolerance -0.30(N11), urgency +0.44(N06 > N07)
  const fired = selectNudges(classifyBit(investorStyleAxes), ALL_MARKET, Infinity);
  assert.deepEqual(fired.map(({ id }) => id), ["N05", "N11", "N06"]);
  assert.deepEqual(
    selectNudges(classifyBit(investorStyleAxes), ALL_MARKET).map(({ id }) => id),
    ["N05", "N11"],
  );
});

test("최대 2개, 우선순위 N02 > N05 > N11 > N04 > N01 > id 순, 같은 축 중복 제외", () => {
  const everything = axes({
    information_reliance: 0.5,
    drawdown_reaction: 0.5,
    loss_tolerance: -0.5,
    urgency: 0.5,
    rule_adherence: 0.5,
  });
  const market: Partial<NudgeMarket> = { ...ALL_MARKET, isTopHolding: false };
  assert.deepEqual(ids(everything, market), ["N02", "N05"]);
  assert.deepEqual(ids(everything, { ...market, foreignNetLatest: 1 }), ["N05", "N11"]);
  assert.deepEqual(
    ids(everything, { ...market, foreignNetLatest: 1, drawdownFrom3mHigh: -0.05 }),
    ["N11", "N04"],
  );
  assert.deepEqual(
    ids(everything, { ...market, foreignNetLatest: 1, drawdownFrom3mHigh: -0.05, riskGrade: 3 }),
    ["N04", "N01"],
  );
  assert.deepEqual(
    ids(everything, {
      ...market,
      foreignNetLatest: 1,
      drawdownFrom3mHigh: -0.05,
      riskGrade: 3,
      volatilityPercentile: 0.5,
    }),
    // N03·N07은 각각 N01·N06과 같은 축이라 빠진다
    ["N01", "N06"],
  );
});

test("다른 성향으로 보기: 프리셋은 해당 유형으로 분류되고 분류 외 축은 그대로 둔다", async () => {
  const { BIT_TYPES, presetStyleAxes } = await import("./bit.ts");
  for (const type of BIT_TYPES) {
    const preset = presetStyleAxes(investorStyleAxes, type);
    const result = classifyBit(preset);
    assert.equal(result.type, type);
    assert.equal(result.lowConfidence, false);
    for (const axisId of BIAS_PROFILE_AXES) {
      assert.equal(result.ratios[axisId], classifyBit(investorStyleAxes).ratios[axisId]);
    }
  }
});
