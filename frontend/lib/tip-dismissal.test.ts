import assert from "node:assert/strict";
import { test } from "node:test";
import { nextKstMidnight } from "./tip-dismissal.ts";

test("팁 숨김은 서울 자정에 끝난다", () => {
  const midnight = Date.parse("2026-12-31T15:00:00.000Z");
  assert.equal(nextKstMidnight(midnight - 1), midnight);
  assert.equal(nextKstMidnight(midnight), Date.parse("2027-01-01T15:00:00.000Z"));
});
