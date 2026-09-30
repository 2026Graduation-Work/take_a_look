import Link from "next/link";
import { isChartPreview } from "@/lib/chart-preview-config";
import { PreviewStockRow } from "./chart-preview";
import { SIGNAL_META } from "@/lib/display";
import { DIRECTION_WORD, topPercentLabel } from "@/lib/copy-glossary";
import type { RecommendedStock } from "@/lib/types";

// 한 줄 이유. 모델 근거 문장이 있으면 그것을, 없으면 기간별 방향으로 만든 결정론 문장을 쓴다.
export function oneLineReason(stock: RecommendedStock): string {
  if (stock.reason) return stock.reason;
  const { h5, h10, h20 } = stock.horizonAgreement;
  return h5 === h10 && h10 === h20
    ? `1주·2주·4주 뒤 모두 ${DIRECTION_WORD[h5]}으로 봤어요`
    : `1주 뒤 ${DIRECTION_WORD[h5]}, 4주 뒤 ${DIRECTION_WORD[h20]}`;
}

// 주식 앱처럼 한 줄: 종목명 · 한 줄 이유 · 신호. 밴드·상승 비율·기간별 일치는 상세로 보낸다.
export default function StockRow({ stock }: { stock: RecommendedStock }) {
  if (isChartPreview(stock.code)) return <PreviewStockRow code={stock.code} name={stock.name} />;
  const signal = SIGNAL_META[stock.signalLight];
  return (
    <Link
      href={`/stocks/${stock.code}`}
      data-stock-row={stock.code}
      className="flex items-center gap-4 px-5 py-4 text-ink transition-colors hover:bg-field hover:text-ink hover:no-underline"
    >
      <div className="flex min-w-0 flex-1 flex-col gap-0.5">
        <span className="flex items-baseline gap-2">
          <span className="truncate text-base font-medium">{stock.name}</span>
          <span className="flex-none text-xs text-muted tabular-nums">{stock.code}</span>
          {stock.caution && (
            <span className="inline-flex flex-none items-center gap-1 text-xs text-body">
              <span className="size-1.5 rounded-full bg-caution-mark" aria-hidden />
              위험도 높음
            </span>
          )}
        </span>
        <span className="truncate text-xs text-muted">{oneLineReason(stock)}</span>
      </div>
      <div className="flex flex-none flex-col items-end gap-0.5">
        <span className="text-sm font-semibold" style={{ color: signal.ink }}>
          {signal.label}
        </span>
        <span className="text-2xs text-muted tabular-nums">{topPercentLabel(stock.rankPercentile)}</span>
      </div>
      <span className="size-2 flex-none rotate-45 border-r-[1.5px] border-t-[1.5px] border-ghost" aria-hidden />
    </Link>
  );
}
