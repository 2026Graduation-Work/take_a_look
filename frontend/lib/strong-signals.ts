import type { SupabaseClient } from "@supabase/supabase-js";
import { AVOIDED_ASSET_LABELS } from "./profiling-rules.ts";
import { passesHardConstraints, type HardConstraints } from "./recommendation-filter.ts";
import type { RiskFlag } from "./types.ts";
import type { SignalHorizon } from "./copy-glossary.ts";

const SHOW = 5;
const SHORTLIST = 30; // 하드 제약으로 빠질 몫을 감안해 방향마다 이만큼만 종목 마스터를 조회

export interface StrongSignal {
  code: string;
  name: string;
  direction: "up" | "down";
  confidence: number;
  asOf: string;
}

export interface SnapshotRow {
  stock_code: string;
  name: string | null;
  as_of: string;
  status: string | null;
  scores: { down: number; neutral: number; up: number } | null;
  volume?: number | string | null; // 게시 기준일 거래량(prices.history 마지막 날)
}

export const isTradable = (row: Pick<SnapshotRow, "status" | "volume">) =>
  row.status === "available" && Number(row.volume ?? 1) > 0;

export function rankSignals(rows: SnapshotRow[]): StrongSignal[] {
  return rows.flatMap((row) => {
    if (!isTradable(row) || !row.scores) return [];
    const ranked = [["down", row.scores.down], ["flat", row.scores.neutral], ["up", row.scores.up]] as const;
    const [first, second] = [...ranked].sort((left, right) => right[1] - left[1]);
    if (first[0] === "flat") return [];
    return [{ code: row.stock_code, name: row.name ?? row.stock_code, direction: first[0], confidence: first[1] - second[1], asOf: row.as_of }];
  }).sort((left, right) => right.confidence - left.confidence || left.code.localeCompare(right.code));
}

export async function loadStrongSignals(
  client: Pick<SupabaseClient, "from"> | null,
  constraints: HardConstraints,
  horizon: SignalHorizon = 20,
): Promise<{ up: StrongSignal[]; down: StrongSignal[]; excluded: { code: string; name: string; reason: string }[] } | null> {
  if (!client) return null;
  const { data, error } = await client
    .from("latest_chart_signal_snapshots")
    .select("stock_code,name:payload->>stock_name,as_of:payload->>data_asof,status:payload->inference->>status,scores:payload->inference->scores,volume:payload->prices->history->-1->>volume")
    .eq("horizon", horizon);
  if (error) return null;
  // 음수 인덱스(->-1)는 PostgREST가 받지만 supabase-js 타입 추론이 못 읽어 unknown을 거친다
  const ranked = rankSignals((data ?? []) as unknown as SnapshotRow[]);
  const shortlist = [...ranked.filter(({ direction }) => direction === "up").slice(0, SHORTLIST),
    ...ranked.filter(({ direction }) => direction === "down").slice(0, SHORTLIST)];
  if (!shortlist.length) return { up: [], down: [], excluded: [] };
  const { data: stocks, error: stockError } = await client
    .from("stocks")
    .select("code,market,risk_grade,risk_flags")
    .in("code", shortlist.map(({ code }) => code));
  if (stockError) return null;
  type Stock = { code: string; market: string; risk_grade: number; risk_flags: string[] | null };
  const byCode = new Map(((stocks ?? []) as Stock[]).map((stock) => [stock.code, stock]));
  const excluded: { code: string; name: string; reason: string }[] = [];
  const kept = shortlist.filter((signal) => {
    const stock = byCode.get(signal.code);
    if (stock?.market !== "KOSPI") return false;
    if (passesHardConstraints(stock.risk_grade, stock.risk_flags ?? [], constraints)) return true;
    excluded.push({ code: signal.code, name: signal.name, reason: (stock.risk_flags ?? []).filter((flag) => constraints.avoided.has(flag)).map((flag) => AVOIDED_ASSET_LABELS[flag as RiskFlag] ?? flag).join(", ") });
    return false;
  });
  return {
    up: kept.filter(({ direction }) => direction === "up").slice(0, SHOW),
    down: kept.filter(({ direction }) => direction === "down").slice(0, SHOW),
    excluded,
  };
}
