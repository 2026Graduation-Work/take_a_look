import assert from "node:assert/strict";
import test from "node:test";
import { contributionWord, formatKstDateTime, formatShares } from "./display.ts";

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

test("모델 근거 크기 말: 전체 합의 10분의 1 기준, 합이 없으면 방향만", () => {
  assert.equal(contributionWord(0.12, 1), "신호를 크게 높임");
  assert.equal(contributionWord(0.05, 1), "신호를 조금 높임");
  assert.equal(contributionWord(-0.05, 1), "신호를 조금 낮춤");
  assert.equal(contributionWord(-0.1, 1), "신호를 크게 낮춤");
  assert.equal(contributionWord(0.3), "신호를 높임");
  assert.equal(contributionWord(0, 1), "신호를 바꾸지 않음");
});
