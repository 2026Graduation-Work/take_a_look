// 시장 바: Supabase market_status 최신 행(차트 서빙이 평일 18:47 이후 갱신) → MarketStatus.
// 행이 없거나 읽기 실패면 호출한 쪽의 스냅샷을 그대로 쓴다.

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

export async function loadLatestMarketStatus(): Promise<MarketStatus | null> {
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

// 기준일 뒤로 지난 평일 수(공휴일은 세지 않는 근사). 장 마감 전엔 전 영업일이 최신이라 1까지는 정상.
function weekdaysAfter(date: string, today: string): number {
  let count = 0;
  for (let day = Date.parse(date) + 86_400_000; day <= Date.parse(today); day += 86_400_000) {
    const weekday = new Date(day).getUTCDay();
    if (weekday !== 0 && weekday !== 6) count += 1;
  }
  return count;
}

// 2영업일 이상 밀리면 "N일 전 데이터예요"(N은 달력 날짜 차이), 아니면 null.
export function staleLabel(date: string, now: number = Date.now()): string | null {
  const today = kstDay(now);
  if (weekdaysAfter(date, today) < 2) return null;
  return `${Math.round((Date.parse(today) - Date.parse(date)) / 86_400_000)}일 전 데이터예요`;
}
