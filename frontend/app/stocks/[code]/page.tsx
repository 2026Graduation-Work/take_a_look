import StockDetailBoundary from "@/app/components/stock-detail-boundary";

export default async function StockDetailPage({ params }: PageProps<"/stocks/[code]">) {
  const { code } = await params;
  return <StockDetailBoundary code={code} />;
}
