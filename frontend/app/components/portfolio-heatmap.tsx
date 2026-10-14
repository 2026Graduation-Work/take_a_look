"use client";

import { useEffect, useId, useRef, useState } from "react";
import Link from "next/link";
import { SIGNAL_META } from "@/lib/display";
import type { DataProvenance, PortfolioHolding } from "@/lib/types";
import DotLegend, { SIGNAL_LEGEND } from "./dot-legend";
import { staleLabel } from "@/lib/market-status";
import { DIRECTION_RULE, HORIZON_AHEAD } from "@/lib/copy-glossary";
import HeatmapPopup from "./portfolio-heatmap-popup";
import HeatmapLabel from "./portfolio-heatmap-label";

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
  const popupId = useId();
  const map = useRef<HTMLDivElement>(null);
  const pointerType = useRef("");
  const [active, setActive] = useState<{
    code: string;
    x: number;
    y: number;
    input: "pointer" | "keyboard" | "touch";
  } | null>(null);
  const isOpen = active !== null;
  useEffect(() => {
    if (!isOpen) return;
    const dismiss = () => setActive(null);
    const outside = (event: PointerEvent) => {
      const target = event.target as Node;
      if (!map.current?.contains(target) && !document.getElementById(popupId)?.contains(target)) dismiss();
    };
    const escape = (event: KeyboardEvent) => {
      if (event.key === "Escape") dismiss();
    };
    window.addEventListener("resize", dismiss);
    window.addEventListener("scroll", dismiss, true);
    document.addEventListener("pointerdown", outside);
    document.addEventListener("keydown", escape);
    return () => {
      window.removeEventListener("resize", dismiss);
      window.removeEventListener("scroll", dismiss, true);
      document.removeEventListener("pointerdown", outside);
      document.removeEventListener("keydown", escape);
    };
  }, [isOpen, popupId]);

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

  const grandTotal = columnTotals.reduce((sum, value) => sum + value, 0) || 1;
  const activeItem = columns.flat().find(({ holding }) => holding.code === active?.code);
  return (
    <div className="surface flex flex-col gap-4 p-4">
      <div
        ref={map}
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
                  aria-label={`${holding.name}, ${holding.quantity}주, ${amountLabel(holding)} ${formatAmount(amount)}, 비중 ${Math.round((amount / grandTotal) * 100)}%, ${HORIZON_AHEAD[20]} ${signal.label} 신호`}
                  aria-describedby={active?.code === holding.code ? popupId : undefined}
                  className="relative min-h-0 min-w-0 overflow-hidden rounded-md text-white hover:text-white hover:no-underline hover:brightness-110 focus-visible:-outline-offset-2"
                  style={{ flexGrow: amount, flexBasis: 0, backgroundColor: signal.solid }}
                  onPointerDown={(event) => { pointerType.current = event.pointerType; }}
                  onPointerEnter={(event) => {
                    if (event.pointerType === "touch") return;
                    setActive({ code: holding.code, x: event.clientX, y: event.clientY, input: "pointer" });
                  }}
                  onPointerMove={(event) => {
                    if (event.pointerType === "touch") return;
                    // Esc로 닫은 팝업은 칸에 다시 들어오기 전까지 열지 않는다.
                    setActive((current) => current?.code === holding.code && current.input === "pointer"
                      ? { ...current, x: event.clientX, y: event.clientY } : current);
                  }}
                  onPointerLeave={() => setActive((current) => current?.input === "pointer" ? null : current)}
                  onFocus={(event) => {
                    if (!event.currentTarget.matches(":focus-visible")) return;
                    const rect = event.currentTarget.getBoundingClientRect();
                    setActive({ code: holding.code, x: rect.right, y: rect.top, input: "keyboard" });
                  }}
                  onBlur={() => setActive((current) => current?.input === "keyboard" ? null : current)}
                  onClick={(event) => {
                    if (pointerType.current !== "touch" || event.detail === 0) return;
                    event.preventDefault();
                    setActive((current) => current?.code === holding.code && current.input === "touch" ? null
                      : { code: holding.code, x: event.clientX, y: event.clientY, input: "touch" });
                  }}
                >
                  <HeatmapLabel name={holding.name} signal={signal.label} weight={Math.round((amount / grandTotal) * 100)} />
                </Link>
              );
            })}
          </div>
        ))}
      </div>
      {active && activeItem && (
        <HeatmapPopup
          id={popupId}
          x={active.x}
          y={active.y}
          touch={active.input === "touch"}
          holding={activeItem.holding}
          amount={`${amountLabel(activeItem.holding)} ${formatAmount(activeItem.amount)}`}
          weight={Math.round((activeItem.amount / grandTotal) * 100)}
          onClose={() => setActive(null)}
        />
      )}
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-2xs text-muted">
        {/* 타일이 좁아 기간은 범례에 한 번(사전 참가자 P0 10/13). 읽기 프로그램은 타일 이름에서 듣는다 */}
        <span className="font-medium text-body">{HORIZON_AHEAD[20]} 방향</span>
        <DotLegend items={SIGNAL_LEGEND} />
        <span>
          넓이·비중은 내 보유 평가금액 기준
          {/* 기준일은 시장 바에 한 번. 종가가 2영업일 넘게 밀렸을 때만 적는다 */}
          {closeAsOf && staleLabel(closeAsOf) && `(${closeAsOf.replaceAll("-", ".")} 종가)`}
          {holdings.some(({ priceBasis }) => priceBasis !== "close") && " · 종가가 없는 종목은 매입금액 기준"}
          {provenance?.kind === "real" ? " · 모델 검증 전" : provenance && " · 예시 데이터"}
        </span>
      </div>
      {/* #278 QA: 상방·하방이 무슨 뜻인지 맵 바로 아래에서 한 줄로 */}
      <p className="m-0 text-2xs text-muted">{DIRECTION_RULE}</p>
      {withoutSignalCount > 0 && (
        <p className="text-2xs text-muted">
          등록한 종목 중 {withoutSignalCount}개는 오늘 모델 신호가 없어 맵에 넣지 않았어요.
        </p>
      )}
    </div>
  );
}
