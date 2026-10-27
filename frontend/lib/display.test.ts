import assert from "node:assert/strict";
import test from "node:test";
import { changeMeta, contributionShare, contributionPercent, contributionWord, formatKstDateTime, formatShares, formatSignedPercent, signedPercent } from "./display.ts";

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

test("본문 크기 말은 기존 전체 합 10% 기준으로 유지한다", () => {
  assert.equal(contributionWord(.12, "하락", 1), "하락 점수를 크게 높였어요.");
  assert.equal(contributionWord(-.05, "상승", 1), "상승 점수를 조금 낮췄어요.");
  assert.equal(contributionWord(-.1, "중립", 1), "중립 점수를 크게 낮췄어요.");
  assert.equal(contributionWord(.3, "상승"), "상승 점수를 높였어요.");
  assert.equal(contributionWord(0, "하락", 1), "하락 점수를 바꾸지 않았어요.");
});

test("상세 영향 비중은 원시 기여값이 아니라 전체 절댓값 합으로 나눈 %다", () => {
  assert.equal(contributionPercent(.12, 1), "12%");
  assert.equal(contributionPercent(-.12, .6), "20%");
  assert.equal(contributionPercent(.6, 1), "60%");
  assert.equal(contributionPercent(-.4, 1), "40%");
  assert.equal(contributionPercent(.1234, 1), "12.3%");
  assert.equal(contributionPercent(-.00000012, 1), "0.1% 미만");
  assert.equal(contributionPercent(-0, 1), "0%");
  for (const total of [undefined, 0, -1, NaN, Infinity, .01]) {
    assert.equal(contributionShare(.12, total), undefined);
    assert.equal(contributionPercent(.12, total), "미제공");
  }
});

test("증감 표시의 방향은 표시 자릿수에 맞추고 반올림된 0에는 부호를 붙이지 않는다", () => {
  for (const value of [0, -0, 0.04, -0.04]) {
    assert.equal(formatSignedPercent(value), "0.0%");
    assert.equal(changeMeta(value, 1).arrow, "");
    assert.equal(changeMeta(value, 1).color, "var(--color-body)");
  }
  assert.equal(formatSignedPercent(1.26), "+1.3%");
  assert.equal(formatSignedPercent(-1.26), "-1.3%");
  assert.equal(signedPercent(0.0126), "+1.3%");
  assert.equal(formatSignedPercent(-0.004, 2), "0.00%");
  assert.equal(changeMeta(0.06, 1).arrow, "▲");
  assert.equal(changeMeta(-0.06, 1).arrow, "▼");
  // 수급처럼 '1만 주 미만'을 말로 표시하는 값은 작은 수량도 실제 방향을 유지한다.
  assert.equal(changeMeta(-1).arrow, "▼");
});

test("범위 끝 원 표시: 오늘 종가 × (1 + %), 유효숫자 3자리", async () => {
  const { bandPrice } = await import("./display.ts");
  assert.equal(bandPrice(100_000, -5.5), "약 94,500원");
  assert.equal(bandPrice(9_950, 40), "약 13,900원");
  assert.equal(bandPrice(812, 3.2), "약 838원");
});

test("기준선과 과거 사례 문장은 pack 값만 쓴다", async () => {
  const { barrierRule, similarCasesLine } = await import("./copy-glossary.ts");
  const text = barrierRule(100_000, 107_500, 94_000, 0.02, 4);
  assert.match(text, /위 107,500원, 아래 94,000원/);
  assert.match(text, /3\.75배 위, 3배 아래/);
  assert.match(text, /4주 안에/);
  assert.equal(similarCasesLine("2019-01-02", "2025-08-29", 7189, 512), "2019년 1월~2025년 8월 중 오늘과 점수가 비슷했던 7,189번(512개 종목)의 결과예요.");
});
