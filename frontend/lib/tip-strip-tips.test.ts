import assert from "node:assert/strict";
import { test } from "node:test";
import { TIP_STRIP_TIPS } from "./tip-strip-tips.ts";
import { nextKstMidnight } from "./tip-dismissal.ts";

test("팁 3개의 문장과 계산 예시가 같은 결과를 보여 준다", () => {
  const [recover30, upAndDown10, recover50] = TIP_STRIP_TIPS;
  assert.equal(TIP_STRIP_TIPS.length, 3);
  assert.equal(new Set(TIP_STRIP_TIPS.map(({ id }) => id)).size, 3);

  const recovery30 = ((30 / 70) * 100).toFixed(1);
  assert.equal(recover30.headline, `-30% 손실을 회복하려면 +${recovery30}%가 필요해요.`);
  assert.equal(recover30.source, `30 ÷ 70 × 100% ≈ ${recovery30}%`);
  assert.match(recover30.description, /70만 원이 남아요/);

  const remaining = (100 * 110 * 90) / 10_000;
  assert.equal(upAndDown10.headline, `10% 오른 뒤 10% 내리면, 처음보다 ${100 - remaining}% 낮아요.`);
  assert.equal(upAndDown10.source, `100 × 1.1 × 0.9 = ${remaining}`);
  assert.match(upAndDown10.description, /99만 원이 남아요/);

  const recovery50 = (50 / 50) * 100;
  assert.equal(recover50.headline, `50% 손실을 회복하려면 ${recovery50}% 상승이 필요해요.`);
  assert.equal(recover50.source, `50 ÷ 50 × 100% = ${recovery50}%`);
  assert.match(recover50.description, /두 배가 되어야 해요/);
});

test("팁 숨김은 서울 자정에 끝난다", () => {
  const midnight = Date.parse("2026-12-31T15:00:00.000Z");
  assert.equal(nextKstMidnight(midnight - 1), midnight);
  assert.equal(nextKstMidnight(midnight), Date.parse("2027-01-01T15:00:00.000Z"));
});
