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

// 한 화면에서 시장 바·출처 표가 같이 부르므로 요청은 한 번만(새로고침하면 다시 읽는다)
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

// KRX가 쉬는 평일. 이 날은 게시가 없어 밀린 날로 세지 않는다.
// ponytail: 손으로 적은 목록, 2027년 휴장일(설 2/8~9 등)은 그 전에 덧붙인다.
const KRX_HOLIDAYS = new Set(["2026-10-09", "2026-12-25", "2026-12-31", "2027-01-01"]);

// 기준일 뒤로 last까지 지난 거래일 수(주말, KRX_HOLIDAYS 제외).
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

// 게시됐어야 할 거래일보다 2거래일 이상 밀리면 "N일 전 데이터예요"(N은 달력 날짜 차이), 아니면 null.
// 1거래일은 정상으로 본다: 정기 실행이 몇 시간 늦게 시작하고 2시간 걸려 새벽에 게시되는 날이 잦다(10/20 → 10/21 01:35).
export function staleLabel(date: string, now: number = Date.now()): string | null {
  if (tradingDaysAfter(date, kstDay(now - PUBLISH_OFFSET_MS)) < 2) return null;
  return `${Math.round((Date.parse(kstDay(now)) - Date.parse(date)) / 86_400_000)}일 전 데이터예요`;
}
