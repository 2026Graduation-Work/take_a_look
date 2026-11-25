"use client";

import Link from "next/link";
import { isChartPreview } from "@/lib/chart-preview-config";
import { usePublicCharts } from "@/lib/use-public-charts";
import { chartDirection } from "@/lib/chart-detail";
import { SIGNAL_META } from "@/lib/display";
import { DIRECTION_WORD, SIGNAL_WORD, topPercentLabel } from "@/lib/copy-glossary";
import type { RecommendedStock } from "@/lib/types";

export function oneLineReason(stock: RecommendedStock): string {
  if (stock.reason) return stock.reason;
  const { h5, h10, h20 } = stock.horizonAgreement;
  return h5 === h10 && h10 === h20
    ? `1주, 2주, 4주 뒤 모두 ${DIRECTION_WORD[h5]}으로 봤어요`
    : `1주 뒤 ${DIRECTION_WORD[h5]}, 4주 뒤 ${DIRECTION_WORD[h20]}`;
}

export default function StockRow({ stock, horizon = 20 }: { stock: RecommendedStock; horizon?: 5 | 20 }) {
  const preview = isChartPreview(stock.code);
  const { charts, loading, error } = usePublicCharts(preview ? [stock.code] : []);
  const chart = charts?.get(stock.code)?.get(horizon);
  const direction = chartDirection(chart);
  const signal = SIGNAL_META[preview ? direction === "up" ? "positive" : direction === "down" ? "negative" : "neutral" : stock.signalLight];
  return (
    <Link
      href={`/stocks/${stock.code}`}
      data-stock-row={stock.code}
      className="flex items-center gap-4 px-5 py-4 text-ink transition-colors hover:bg-field hover:text-ink hover:no-underline"
    >
      <div className="flex min-w-0 flex-1 flex-col gap-1">
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
        <span className="truncate text-xs text-muted">{preview
          ? loading ? "최신 게시 결과를 불러오는 중이에요." : error ? "연결을 확인하지 못했어요. 상세에서 다시 시도해 주세요."
            : chart ? `${horizon === 5 ? "1주" : "4주"}, ${chart.data_asof.slice(5, 10).replace("-", ".")}` : "게시된 예측 결과가 아직 없어요."
          : oneLineReason(stock)}</span>
      </div>
      <div className="flex flex-none flex-col items-end gap-1">
        <span className="text-sm font-semibold" style={{ color: signal.ink }}>
          {preview ? direction ? SIGNAL_WORD[direction] : "신호 미제공" : signal.label}
        </span>
        {!preview && <span className="text-2xs text-muted tabular-nums">{topPercentLabel(stock.rankPercentile)}</span>}
      </div>
      <span className="size-2 flex-none rotate-45 border-r-[1.5px] border-t-[1.5px] border-ghost" aria-hidden />
    </Link>
  );
}
