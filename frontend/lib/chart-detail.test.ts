import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import { chartDetail, chartDirection } from "./chart-detail.ts";
import { stockDetails } from "./mock-data.ts";
import { parseChartSnapshot } from "./chart-public.ts";

const snapshots = JSON.parse(readFileSync(new URL("../../backend/analysis/chart/serving/previews/2026-09-21/snapshots.json", import.meta.url), "utf8"));
const charts = snapshots.map((payload: typeof snapshots[number]) => parseChartSnapshot({
  batch_id: payload.batch_id, stock_code: payload.stock_code, horizon: payload.horizon, payload,
}));

test("recorded models supply their own directions and replace the demo prices and distribution", () => {
  for (const chart of charts) assert.equal(chartDirection(chart), "down");
  const chart = charts.find((c: typeof charts[number]) => c.horizon === 20)!;
  const detail = chartDetail(stockDetails["005930"], chart);
  assert.equal(detail.asOf, "2026-09-21");
  assert.equal(detail.currentPrice, chart.prices.history.at(-1)!.close);
  assert.deepEqual(detail.priceDates, chart.prices.history.map((p: {date: string}) => p.date));
  assert.deepEqual(detail.returnBand, { ...chart.distribution.histogram.central_68, ciLevel: .68 });
  assert.equal(detail.realizedReturns!.reduce((n, b) => n + b.count, 0), detail.similarCaseCount);
  assert.deepEqual(detail.reasons, []);
  assert.equal(detail.aiAdvice, undefined);
});

test("missing public data does not retain demo chart values or invent a direction", () => {
  const detail = chartDetail(stockDetails["005930"], undefined);
  assert.equal(chartDirection(undefined), null);
  assert.equal(detail.currentPrice, undefined);
  assert.deepEqual(detail.priceHistory, []);
  assert.deepEqual(detail.realizedReturns, []);
  assert.deepEqual(detail.reasons, []);
});
