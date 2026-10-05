import { notFound } from "next/navigation";
import Link from "next/link";
import { NewsSentimentPanel } from "@/app/components/insight-cards";
import StockDetailBoundary from "@/app/components/stock-detail-boundary";
import { stockDetails } from "@/lib/mock-data";
import { loadStockInsights } from "@/lib/providers";
import { getMockStockDetailData } from "@/lib/queries";

// GitHub Actions가 매일 적재한 뉴스가 재배포 없이 화면에 반영되도록 한다.
export const revalidate = 3600;

const NEWS_ONLY_STOCKS: Record<string, { name: string; market: "KOSPI" | "KOSDAQ" }> = {
  "035420": { name: "네이버", market: "KOSPI" },
  "247540": { name: "에코프로비엠", market: "KOSDAQ" },
};

export function generateStaticParams() {
  return [...Object.keys(stockDetails), ...Object.keys(NEWS_ONLY_STOCKS)].map((code) => ({ code }));
}

export default async function StockDetailPage({ params }: PageProps<"/stocks/[code]">) {
  const { code } = await params;
  const initialData = getMockStockDetailData(code);
  const insights = await loadStockInsights(code);
  if (!initialData) {
    const stock = NEWS_ONLY_STOCKS[code];
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
