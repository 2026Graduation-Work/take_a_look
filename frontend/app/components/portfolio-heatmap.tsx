import Link from "next/link";
import { SIGNAL_META } from "@/lib/display";
import type { DataProvenance, PortfolioHolding } from "@/lib/types";
import SourceChip from "./source-chip";

interface WeightedHolding {
  holding: PortfolioHolding;
  amount: number;
}

function splitIntoColumns(holdings: PortfolioHolding[]): WeightedHolding[][] {
  const columns: WeightedHolding[][] = [[], []];
  const totals = [0, 0];
  const weighted = holdings
    .map((holding) => ({
      holding,
      amount: Math.max(holding.quantity * holding.avgBuyPrice, 1),
    }))
    .sort(
      (left, right) =>
        right.amount - left.amount || left.holding.code.localeCompare(right.holding.code),
    );

  for (const item of weighted) {
    const columnIndex = totals[0] <= totals[1] ? 0 : 1;
    columns[columnIndex].push(item);
    totals[columnIndex] += item.amount;
  }

  return columns.filter((column) => column.length > 0);
}

// 평가금액(수량 × 최신 종가). 종가가 없는 종목은 상위에서 매입금액(수량 × 평균 매입가)으로 채워 넘긴다.
function amountLabel(holding: PortfolioHolding): string {
  return holding.priceBasis === "close" ? "평가금액" : "매입금액";
}

function formatAmount(amount: number): string {
  return `${Math.round(amount / 10_000).toLocaleString("ko-KR")}만원`;
}

export default function PortfolioHeatmap({
  holdings,
  withoutSignalCount = 0,
  emptyAction,
}: {
  holdings: PortfolioHolding[];
  withoutSignalCount?: number;
  emptyAction?: React.ReactNode;
}) {
  const columns = splitIntoColumns(holdings);
  const closeAsOf = holdings.map(({ priceAsOf }) => priceAsOf ?? "").sort().at(-1);
  const columnTotals = columns.map((column) =>
    column.reduce((sum, item) => sum + item.amount, 0),
  );
  // 한 종목이라도 예시면 맵 전체를 예시로 표시한다.
  const provenance: DataProvenance | null =
    holdings.length === 0
      ? null
      : holdings.every(({ provenance: { kind } }) => kind === "real")
        ? holdings[0].provenance
        : { kind: "mock", source: "" };

  if (holdings.length === 0) {
    return (
      <div className="surface flex min-h-[280px] flex-col items-center justify-center gap-4 px-6 text-center">
        <p className="m-0 flex flex-col gap-1">
          <span className="text-base font-medium text-ink">관심 가는 종목을 검색해 보세요</span>
          <span className="text-xs text-muted">위 검색창에 종목명을 넣거나, 가진 종목을 넣으면 여기에 오늘 신호가 보여요.</span>
        </p>
        {emptyAction ?? (
          <Link href="/portfolio" className="btn-primary">
            보유 종목 추가
          </Link>
        )}
      </div>
    );
  }

  return (
    <div className="surface flex flex-col gap-3 p-4">
      <div
        role="list"
        aria-label="보유 종목별 오늘 모델 신호"
        className="flex h-[280px] min-w-0 gap-1 overflow-hidden"
      >
        {columns.map((column, columnIndex) => (
          <div
            key={column.map(({ holding }) => holding.code).join("-")}
            className="flex min-w-0 flex-col gap-1"
            style={{ flexGrow: columnTotals[columnIndex], flexBasis: 0 }}
          >
            {column.map(({ holding, amount }) => {
              const signal = SIGNAL_META[holding.signalLight];
              return (
                <Link
                  key={holding.code}
                  role="listitem"
                  href={`/stocks/${holding.code}`}
                  title={`${holding.name}, ${holding.quantity}주, ${amountLabel(holding)} ${formatAmount(amount)}, ${signal.label} 신호`}
                  className="flex min-h-0 min-w-0 flex-col justify-between overflow-hidden rounded-md px-3 py-2.5 text-white hover:text-white hover:no-underline hover:brightness-110"
                  style={{ flexGrow: amount, flexBasis: 0, backgroundColor: signal.solid }}
                >
                  <span className="truncate text-base font-semibold">{holding.name}</span>
                  <span className="truncate text-sm font-medium">{signal.label}</span>
                </Link>
              );
            })}
          </div>
        ))}
      </div>
      <p className="flex flex-wrap items-center gap-x-3 gap-y-1 text-2xs text-muted">
        <span>
          색은 오늘 모델 신호(적 긍정 · 회색 중립 · 청 부정), 넓이는 평가금액 기준
          {closeAsOf && `(${closeAsOf.replaceAll("-", ".")} 종가)`}
          {holdings.some(({ priceBasis }) => priceBasis !== "close") && " · 종가가 없는 종목은 매입금액 기준"}
        </span>
        {provenance && <SourceChip provenance={provenance} />}
      </p>
      {withoutSignalCount > 0 && (
        <p className="text-2xs text-muted">
          등록한 종목 중 {withoutSignalCount}개는 오늘 모델 신호가 없어 맵에 넣지 않았어요.
        </p>
      )}
    </div>
  );
}
