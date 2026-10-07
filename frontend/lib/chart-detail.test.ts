import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import { chartDetail, chartDirection, clipReturnBins } from "./chart-detail.ts";
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

test("수익률 분포: 1% 미만 tail은 양 끝 한 칸으로 묶고, 빈 칸은 버린다", () => {
  const bins = [
    { from: -30, to: -28, count: 0 },
    { from: -28, to: -26, count: 1 },
    ...Array.from({ length: 10 }, (_, i) => ({ from: -10 + i * 2, to: -8 + i * 2, count: 20 })),
    { from: 40, to: 42, count: 1 },
    { from: 42, to: 44, count: 0 },
  ];
  const clipped = clipReturnBins(bins);
  assert.equal(clipped.length, 12);
  assert.deepEqual(clipped[0], { from: -12, to: -10, count: 1, tail: "low" });
  assert.deepEqual(clipped.at(-1), { from: 10, to: 12, count: 1, tail: "high" });
  assert.equal(clipped.reduce((sum, bin) => sum + bin.count, 0), 202);
  assert.deepEqual(clipReturnBins([{ from: 0, to: 2, count: 0 }]), [{ from: 0, to: 2, count: 0 }]);
});
