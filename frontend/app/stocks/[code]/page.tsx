import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { cache } from "react";
import StockDetailBoundary from "@/app/components/stock-detail-boundary";
import { stockDetails } from "@/lib/mock-data";
import { loadStockInsights } from "@/lib/providers";
import { getMockStockDetailData } from "@/lib/queries";
import { masterVolatility, toRiskFlags, toRiskGrade } from "@/lib/mappers";
import { getSupabaseClient } from "@/lib/supabase";
import type { StockDetail } from "@/lib/types";

// GitHub Actions가 매일 적재한 뉴스가 재배포 없이 화면에 반영되도록 한다.
export const revalidate = 3600;

type MasterStock = Pick<StockDetail, "name" | "market" | "riskGrade" | "riskFlags" | "volatilityAnnual" | "volatilityPercentile" | "riskAsOf">;

const loadMasterStock = cache(async (code: string): Promise<MasterStock | null> => {
  const client = getSupabaseClient();
  if (!client || !/^[0-9A-Z]{6}$/.test(code)) return null;
  const { data } = await client
    .from("stocks")
    .select("code,name,market,risk_grade,risk_flags,volatility_annual,volatility_percentile,risk_as_of")
    .eq("code", code)
    .eq("is_active", true)
    .maybeSingle();
  if (!data) return null;
  return {
    name: data.name, market: data.market, riskGrade: toRiskGrade(data.risk_grade), riskFlags: toRiskFlags(data.risk_flags),
    ...masterVolatility(data),
  };
});

function masterOnlyDetail(code: string, stock: MasterStock): StockDetail {
  return {
    code, ...stock, signalLight: "neutral", rankPercentile: 0,
    returnBand: { low: 0, high: 0, ciLevel: 0.68 }, hitRate: 0, similarCaseCount: 0,
    horizonAgreement: { h5: "flat", h10: "flat", h20: "flat", agreement: "mixed" },
    provenance: { kind: "real", source: "KRX 종목 정보" }, asOf: "", reasons: [],
  };
}

export function generateStaticParams() {
  return Object.keys(stockDetails).map((code) => ({ code }));
}

export async function generateMetadata({ params }: PageProps<"/stocks/[code]">): Promise<Metadata> {
  const { code } = await params;
  const name = (await loadMasterStock(code))?.name ?? stockDetails[code]?.name;
  return name ? { title: `${name} ${code}`, description: `${name}의 뉴스 분위기, 재무, 차트 신호를 근거와 함께 쉽게 보여 드려요.` } : {};
}

export default async function StockDetailPage({ params }: PageProps<"/stocks/[code]">) {
  const { code } = await params;
  const [master, insights] = await Promise.all([loadMasterStock(code), loadStockInsights(code)]);
  const masterOnly = master && !stockDetails[code];
  const data = getMockStockDetailData(code, masterOnly ? masterOnlyDetail(code, master) : undefined);
  if (!data) notFound();

  const initialData = {
    ...data,
    detail: { ...data.detail, ...master },
    styleAxes: masterOnly ? null : data.styleAxes,
    holdings: masterOnly ? [] : data.holdings,
  };
  return <StockDetailBoundary code={code} initialData={initialData} insights={insights} />;
}
