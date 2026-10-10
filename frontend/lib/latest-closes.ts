import type { SupabaseClient } from "@supabase/supabase-js";
import { inferenceDirection } from "./chart-detail.ts";
import type { SignalLight } from "./types.ts";

export type LatestCloses = Map<string, { close: number; asOf: string; signal?: SignalLight }>;

const LIGHT = { up: "positive", flat: "neutral", down: "negative" } as const;

// 보유 평가금액용 최신 종가 = 최신 게시 차트 스냅샷(latest_chart_signal_snapshots)의 기준일 종가.
// 같은 행의 4주(H20) 방향을 보유 맵의 오늘 신호로 쓴다(종목 상세·오늘 목록과 같은 값).
// 새 공개 테이블을 만들지 않는다. 읽기 실패나 스냅샷 없는 종목은 빈 값(→ 매입금액 기준).
export async function loadLatestCloses(client: Pick<SupabaseClient, "from"> | null, codes: string[]): Promise<LatestCloses> {
  const unique = [...new Set(codes.filter((code) => /^[0-9A-Z]{6}$/.test(code)))];
  if (!client || !unique.length) return new Map();
  const { data, error } = await client
    .from("latest_chart_signal_snapshots")
    .select("stock_code,close:payload->inference->close,as_of:payload->>data_asof,status:payload->inference->>status,scores:payload->inference->scores")
    .eq("horizon", 20)
    .in("stock_code", unique);
  if (error) return new Map();
  type Row = { stock_code: string; close: unknown; as_of: string; status: string; scores: { down: number; neutral: number; up: number } | null };
  return new Map(
    ((data ?? []) as Row[]).flatMap((row) => {
      if (typeof row.close !== "number" || row.close <= 0) return [];
      const direction = inferenceDirection({ status: row.status, scores: row.scores } as Parameters<typeof inferenceDirection>[0]);
      return [[row.stock_code, { close: row.close, asOf: row.as_of, ...(direction ? { signal: LIGHT[direction] } : {}) }] as const];
    }),
  );
}
