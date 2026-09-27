import { notFound } from "next/navigation";
import StockDetailBoundary from "@/app/components/stock-detail-boundary";
import { stockDetails } from "@/lib/mock-data";
import { loadStockInsights } from "@/lib/providers";
import { getMockStockDetailData } from "@/lib/queries";

export function generateStaticParams() {
  return Object.keys(stockDetails).map((code) => ({ code }));
}

export default async function StockDetailPage({ params }: PageProps<"/stocks/[code]">) {
  const { code } = await params;
  const initialData = getMockStockDetailData(code);
  if (!initialData) notFound();
  const insights = await loadStockInsights(code);

  return <StockDetailBoundary code={code} initialData={initialData} insights={insights} />;
}
