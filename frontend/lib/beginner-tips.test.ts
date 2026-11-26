import assert from "node:assert/strict";
import { test } from "node:test";
import { BEGINNER_TIPS } from "./beginner-tips.ts";

// 금지 표현(매매 지시, 전망, 가운데 점 등)은 copy-rules.test.ts가 lib/ 전체를 훑으며 이 파일도 검사한다.

const DATE = /^\d{4}-\d{2}-\d{2}$/;

test("팁은 30개 이상이고 id가 겹치지 않는다", () => {
  assert.ok(BEGINNER_TIPS.length >= 30, `${BEGINNER_TIPS.length}개`);
  const ids = BEGINNER_TIPS.map((tip) => tip.id);
  assert.equal(new Set(ids).size, ids.length);
  for (const id of ids) assert.match(id, /^[a-z0-9]+(-[a-z0-9]+)*$/);
});

test("띠 한 줄은 36자 이하, 설명 문장은 '요.'로 끝난다", () => {
  for (const tip of BEGINNER_TIPS) {
    assert.ok([...tip.title].length <= 36, `${tip.id} 제목 ${[...tip.title].length}자`);
    assert.doesNotMatch(tip.title, /[.!?]$/, `${tip.id} 제목은 마침표 없이`);
    assert.match(tip.summary, /요\.$/, `${tip.id} summary`);
    assert.ok(tip.detail.length >= 2, `${tip.id} 자세히 보기는 두 문장 이상`);
    for (const line of tip.detail) assert.match(line, /요\.$/, `${tip.id} detail: ${line}`);
    if (tip.inService) assert.match(tip.inService, /요\.$/, `${tip.id} inService`);
  }
});

test("모든 팁에 출처가 있고, 계산식 말고는 주소가 있다", () => {
  for (const tip of BEGINNER_TIPS) {
    assert.ok(tip.sources.length > 0, `${tip.id} 출처 없음`);
    for (const source of tip.sources) {
      if (source.kind === "계산식") continue;
      assert.match(source.url ?? "", /^https:\/\//, `${tip.id} ${source.label}`);
    }
    // 계산식만 출처로 단 팁은 식을 화면에 보여 준다
    if (tip.sources.every((source) => source.kind === "계산식")) assert.ok(tip.formula, `${tip.id} 식 없음`);
    assert.match(tip.checkedAt, DATE);
    if (tip.reviewBy) {
      assert.match(tip.reviewBy, DATE);
      assert.ok(tip.reviewBy > tip.checkedAt, `${tip.id} reviewBy`);
    }
  }
});

test("계산 팁의 숫자가 식과 맞는다", () => {
  const recovery = (drop: number) => Math.round((1 / (1 - drop) - 1) * 1000) / 10;
  assert.equal(recovery(0.3), 42.9);
  assert.equal(recovery(0.1), 11.1);
  assert.equal(recovery(0.2), 25);
  assert.equal(recovery(0.5), 100);
  assert.equal(Math.round(1.1 * 0.9 * 100), 99);
  assert.equal(1.5 * 0.5, 0.75);
  assert.equal(2 * 0.5, 1); // +100% 뒤 -50%
  assert.equal((100_000 - 70_000), (170_000 - 140_000)); // 물타기 전후 손실 3만 원
  assert.equal(170_000 / 20, 8_500);
  assert.ok(Math.abs(1.06 ** 12 - 2.01) < 0.01);
  assert.equal(Math.round(1.6 * 0.4 * 100), 64); // 2배 레버리지 +30% 뒤 -30%
  assert.equal(Math.round(0.7 * 1.3 * 100), 91); // 1배는 -9%
  assert.equal((10_000_000 - 2_500_000) * 0.22, 1_650_000);
  assert.equal(Math.round(50 * 0.2), 10); // 1년 50번 매도면 원금의 약 10%
});

test("바뀌는 제도는 다시 볼 날짜가 있다", () => {
  const timeSensitive = ["transaction-tax", "settlement-t2", "leverage-decay", "margin-forced-sale", "overseas-stock-tax", "etf-tax-differs", "dividend-why", "market-warning"];
  for (const id of timeSensitive) {
    const tip = BEGINNER_TIPS.find((item) => item.id === id);
    assert.ok(tip?.reviewBy, id);
  }
});
