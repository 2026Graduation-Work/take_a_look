import type { SupabaseClient } from "@supabase/supabase-js";
import { inferenceDirection } from "./chart-detail.ts";
import type { SignalHorizon } from "./copy-glossary.ts";
import type { SignalLight } from "./types.ts";

// change: 전일 대비 등락(원, %). 차트 가격 기록(수정종가) 마지막 두 날로 계산, 기록이 하루뿐이면 없음
export type LatestCloses = Map<string, { close: number; asOf: string; signal?: SignalLight; change?: { won: number; percent: number } }>;

const LIGHT = { up: "positive", flat: "neutral", down: "negative" } as const;

export function dailyChange(history: { close: number }[] | null | undefined): { won: number; percent: number } | null {
  const [prev, last] = (Array.isArray(history) ? history : []).slice(-2).map((point) => point?.close);
  if (typeof prev !== "number" || typeof last !== "number" || !(prev > 0) || !(last > 0)) return null;
  return { won: last - prev, percent: (last / prev - 1) * 100 };
}

// 보유 평가금액용 최신 종가 = 최신 게시 차트 스냅샷(latest_chart_signal_snapshots)의 기준일 종가.
// 같은 행의 방향(기본 4주 H20, 대시보드에서 1주 H5 선택 가능)을 보유 맵의 오늘 신호로 쓴다. 종가는 두 기간이 같다.
// 새 공개 테이블을 만들지 않는다. 읽기 실패나 스냅샷 없는 종목은 빈 값(→ 매입금액 기준).
export async function loadLatestCloses(client: Pick<SupabaseClient, "from"> | null, codes: string[], horizon: SignalHorizon = 20): Promise<LatestCloses> {
  const unique = [...new Set(codes.filter((code) => /^[0-9A-Z]{6}$/.test(code)))];
  if (!client || !unique.length) return new Map();
  const { data, error } = await client
    .from("latest_chart_signal_snapshots")
    .select("stock_code,close:payload->inference->close,as_of:payload->>data_asof,status:payload->inference->>status,scores:payload->inference->scores,history:payload->prices->history")
    .eq("horizon", horizon)
    .in("stock_code", unique);
  if (error) return new Map();
  type Row = { stock_code: string; close: unknown; as_of: string; status: string; scores: { down: number; neutral: number; up: number } | null; history?: { close: number }[] | null };
  return new Map(
    ((data ?? []) as Row[]).flatMap((row) => {
      if (typeof row.close !== "number" || row.close <= 0) return [];
      const direction = inferenceDirection({ status: row.status, scores: row.scores } as Parameters<typeof inferenceDirection>[0]);
      const change = dailyChange(row.history);
      return [[row.stock_code, { close: row.close, asOf: row.as_of, ...(direction ? { signal: LIGHT[direction] } : {}), ...(change ? { change } : {}) }] as const];
    }),
  );
}
