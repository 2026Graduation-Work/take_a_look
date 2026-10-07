import type { SupabaseClient } from "@supabase/supabase-js";

export type LatestCloses = Map<string, { close: number; asOf: string }>;

// 보유 평가금액용 최신 종가 = 최신 게시 차트 스냅샷(latest_chart_signal_snapshots)의 기준일 종가.
// 새 공개 테이블을 만들지 않는다. 읽기 실패나 스냅샷 없는 종목은 빈 값(→ 매입금액 기준).
export async function loadLatestCloses(client: Pick<SupabaseClient, "from"> | null, codes: string[]): Promise<LatestCloses> {
  const unique = [...new Set(codes.filter((code) => /^[0-9A-Z]{6}$/.test(code)))];
  if (!client || !unique.length) return new Map();
  const { data, error } = await client
    .from("latest_chart_signal_snapshots")
    .select("stock_code,close:payload->inference->close,as_of:payload->>data_asof")
    .eq("horizon", 20)
    .in("stock_code", unique);
  if (error) return new Map();
  return new Map(
    ((data ?? []) as Array<{ stock_code: string; close: unknown; as_of: string }>).flatMap((row) =>
      typeof row.close === "number" && row.close > 0 ? [[row.stock_code, { close: row.close, asOf: row.as_of }] as const] : [],
    ),
  );
}
