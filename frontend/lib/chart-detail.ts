import { chartChange, type ChartSnapshot } from "./chart-public.ts";
import type { HorizonDirection, StockDetail } from "./types.ts";

export function chartDirection(chart: ChartSnapshot | undefined): HorizonDirection | null {
  if (chart?.inference.status !== "available" || !chart.inference.scores) return null;
  const { down, neutral, up } = chart.inference.scores;
  const scores = [["down", down], ["flat", neutral], ["up", up]] as const;
  return scores.reduce((best, next) => next[1] > best[1] ? next : best)[0];
}

// Keep the existing view model; replace only fields present in the serving output.
export function chartDetail(detail: StockDetail, chart: ChartSnapshot | undefined): StockDetail {
  const band = chart?.distribution.histogram.central_68;
  return {
    ...detail,
    currentPrice: chart?.prices.history.at(-1)?.close,
    changePercent: chart ? chartChange(chart) ?? undefined : undefined,
    asOf: chart?.data_asof ?? "",
    returnHorizon: "h20",
    priceHistory: chart?.prices.history.map(p => p.close) ?? [],
    priceDates: chart?.prices.history.map(p => p.date) ?? [],
    priceProvenance: { kind: "real", source: chart?.prices.source.replace("KRX adjusted daily OHLCV", "KRX 수정종가") ?? "KRX", asOf: chart?.data_asof },
    provenance: { kind: "real", source: "LGBM · 20거래일 · 검증 전", asOf: chart?.data_asof },
    returnBand: { low: band?.low ?? 0, high: band?.high ?? 0, ciLevel: .68 },
    realizedReturns: chart?.distribution.histogram.bins.map(b => ({ from: b.left, to: b.right, count: b.count })) ?? [],
    similarCaseCount: chart?.distribution.sample_count ?? 0,
    reasons: [],
    aiAdvice: undefined,
  };
}
