import { PREVIEW_BATCH_ID } from "./chart-preview-config.ts";
import { getSupabaseClient } from "./supabase.ts";

export type ChartProfile = "stable" | "aggressive";
export type ChartHorizon = 5 | 20;

export interface ChartSnapshot {
  contract: "chart_signal_detail_v2";
  stock_code: string;
  stock_name: string;
  data_asof: string;
  horizon: ChartHorizon;
  profile: ChartProfile;
  release_id: string;
  batch_id: string;
  pack_id: string;
  inference: {
    status: "available" | "unavailable";
    reason: string | null;
    contribution_space: "class_2_raw_margin";
    features: { name: string; label_ko: string; meaning_ko: string; value: number | null; contribution: number }[];
  };
  distribution: {
    status: "available" | "no_cases" | "unavailable";
    reason: string | null;
    sample_count: number;
    period_start: string | null;
    period_end: string | null;
    stock_count: number;
    histogram: {
      bins: { left: number; right: number; count: number }[];
      central_68: { low: number; high: number } | null;
    };
  };
  prices: {
    basis: "adjusted_close";
    source: string;
    history: { date: string; close: number; volume: number }[];
  };
}

interface ChartRow {
  batch_id: string;
  stock_code: string;
  horizon: number;
  payload: unknown;
}

const record = (value: unknown): value is Record<string, unknown> =>
  typeof value === "object" && value !== null && !Array.isArray(value);
const number = (value: unknown): value is number => typeof value === "number" && Number.isFinite(value);
const date = (value: unknown): value is string =>
  typeof value === "string" && /^\d{4}-\d{2}-\d{2}$/.test(value);

export function parseChartSnapshot(row: ChartRow): ChartSnapshot {
  const p = row.payload;
  if (!record(p) || !record(p.inference) || !record(p.distribution) || !record(p.prices)) {
    throw new Error("차트 응답 구조가 올바르지 않습니다.");
  }
  const inference = p.inference;
  const distribution = p.distribution;
  const prices = p.prices;
  const histogram = distribution.histogram;
  const history = prices.history;
  const bins = record(histogram) ? histogram.bins : null;
  const central = record(histogram) ? histogram.central_68 : null;
  if (
    p.contract !== "chart_signal_detail_v2" || p.stock_code !== row.stock_code ||
    p.batch_id !== row.batch_id || p.horizon !== row.horizon ||
    (p.horizon !== 5 && p.horizon !== 20) ||
    p.profile !== (p.horizon === 5 ? "aggressive" : "stable") ||
    typeof p.stock_name !== "string" || !p.stock_name || !date(p.data_asof) ||
    typeof p.release_id !== "string" || !p.release_id ||
    typeof p.pack_id !== "string" || !p.pack_id ||
    !["available", "unavailable"].includes(String(inference.status)) ||
    inference.contribution_space !== "class_2_raw_margin" ||
    !Array.isArray(inference.features) ||
    !inference.features.every((feature: unknown) => record(feature) &&
      typeof feature.name === "string" && typeof feature.label_ko === "string" &&
      typeof feature.meaning_ko === "string" &&
      (feature.value === null || number(feature.value)) && number(feature.contribution)) ||
    !["available", "no_cases", "unavailable"].includes(String(distribution.status)) ||
    !Number.isInteger(distribution.stock_count) || Number(distribution.stock_count) < 0 ||
    (distribution.period_start !== null && !date(distribution.period_start)) ||
    (distribution.period_end !== null && !date(distribution.period_end)) ||
    !Number.isInteger(distribution.sample_count) || Number(distribution.sample_count) < 0 ||
    !Array.isArray(bins) ||
    !bins.every((bin: unknown) => record(bin) && number(bin.left) && number(bin.right) &&
      bin.left < bin.right && Number.isInteger(bin.count) && Number(bin.count) >= 0) ||
    (central !== null && (!record(central) || !number(central.low) || !number(central.high) || central.low > central.high)) ||
    bins.reduce((sum: number, bin: { count: number }) => sum + bin.count, 0) !== distribution.sample_count ||
    prices.basis !== "adjusted_close" || typeof prices.source !== "string" || !Array.isArray(history) ||
    !history.every((point: unknown) => record(point) && date(point.date) && number(point.close) &&
      point.close > 0 && number(point.volume) && point.volume >= 0)
  ) {
    throw new Error("차트 응답 값이 계약과 일치하지 않습니다.");
  }
  if (distribution.status === "available" &&
      (!central || !distribution.sample_count || !distribution.stock_count || !distribution.period_start || !distribution.period_end)) {
    throw new Error("과거 사례 분포가 완전하지 않습니다.");
  }
  if (history.some((point: { date: string }, i: number) => point.date > String(p.data_asof) ||
      (i > 0 && point.date <= history[i - 1].date))) throw new Error("가격 기준일이 올바르지 않습니다.");
  return p as unknown as ChartSnapshot;
}

export async function loadPublicCharts(codes: string[]): Promise<Map<string, Map<ChartHorizon, ChartSnapshot>>> {
  const client = getSupabaseClient();
  if (!client) throw new Error("차트 연결 설정이 없습니다. 잠시 뒤 다시 시도해 주세요.");
  const unique = [...new Set(codes.filter((code) => /^[0-9A-Z]{6}$/.test(code)))];
  const result = new Map<string, Map<ChartHorizon, ChartSnapshot>>();
  if (!unique.length) return result;
  const { data, error } = await client.from("chart_signal_snapshots")
    .select("batch_id,stock_code,horizon,payload").eq("batch_id", PREVIEW_BATCH_ID).in("stock_code", unique);
  if (error) throw new Error("차트를 불러오지 못했어요. 잠시 뒤 다시 시도해 주세요.");
  const rows = (data ?? []) as ChartRow[];
  const batchIds = new Set(rows.map((row) => row.batch_id));
  const asOfDates = new Set<string>();
  if (batchIds.size > 1) throw new Error("서로 다른 차트 배치가 섞였습니다.");
  for (const row of rows) {
    const snapshot = parseChartSnapshot(row);
    asOfDates.add(snapshot.data_asof);
    const byHorizon = result.get(row.stock_code) ?? new Map<ChartHorizon, ChartSnapshot>();
    if (byHorizon.has(snapshot.horizon)) throw new Error("중복된 기간 데이터가 있습니다.");
    byHorizon.set(snapshot.horizon, snapshot);
    result.set(row.stock_code, byHorizon);
  }
  if (asOfDates.size > 1) throw new Error("서로 다른 차트 기준일이 섞였습니다.");
  for (const horizons of result.values()) {
    if (horizons.size !== 2) throw new Error("두 기간의 차트가 모두 준비되지 않았어요.");
  }
  return result;
}

export function chartChange(snapshot: ChartSnapshot): number | null {
  const history = snapshot.prices.history;
  if (history.length < 2) return null;
  return (history.at(-1)!.close / history.at(-2)!.close - 1) * 100;
}
