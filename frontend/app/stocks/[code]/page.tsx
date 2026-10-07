import { notFound } from "next/navigation";
import Link from "next/link";
import { NewsSentimentPanel } from "@/app/components/insight-cards";
import StockDetailBoundary from "@/app/components/stock-detail-boundary";
import { stockDetails } from "@/lib/mock-data";
import { loadPublicCharts } from "@/lib/chart-public";
import { loadStockInsights } from "@/lib/providers";
import { getMockStockDetailData } from "@/lib/queries";
import { toRiskFlags, toRiskGrade } from "@/lib/mappers";
import { getSupabaseClient } from "@/lib/supabase";
import type { StockDetail } from "@/lib/types";

// GitHub Actions가 매일 적재한 뉴스가 재배포 없이 화면에 반영되도록 한다.
export const revalidate = 3600;

// 데모 예시가 없는 종목은 종목 마스터(stocks, 차트 서빙 universe로 매일 갱신)에서 찾는다.
// 게시된 차트 스냅샷이 있으면 다른 종목과 같은 상세 화면, 없으면 뉴스만 보인다.
type MasterStock = Pick<StockDetail, "name" | "market" | "riskGrade" | "riskFlags">;

async function loadMasterStock(code: string): Promise<MasterStock | null> {
  const client = getSupabaseClient();
  if (!client || !/^[0-9A-Z]{6}$/.test(code)) return null;
  const { data } = await client
    .from("stocks")
    .select("name,market,risk_grade,risk_flags")
    .eq("code", code)
    .eq("is_active", true)
    .maybeSingle();
  if (!data) return null;
  return { name: data.name, market: data.market, riskGrade: toRiskGrade(data.risk_grade), riskFlags: toRiskFlags(data.risk_flags) };
}

// 예측·시세 칸은 ChartPreviewDetail이 스냅샷 값으로 덮는다(chartDetail).
function chartOnlyDetail(code: string, stock: MasterStock): StockDetail {
  return {
    code, ...stock, signalLight: "neutral", rankPercentile: 0,
    returnBand: { low: 0, high: 0, ciLevel: 0.68 }, hitRate: 0, similarCaseCount: 0,
    horizonAgreement: { h5: "flat", h10: "flat", h20: "flat", agreement: "mixed" },
    provenance: { kind: "real", source: "LGBM · 20거래일 · 검증 전" }, asOf: "", reasons: [],
  };
}

export function generateStaticParams() {
  return Object.keys(stockDetails).map((code) => ({ code }));
}

export default async function StockDetailPage({ params }: PageProps<"/stocks/[code]">) {
  const { code } = await params;
  const stock = stockDetails[code] ? null : await loadMasterStock(code);
  const [insights, charts] = await Promise.all([
    loadStockInsights(code),
    stock ? loadPublicCharts([code]).catch(() => null) : null,
  ]);
  const initialData = getMockStockDetailData(code, stock && charts?.has(code) ? chartOnlyDetail(code, stock) : undefined);
  if (!initialData) {
    if (!stock) notFound();
    return (
      <main className="mx-auto flex w-full max-w-[960px] flex-col gap-6 px-4 pb-12 pt-5 sm:px-8">
        <Link href="/" className="btn-text self-start text-xs">‹ 대시보드</Link>
        <section className="surface flex flex-col gap-4 p-6">
          <div>
            <span className="eyebrow tabular-nums">{code} · {stock.market}</span>
            <h1 className="mt-1 text-3xl font-semibold">{stock.name}</h1>
            <p className="m-0 mt-2 text-sm text-body">
              예측·시세 스냅샷은 아직 연결되지 않았어요. 현재 수집된 뉴스 분위기만 보여 드려요.
            </p>
          </div>
          <NewsSentimentPanel insights={insights} />
        </section>
      </main>
    );
  }

  return <StockDetailBoundary code={code} initialData={initialData} insights={insights} />;
}
