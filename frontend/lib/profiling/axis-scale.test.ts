import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import { PSYCHOLOGY_SCALE, STYLE_AXIS_SCALE, SUMMARY_SCALE, stageIndex, stageOf, stageWord, storedForStage } from "./axis-scale.ts";

test("단계 구간: −1~−0.6 / −0.6~−0.2 / −0.2~0.2 / 0.2~0.6 / 0.6~1, 경계는 가운데 쪽 칸", () => {
  const cases: [number, number][] = [
    [-1, 0], [-0.61, 0], [-0.6, 1], [-0.21, 1], [-0.2, 2], [0, 2], [0.2, 2], [0.21, 3], [0.6, 3], [0.61, 4], [1, 4],
  ];
  for (const [value, stage] of cases) assert.equal(stageIndex(value), stage, `${value}`);
});

test("극 방향: 오른쪽은 축 이름의 '더' 쪽, 화면만 뒤집고 저장 값은 그대로", () => {
  const { turnover, rule_adherence, loss_tolerance } = STYLE_AXIS_SCALE;
  // 저장 +1 = 단기 매매(style-questions.json) → 보유 기간 막대에서는 왼쪽(짧게)
  assert.equal(turnover.right, "길게");
  assert.equal(stageOf(turnover, 1), 0);
  assert.equal(stageWord(turnover, stageOf(turnover, 1)), "아주 단기 매매");
  assert.equal(stageWord(turnover, stageOf(turnover, -0.5)), "장기 보유");
  assert.equal(stageOf(rule_adherence, 1), 0);
  // 저장 +1 = 손실 감수 쪽 → 오른쪽, 극 이름은 결과가 아니라 행동
  assert.equal(stageOf(loss_tolerance, 1), 4);
  assert.doesNotMatch(loss_tolerance.right + loss_tolerance.rightSide, /수익/);
  assert.equal(SUMMARY_SCALE.horizon.flip, true);
  assert.equal(stageWord(PSYCHOLOGY_SCALE, stageIndex(-0.87)), "많이 움츠러듦");
});

test("칸을 고르면 그 칸의 가운데 값을 저장하고 다시 같은 칸으로 읽힌다", () => {
  for (const axis of Object.values(STYLE_AXIS_SCALE)) {
    for (let stage = 0; stage < 5; stage += 1) {
      const stored = storedForStage(axis, stage);
      assert.ok([-1, -0.5, 0, 0.5, 1].includes(stored));
      assert.equal(stageOf(axis, stored), stage);
    }
  }
});

test("8축 정의가 문항 정본의 축과 같다", () => {
  const bank = JSON.parse(readFileSync(new URL("./style-questions.json", import.meta.url), "utf8"));
  assert.deepEqual(Object.keys(STYLE_AXIS_SCALE).sort(), bank.axes.map((axis: { id: string }) => axis.id).sort());
});
