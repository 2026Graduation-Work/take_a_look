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
  ]) {
    const payload = structuredClone(original);
    change(payload);
    assert.throws(() => parseChartSnapshot(row(payload)));
  }
});
