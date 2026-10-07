// 데모 4종목·시장 지수 실데이터 스냅샷(기준일 2025-12-30). 생성: frontend/scripts/build_demo_snapshot.py
// 원천·산식은 그 스크립트 머리말에 있다. 예측 스코어·순위·신호는 여기에 없다(예시 유지, 이슈 #107).

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


export const SUPPLY_PROVENANCE: DataProvenance = {
  kind: "real",
  source: snapshot.supply.source,
  asOf: snapshot.asOf,
};

export const MARKET_SNAPSHOT: MarketStatus = {
  date: snapshot.market.date,
  provenance: { kind: "real", source: snapshot.market.source, asOf: snapshot.market.date },
  condition: snapshot.market.condition as MarketStatus["condition"],
  // 0~100 = KOSPI 20거래일 실현변동성·평균 거래대금의 직전 1년 백분위
  volatilityScore: Math.round(snapshot.market.volatility.percentile * 100),
  volumeScore: Math.round(snapshot.market.volume.percentile * 100),
  indexQuotes: snapshot.market.indexQuotes as MarketIndexQuote[],
};

// 상세 화면 시세 필드. 스냅샷에 없는 종목은 빈 객체(시세 없음으로 표시).
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
