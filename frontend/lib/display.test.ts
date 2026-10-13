import assert from "node:assert/strict";
import test from "node:test";
import { formatKstDateTime, formatShares } from "./display.ts";

test("formatKstDateTime shows UTC timestamps in Korean time and leaves dates alone", () => {
  assert.equal(formatKstDateTime("2026-10-06T03:53:12.940604+00:00"), "2026.10.06 12:53");
  assert.equal(formatKstDateTime("2026-10-02"), "2026.10.02");
});

test("수급 수량 표기는 -0을 만들지 않는다", () => {
  assert.equal(formatShares(0), "변동 없음");
  assert.equal(formatShares(-0), "변동 없음");
  assert.equal(formatShares(-400), "1만 주 미만 순매도");
  assert.equal(formatShares(9_999), "1만 주 미만 순매수");
  assert.equal(formatShares(-10_000), "-1만 주");
  assert.equal(formatShares(5_276_406), "+527.6만 주");
  for (let value = -30_000; value <= 30_000; value += 7) assert.ok(!formatShares(value).includes("-0"), String(value));
});
