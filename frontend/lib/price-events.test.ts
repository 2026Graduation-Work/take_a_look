import assert from "node:assert/strict";
import { test } from "node:test";
import { isCalendarDate, selectPriceMoves, type DatedClose, type PriceEventBasis } from "./price-events.ts";

function prices(): DatedClose[] {
  return Array.from({ length: 61 }, (_, index) => ({
    date: new Date(Date.UTC(2026, 7, index + 1)).toISOString().slice(0, 10),
    close: 100,
    volume: 1_000,
  }));
}

function basis(bars: DatedClose[], sigma = .025): PriceEventBasis {
  return {
    method: "daily-log-std-250-v1", dailySigma: sigma, returnCount: 60,
    periodStart: bars[1].date, periodEnd: bars[60].date, previousBar: bars[0], inputSha256: "a".repeat(64),
  };
}

test("the first of 60 displayed days uses the extra bar and an absent bar leaves 59 pairs", () => {
  const bars = prices();
  for (const bar of bars.slice(1)) bar.close = 108;
  const result = selectPriceMoves(bars.slice(1), basis(bars), bars[60].date);
  assert.equal(result.status, "ready");
  assert.equal(result.evaluatedDays, 60);
  assert.deepEqual(result.moves.map(move => [move.date, move.previousDate, Math.round(move.changePercent)]),
    [[bars[1].date, bars[0].date, 8]]);
  assert.deepEqual(selectPriceMoves(bars.slice(1), { ...basis(bars), previousBar: null }, bars[60].date),
    { status: "ready", moves: [], evaluatedDays: 59, excludedDays: 1 });
});

test("strict unrounded threshold, latest tie breaker, strongest three and snapshot boundary", () => {
  const bars = prices();
  for (const [index, close] of [[0, 128], [1, 144], [2, 128], [3, 144.001], [4, 128], [5, 160], [6, 128], [58, 160], [59, 128], [60, 160]]) {
    bars[index].close = close;
  }
  for (const bar of bars.slice(7, 58)) bar.close = 128;
  const result = selectPriceMoves(bars.slice(1), basis(bars, .0625), bars[60].date);
  assert.equal(result.status, "ready");
  assert.deepEqual(result.moves.map(move => move.date), [bars[60].date, bars[58].date, bars[5].date]);
  assert.equal(result.moves[0].changePercent, 25);
  assert.deepEqual(result.moves[0].disclosureWindow, { from: bars[59].date, through: bars[60].date, endReason: "snapshot_boundary" });
  assert.deepEqual(result.moves[1].disclosureWindow, { from: bars[57].date, through: bars[59].date, endReason: "next_session_included" });

  const boundary = prices();
  boundary[0].close = 128;
  for (const bar of boundary.slice(1)) bar.close = 144;
  assert.deepEqual(selectPriceMoves(boundary.slice(1), basis(boundary, .0625), boundary[60].date),
    { status: "ready", moves: [], evaluatedDays: 60, excludedDays: 0 });
  for (const bar of boundary.slice(1)) bar.close = 144.001;
  const above = selectPriceMoves(boundary.slice(1), basis(boundary, .0625), boundary[60].date);
  assert.equal(above.status, "ready");
  assert.ok(above.moves[0].changePercent > 12.5);
});

test("exact +10% and -10% returns do not exceed twice a 5% daily sigma", () => {
  for (const close of [110, 90]) {
    const bars = prices();
    for (const bar of bars.slice(1)) bar.close = close;
    assert.deepEqual(selectPriceMoves(bars.slice(1), basis(bars, .05), bars[60].date),
      { status: "ready", moves: [], evaluatedDays: 60, excludedDays: 0 });
  }
});

test("equally large rises and falls are ranked by latest date", () => {
  const bars = prices();
  const closes = [10000, 11000, 9900, 10890, 9801];
  for (const [index, bar] of bars.entries()) bar.close = closes[Math.min(index, closes.length - 1)];
  const result = selectPriceMoves(bars.slice(1), basis(bars, .04), bars[60].date);
  assert.equal(result.status, "ready");
  assert.deepEqual(result.moves.map(({ date, changePercent }) => [date, changePercent]),
    [[bars[4].date, -10], [bars[3].date, 10], [bars[2].date, -10]]);
});

test("reconstructing adjusted closes cannot turn an exact threshold into a move", () => {
  const bars = prices();
  bars[0].close = 290 * (1000 / 290);
  for (const bar of bars.slice(1)) bar.close = 319 * (1100 / 319);
  assert.equal(bars[0].close, 999.9999999999999);
  const eventBasis = basis(bars, .05);
  const dataAsOf = bars[60].date;
  assert.deepEqual(selectPriceMoves(bars.slice(1), eventBasis, dataAsOf),
    { status: "ready", moves: [], evaluatedDays: 60, excludedDays: 0 });
  for (const bar of bars.slice(1)) bar.close = 319 * (1100.000001 / 319);
  const above = selectPriceMoves(bars.slice(1), eventBasis, dataAsOf);
  assert.equal(above.status, "ready");
  assert.equal(above.moves.length, 1);
  assert.equal(above.moves[0].date, bars[1].date);
  assert.ok(above.moves[0].changePercent > 10);
});

test("roundoff from reconstructing adjusted prices does not reorder tied returns", () => {
  const bars = prices();
  const adjusted = [10000, 11000, 9900, 10890, 9801];
  const raw = [139, 81, 77, 77, 141];
  for (const [index, bar] of bars.entries()) {
    const n = Math.min(index, adjusted.length - 1);
    bar.close = raw[n] * (adjusted[n] / raw[n]);
  }
  const result = selectPriceMoves(bars.slice(1), basis(bars, .04), bars[60].date);
  assert.equal(result.status, "ready");
  assert.deepEqual(result.moves.map(({ date, changePercent }) => [date, Math.round(changePercent)]),
    [[bars[4].date, -10], [bars[3].date, 10], [bars[2].date, -10]]);
});

test("zero volume excludes both adjacent returns, and zero pairs differ from zero candidates", () => {
  const bars = prices();
  bars[30].volume = 0;
  assert.deepEqual(selectPriceMoves(bars.slice(1), basis(bars), bars[60].date),
    { status: "ready", moves: [], evaluatedDays: 58, excludedDays: 2 });
  for (const bar of bars) bar.volume = 0;
  assert.deepEqual(selectPriceMoves(bars.slice(1), basis(bars), bars[60].date),
    { status: "unavailable", reason: "no_evaluable_returns" });
});

test("invalid basis, wrong end and malformed dates do not produce markers", () => {
  const bars = prices();
  const end = bars[60].date;
  assert.equal(isCalendarDate("2024-02-29"), true);
  assert.equal(isCalendarDate("2026-02-29"), false);
  assert.deepEqual(selectPriceMoves(bars.slice(1), undefined, end), { status: "unavailable", reason: "missing_basis" });
  for (const value of [{ ...basis(bars), dailySigma: 0 }, { ...basis(bars), returnCount: 59 }, { ...basis(bars), periodEnd: bars[59].date }]) {
    assert.deepEqual(selectPriceMoves(bars.slice(1), value, end), { status: "unavailable", reason: "invalid_basis" });
  }
  const duplicate = [...bars.slice(1, 60), bars[59]];
  assert.deepEqual(selectPriceMoves(duplicate, basis(bars), end), { status: "unavailable", reason: "incomplete_sessions" });
});
