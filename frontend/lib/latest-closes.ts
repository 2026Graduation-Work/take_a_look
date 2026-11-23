import type { SupabaseClient } from "@supabase/supabase-js";
import { inferenceDirection } from "./chart-detail.ts";
import type { SignalHorizon } from "./copy-glossary.ts";
import type { SignalLight } from "./types.ts";

export type LatestCloses = Map<string, { close: number; asOf: string; signal?: SignalLight }>;

const LIGHT = { up: "positive", flat: "neutral", down: "negative" } as const;

export async function loadLatestCloses(client: Pick<SupabaseClient, "from"> | null, codes: string[], horizon: SignalHorizon = 20, options?: { throwOnError?: boolean }): Promise<LatestCloses> {
  const unique = [...new Set(codes.filter((code) => /^[0-9A-Z]{6}$/.test(code)))];
  if (!client || !unique.length) return new Map();
  const { data, error } = await client
    .from("latest_chart_signal_snapshots")
    .select("stock_code,close:payload->inference->close,as_of:payload->>data_asof,status:payload->inference->>status,scores:payload->inference->scores")
    .eq("horizon", horizon)
    .in("stock_code", unique);
  if (error) {
    if (options?.throwOnError) throw new Error("게시된 신호를 읽지 못했어요.");
    return new Map();
  }
  type Row = { stock_code: string; close: unknown; as_of: string; status: string; scores: { down: number; neutral: number; up: number } | null };
  return new Map(
    ((data ?? []) as Row[]).flatMap((row) => {
      if (typeof row.close !== "number" || row.close <= 0) return [];
      const direction = inferenceDirection({ status: row.status, scores: row.scores } as Parameters<typeof inferenceDirection>[0]);
      return [[row.stock_code, { close: row.close, asOf: row.as_of, ...(direction ? { signal: LIGHT[direction] } : {}) }] as const];
    }),
  );
}
