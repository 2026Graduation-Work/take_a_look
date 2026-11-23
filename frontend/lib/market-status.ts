import { kstDay } from "./display.ts";
import { getSupabaseClient } from "./supabase.ts";
import type { MarketCondition, MarketIndexQuote, MarketStatus } from "./types";

interface MarketStatusRow {
  status_date: string;
  condition: MarketCondition;
  volatility_score: number;
  volume_score: number;
  index_quotes: MarketIndexQuote[];
}

let latest: Promise<MarketStatus | null> | null = null;
export function loadLatestMarketStatus(): Promise<MarketStatus | null> {
  latest ??= readLatestMarketStatus();
  return latest;
}

async function readLatestMarketStatus(): Promise<MarketStatus | null> {
  const client = getSupabaseClient();
  if (!client) return null;
  const { data } = await client
    .from("market_status")
    .select("status_date,condition,volatility_score,volume_score,index_quotes")
    .order("status_date", { ascending: false })
    .limit(1)
    .maybeSingle<MarketStatusRow>();
  if (!data) return null;
  return {
    date: data.status_date,
    provenance: { kind: "real", source: "KRX 지수(pykrx)", asOf: data.status_date },
    condition: data.condition,
    volatilityScore: data.volatility_score,
    volumeScore: data.volume_score,
    indexQuotes: data.index_quotes,
  };
}

// ponytail: 손으로 적은 목록, 2027년 휴장일(설 2/8~9 등)은 그 전에 덧붙인다.
const KRX_HOLIDAYS = new Set(["2026-10-09", "2026-12-25", "2026-12-31", "2027-01-01"]);

function tradingDaysAfter(date: string, last: string): number {
  let count = 0;
  for (let day = Date.parse(date) + 86_400_000; day <= Date.parse(last); day += 86_400_000) {
    const weekday = new Date(day).getUTCDay();
    if (weekday !== 0 && weekday !== 6 && !KRX_HOLIDAYS.has(new Date(day).toISOString().slice(0, 10))) count += 1;
  }
  return count;
}

// 차트 서빙 게시 시각(평일 18:47 KST). 이 시각 전이면 전 거래일이 최신이다.
const PUBLISH_OFFSET_MS = (18 * 60 + 47) * 60_000;

// 2거래일 이상 밀려야 "N일 전 데이터예요"(N은 달력 날짜 차이). 정기 실행이 몇 시간 늦게 시작해
// 새벽에 게시되는 날이 잦아 1거래일 밀림은 정상으로 본다.
export function staleLabel(date: string, now: number = Date.now()): string | null {
  if (tradingDaysAfter(date, kstDay(now - PUBLISH_OFFSET_MS)) < 2) return null;
  return `${Math.round((Date.parse(kstDay(now)) - Date.parse(date)) / 86_400_000)}일 전 데이터예요`;
}
