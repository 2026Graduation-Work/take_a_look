"use client";

import { usePublicCharts } from "@/lib/use-public-charts";
import { chartDetail } from "@/lib/chart-detail";
import type { StockDetailData } from "@/lib/queries";
import type { StockInsights } from "@/lib/providers";
import StockDetailView from "./stock-detail";

export default function ChartPreviewDetail({ data, insights }: {
  data: StockDetailData; insights: StockInsights;
}) {
  const { charts, loading, error, retry } = usePublicCharts([data.detail.code]);
  const snapshots = charts?.get(data.detail.code);
  const detail = chartDetail(data.detail, snapshots?.get(20));
  return <StockDetailView {...data} detail={detail}
    insights={{ ...insights, provenance: { ...insights.provenance, contributions: detail.provenance } }}
    chartSnapshots={snapshots ?? null} loading={loading}
    dataError={error || (!loading && !snapshots ? "시험 결과가 아직 준비되지 않았어요." : "")}
    onRetry={retry} />;
}
