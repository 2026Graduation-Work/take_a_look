import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import { parseChartSnapshot, chartChange } from "./chart-public.ts";

const snapshots = JSON.parse(readFileSync(new URL("../../backend/analysis/chart/serving/previews/2026-09-21/snapshots.json", import.meta.url), "utf8"));
const row = (payload: typeof snapshots[number]) => ({ batch_id: payload.batch_id, stock_code: payload.stock_code, horizon: payload.horizon, payload });

test("recorded display-test horizons retain their dates, counts and prices", () => {
  for (const payload of snapshots) {
    const parsed = parseChartSnapshot(row(payload));
    assert.equal(parsed.data_asof, "2026-09-21");
    assert.ok([5, 20].includes(parsed.horizon));
    assert.equal(parsed.distribution.histogram.bins.reduce((n, b) => n + b.count, 0), parsed.distribution.sample_count);
    assert.ok(Number.isFinite(chartChange(parsed)));
    if (!Object.hasOwn(payload.prices, "event_basis")) {
      assert.deepEqual(parsed.prices.eventBasis, { status: "unavailable", reason: "missing_basis" });
    }
  }
});

test("mixed identity, invalid prices and inconsistent distribution are rejected", () => {
  const original = snapshots[0];
  assert.throws(() => parseChartSnapshot({ ...row(original), horizon: 20 }));
  for (const change of [
    (p: typeof original) => { p.prices.history[1].date = p.prices.history[0].date; },
    (p: typeof original) => { p.distribution.sample_count += 1; },
    (p: typeof original) => { p.distribution.histogram.central_68 = null; },
    (p: typeof original) => { p.inference.features[0].contribution = Infinity; },
    (p: typeof original) => { p.inference.scores.up = 2; },
    (p: typeof original) => { p.inference.contribution_abs_sum = -1; },
    (p: typeof original) => { p.inference.contribution_abs_sum = 0; },
    (p: typeof original) => { p.inference.contribution_abs_sum = NaN; },
  ]) {
    const payload = structuredClone(original);
    change(payload);
    assert.throws(() => parseChartSnapshot(row(payload)));
  }
});

test("a matching optional public event basis parses independently of legacy prices", () => {
  const payload = structuredClone(snapshots[0]);
  const first = payload.prices.history[0].date;
  const previous = new Date(Date.parse(first) - 86_400_000).toISOString().slice(0, 10);
  const hash = "a".repeat(64);
  const basis = {
    method: "daily-log-std-250-v1", daily_sigma: .025, return_count: 60,
    period_start: first, period_end: payload.data_asof, input_sha256: hash,
    previous_bar: { date: previous, close: 100, volume: 10 },
  };
  payload.sources = { ...payload.sources, prices_sha256: hash };
  payload.prices.event_basis = basis;
  const parsed = parseChartSnapshot(row(payload));
  assert.deepEqual(parsed.prices.eventBasis, {
    status: "available",
    basis: {
      method: basis.method, dailySigma: .025, returnCount: 60, periodStart: first,
      periodEnd: payload.data_asof, inputSha256: hash, previousBar: basis.previous_bar,
    },
  });
  for (const invalid of [
    { input_sha256: "b".repeat(64) }, { daily_sigma: 0 }, { return_count: 59 }, { period_end: previous },
    { previous_bar: { ...basis.previous_bar, date: first } },
  ]) {
    payload.prices.event_basis = { ...basis, ...invalid };
    const parsed = parseChartSnapshot(row(payload));
    assert.deepEqual(parsed.prices.eventBasis, { status: "unavailable", reason: "invalid_basis" });
    assert.deepEqual(parsed.prices.history, payload.prices.history);
  }
  payload.prices.event_basis = null;
  assert.deepEqual(parseChartSnapshot(row(payload)).prices.eventBasis, { status: "unavailable", reason: "invalid_basis" });
});

test("a missing displayed trading day disables the event basis for either horizon", () => {
  for (const payload of structuredClone(snapshots)) {
    const { history } = payload.prices;
    const start = history[0].date;
    const previous = new Date(Date.parse(start) - 86_400_000).toISOString().slice(0, 10);
    const hash = "a".repeat(64);
    payload.sources = { ...payload.sources, prices_sha256: hash };
    payload.prices.event_basis = {
      method: "daily-log-std-250-v1", daily_sigma: .05, return_count: 60,
      period_start: start, period_end: payload.data_asof, input_sha256: hash,
      previous_bar: { date: previous, close: 100, volume: 10 },
    };
    for (const [index, bar] of history.entries()) bar.close = index < 21 ? 100 : index === 21 ? 110 : 121;
    assert.equal(parseChartSnapshot(row(payload)).prices.eventBasis.status, "available");
    history.splice(21, 1);
    assert.equal(history.length, 59);
    assert.equal(history[20].close, 100);
    assert.equal(history[21].close, 121);
    const parsed = parseChartSnapshot(row(payload));
    assert.deepEqual(parsed.prices.history, history);
    assert.deepEqual(parsed.prices.eventBasis, { status: "unavailable", reason: "incomplete_sessions" });
  }
});
