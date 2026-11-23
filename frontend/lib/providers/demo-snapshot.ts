import snapshot from "./demo-snapshot.json" with { type: "json" };
import type { DataProvenance, MarketIndexQuote, MarketStatus, StockDetail } from "../types.ts";

export const SNAPSHOT_AS_OF: string = snapshot.asOf;

export const PRICE_PROVENANCE: DataProvenance = {
  kind: "real",
  source: snapshot.stockSource,
  asOf: snapshot.asOf,
};

export interface StockSnapshot {
  name: string;
  close: number;
  changePercent: number;
  prices: { date: string; close: number }[];
  psychology: { axis: number; word: string };
}

export const STOCK_SNAPSHOT = snapshot.stocks as Record<string, StockSnapshot>;

// 투자자별 순매수 수량(주), 기준일까지 최근 20영업일. 기타법인·금액은 원천에 없어 비워 둔다.
export const SUPPLY_SNAPSHOT = snapshot.supply.stocks as Record<
  string,
  { date: string; retail: number; foreign: number; institution: number }[]
>;


export const MARKET_SNAPSHOT: MarketStatus = {
  date: snapshot.market.date,
  provenance: { kind: "real", source: snapshot.market.source, asOf: snapshot.market.date },
  condition: snapshot.market.condition as MarketStatus["condition"],
  // 0~100 = KOSPI 20거래일 실현변동성·평균 거래대금의 직전 1년 백분위
  volatilityScore: Math.round(snapshot.market.volatility.percentile * 100),
  volumeScore: Math.round(snapshot.market.volume.percentile * 100),
  indexQuotes: snapshot.market.indexQuotes as MarketIndexQuote[],
};

export function snapshotPrice(
  code: string,
): Partial<Pick<StockDetail, "currentPrice" | "changePercent" | "asOf" | "priceHistory" | "priceDates" | "priceProvenance">> {
  const stock = STOCK_SNAPSHOT[code];
  if (!stock) return {};
  return {
    currentPrice: stock.close,
    changePercent: stock.changePercent,
    asOf: SNAPSHOT_AS_OF,
    priceHistory: stock.prices.map(({ close }) => close),
    priceDates: stock.prices.map(({ date }) => date),
    priceProvenance: PRICE_PROVENANCE,
  };
}
