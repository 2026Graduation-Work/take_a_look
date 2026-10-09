import type { SupabaseClient } from "@supabase/supabase-js";
import { AVOIDED_ASSET_LABELS } from "./profiling-rules.ts";
import { passesHardConstraints, type HardConstraints } from "./recommendation-filter.ts";
import type { RiskFlag } from "./types.ts";

// 대시보드 "오늘 신호가 강한 종목": 최신 게시 배치의 코스피 전 종목에서 4주(H20) 분류 점수의
// 확신도(가장 높은 점수 − 두 번째 점수)가 큰 순으로 상방·하방 각 SHOW개. 규칙 코드이며 성향으로 거르지 않는다.
// 사용자가 직접 고른 회피 항목(하드 제약)만 뺀다. payload 전체 대신 필요한 경로만 한 번에 읽는다.
export const SHOW = 5;
const SHORTLIST = 30; // 하드 제약으로 빠질 몫을 감안해 방향마다 이만큼만 종목 마스터를 조회

export interface StrongSignal {
  code: string;
  name: string;
  direction: "up" | "down";
  confidence: number;
  why: string | null; // 기여도 1위 항목명(payload.inference.features는 |기여도| 내림차순)
  asOf: string;
}

export interface SnapshotRow {
  stock_code: string;
  name: string | null;
  as_of: string;
  status: string | null;
  scores: { down: number; neutral: number; up: number } | null;
  why: string | null;
}

// 확신도 순위(순수 함수). 중립이 1위인 종목은 넣지 않는다.
export function rankSignals(rows: SnapshotRow[]): StrongSignal[] {
  return rows.flatMap((row) => {
    if (row.status !== "available" || !row.scores) return [];
    const ranked = [["down", row.scores.down], ["flat", row.scores.neutral], ["up", row.scores.up]] as const;
    const [first, second] = [...ranked].sort((left, right) => right[1] - left[1]);
    if (first[0] === "flat") return [];
    return [{ code: row.stock_code, name: row.name ?? row.stock_code, direction: first[0], confidence: first[1] - second[1], why: row.why, asOf: row.as_of }];
  }).sort((left, right) => right.confidence - left.confidence || left.code.localeCompare(right.code));
}

export async function loadStrongSignals(
  client: Pick<SupabaseClient, "from"> | null,
  constraints: HardConstraints,
): Promise<{ up: StrongSignal[]; down: StrongSignal[]; excluded: { code: string; name: string; reason: string }[] } | null> {
  if (!client) return null;
  const { data, error } = await client
    .from("latest_chart_signal_snapshots")
    .select("stock_code,name:payload->>stock_name,as_of:payload->>data_asof,status:payload->inference->>status,scores:payload->inference->scores,why:payload->inference->features->0->>label_ko")
    .eq("horizon", 20);
  if (error) return null;
  const ranked = rankSignals((data ?? []) as SnapshotRow[]);
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
