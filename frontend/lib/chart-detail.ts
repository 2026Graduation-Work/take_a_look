import { chartChange, type ChartSnapshot } from "./chart-public.ts";
import type { HorizonDirection, ReturnBin, StockDetail } from "./types.ts";

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

export type ClippedBin = ReturnBin & { tail?: "low" | "high" };

// 분포 양 끝 tail(기본 각 1%)을 "그 이하"·"그 이상" 한 칸씩으로 묶어, 막대가 1~99% 구간 폭을 채우게 한다.
// 묶은 칸은 바로 옆 칸과 같은 폭으로 붙인다(그리는 자리일 뿐 실제 수익률 범위는 아니다).
export function clipReturnBins(bins: readonly ReturnBin[], tail = 0.01): ClippedBin[] {
  const total = bins.reduce((sum, bin) => sum + bin.count, 0);
  if (!total) return [...bins];
  let lo = 0;
  let below = 0;
  while (lo < bins.length - 1 && below + bins[lo].count <= total * tail) below += bins[lo++].count;
  let hi = bins.length - 1;
  let above = 0;
  while (hi > lo && above + bins[hi].count <= total * tail) above += bins[hi--].count;
  const kept: ClippedBin[] = bins.slice(lo, hi + 1);
  const first = kept[0];
  const last = kept[kept.length - 1];
  return [
    ...(below ? [{ from: first.from - (first.to - first.from), to: first.from, count: below, tail: "low" as const }] : []),
    ...kept,
    ...(above ? [{ from: last.to, to: last.to + (last.to - last.from), count: above, tail: "high" as const }] : []),
  ];
}
