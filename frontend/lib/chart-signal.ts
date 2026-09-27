import { getSupabaseClient } from "./supabase";

// Derived from serving/contracts/chart_signal_detail_v1.schema.json and v2.
interface ChartSignalBase {
  stock_code: string;
  stock_name: string;
  data_asof: string;
  horizon: 5 | 20;
  profile: "stable" | "aggressive";
  release_id: string;
  batch_id: string;
  inference: {
    status: "available" | "unavailable";
    reason: string | null;
    scores: { down: number; neutral: number; up: number } | null;
    score_event: "class_2_upper_barrier_first";
    close: number | null;
    sigma: number | null;
    barriers: { up: number; down: number } | null;
    contribution_space: "class_2_raw_margin";
    features: { name: string; label_ko: string; meaning_ko: string; value: number | null; contribution: number }[];
  };
  prices: {
    basis: "adjusted_close";
    source: string;
    history: { date: string; close: number; volume: number }[];
  };
  sources: {
    model_sha256: string | null;
    features_sha256: string | null;
    prices_sha256: string | null;
    cases_sha256: string | null;
    config_sha256: string | null;
  };
}

export interface ChartSignalDetailV1 extends ChartSignalBase {
  contract: "chart_signal_detail_v1";
  cases: {
    status: "available" | "no_cases" | "unavailable";
    reason: string | null;
    policy_id: "same_stock_up_down_001_sigma_rel010_v1";
    current: { up: number; down: number; sigma: number } | null;
    tolerances: { up_absolute: 0.01; down_absolute: 0.01; sigma_relative: 0.1 };
    sample_count: number;
    up_count: number;
    down_count: number;
    both_count: number;
    neither_count: number;
    up_rate: number | null;
    down_rate: number | null;
    period_start: string | null;
    period_end: string | null;
    observed_through: string | null;
    by_fold: Record<string, number>;
    by_year: Record<string, number>;
  };
}

export interface ChartSignalDetailV2 extends ChartSignalBase {
  contract: "chart_signal_detail_v2";
  pack_id: string;
  distribution: {
    status: "available" | "no_cases" | "unavailable";
    reason: string | null;
    policy_id: "multi_stock_up_sigma_001_005_v1";
    current: { up: number; sigma: number } | null;
    tolerances: { up_absolute: 0.01; sigma_relative: 0.05 };
    sample_count: number;
    stock_count: number;
    period_start: string | null;
    period_end: string | null;
    observed_through: string | null;
    by_fold: Record<string, number>;
    histogram: {
      bins: { left: number; right: number; count: number }[];
      central_68: { low: number; high: number } | null;
    };
  };
}

export type ChartSignalDetail = ChartSignalDetailV1 | ChartSignalDetailV2;

export interface PublishedChartDetail {
  name: string;
  snapshots: Partial<Record<5 | 20, ChartSignalDetail>>;
  initialHorizon: 5 | 20;
  stale: Partial<Record<5 | 20, boolean>>;
}

function isChartSignalDetail(value: unknown, code: string, batchId: string): value is ChartSignalDetail {
  if (!value || typeof value !== "object") return false;
  const row = value as Partial<ChartSignalDetail>;
  const validDistribution = row.contract === "chart_signal_detail_v2" &&
    typeof row.pack_id === "string" && !!row.distribution &&
    Number.isInteger(row.distribution.sample_count) &&
    Number.isInteger(row.distribution.stock_count) &&
    Array.isArray(row.distribution.histogram?.bins);
  const validCases = row.contract === "chart_signal_detail_v1" &&
    !!row.cases && Number.isInteger(row.cases.sample_count);
  return (validDistribution || validCases) && row.stock_code === code &&
    typeof row.stock_name === "string" && row.stock_name.length > 0 &&
    row.batch_id === batchId && (row.horizon === 5 || row.horizon === 20) &&
    !!row.inference && Array.isArray(row.inference.features) &&
    !!row.prices && Array.isArray(row.prices.history) && !!row.sources;
}

export async function getPublishedChartDetail(code: string): Promise<PublishedChartDetail | null> {
  const client = getSupabaseClient();
  if (!client) return null;
  const { data: rows, error } = await client.from("latest_chart_signal_snapshots")
    .select("batch_id,horizon,payload")
    .eq("stock_code", code);
  if (error) throw new Error(`공개된 차트 신호 조회 실패: ${error.message}`);
  if (!rows?.length) return null;

  const snapshots: PublishedChartDetail["snapshots"] = {};
  for (const row of rows) {
    if (!isChartSignalDetail(row.payload, code, row.batch_id) || row.horizon !== row.payload.horizon) {
      throw new Error("공개 차트 데이터의 계약이 맞지 않습니다.");
    }
    snapshots[row.payload.horizon] = row.payload;
  }
  if (snapshots[5]?.batch_id !== snapshots[20]?.batch_id) {
    throw new Error("두 기간의 차트 데이터 배치가 다릅니다.");
  }

  let profile: "stable" | "aggressive" = "stable";
  const { data: auth } = await client.auth.getUser();
  if (auth.user) {
    const { data: user } = await client.from("users")
      .select("id").eq("auth_user_id", auth.user.id).maybeSingle();
    if (user) {
      const { data: ips } = await client.from("ips_profiles")
        .select("profile_type").eq("user_id", user.id).maybeSingle();
      if (ips?.profile_type === "aggressive") profile = "aggressive";
    }
  }
  return {
    name: snapshots[5]?.stock_name ?? snapshots[20]?.stock_name ?? code,
    snapshots,
    initialHorizon: profile === "aggressive" ? 5 : 20,
    stale: Object.fromEntries(([5, 20] as const).map((horizon) => [horizon,
      !!snapshots[horizon] && Date.now() - new Date(`${snapshots[horizon].data_asof}T00:00:00+09:00`).getTime() > 5 * 24 * 60 * 60 * 1000,
    ])) as PublishedChartDetail["stale"],
  };
}
