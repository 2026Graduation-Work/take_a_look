"use client";

import { useEffect, useId, useRef, useState } from "react";
import Link from "next/link";
import { SIGNAL_META } from "@/lib/display";
import type { DataProvenance, PortfolioHolding } from "@/lib/types";
import DotLegend, { SIGNAL_LEGEND } from "./dot-legend";
import { staleLabel } from "@/lib/market-status";
import { DIRECTION_BASIS, HORIZON_AHEAD } from "@/lib/copy-glossary";
import HeatmapPopup from "./portfolio-heatmap-popup";
import HeatmapLabel from "./portfolio-heatmap-label";

interface WeightedHolding {
  holding: PortfolioHolding;
  amount: number;
}

type Tile = WeightedHolding | { others: WeightedHolding[]; amount: number };

// 모든 칸은 높이 44px 이상(이름이 늘 보이게, #326 후속). 280px 맵에 44px 칸 + 4px 간격은 한 열에 5개까지.
const MAX_PER_COLUMN = 5;

// 금액 큰 순으로 두 열에 나눈다. 다 들어가지 않으면 작은 종목들을 "그 밖의 N종목" 칸 하나로 묶는다.
function layoutTiles(holdings: PortfolioHolding[]): { columns: Tile[][]; all: WeightedHolding[] } {
  const all = holdings
    .map((holding) => ({
      holding,
      amount: Math.max(holding.quantity * holding.avgBuyPrice, 1),
    }))
    .sort(
      (left, right) =>
        right.amount - left.amount || left.holding.code.localeCompare(right.holding.code),
    );
  const capacity = MAX_PER_COLUMN * 2;
  const own = all.length > capacity ? all.slice(0, capacity - 1) : all;
  const rest = all.slice(own.length);
  const tiles: Tile[] = rest.length
    ? [...own, { others: rest, amount: rest.reduce((sum, item) => sum + item.amount, 0) }]
    : own;

  const columns: Tile[][] = [[], []];
  const totals = [0, 0];
  for (const tile of tiles) {
    const columnIndex = columns[1].length >= MAX_PER_COLUMN || (columns[0].length < MAX_PER_COLUMN && totals[0] <= totals[1]) ? 0 : 1;
    columns[columnIndex].push(tile);
    totals[columnIndex] += tile.amount;
  }

  return { columns: columns.filter((column) => column.length > 0), all };
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
  const othersId = useId();
  const [othersOpen, setOthersOpen] = useState(false);
  const map = useRef<HTMLDivElement>(null);
  const pointerType = useRef("");
  const [active, setActive] = useState<{
    code: string;
    x: number;
    y: number;
    input: "pointer" | "keyboard" | "touch";
  } | null>(null);
  const isOpen = active !== null;
  const popupInput = active?.input;
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
    const scroll = (event: Event) => {
      if (event.target instanceof Node && document.getElementById(popupId)?.contains(event.target)) return;
      // 터치 선택기의 기본 스크롤이나 팝업 내부 스크롤은 정보를 닫지 않는다.
      // 바깥에서 시작한 터치는 pointerdown에서 닫힌다.
      if (popupInput === "touch") return;
      dismiss();
    };
    window.addEventListener("resize", dismiss);
    window.addEventListener("scroll", scroll, true);
    document.addEventListener("pointerdown", outside);
    document.addEventListener("keydown", escape);
    return () => {
      window.removeEventListener("resize", dismiss);
      window.removeEventListener("scroll", scroll, true);
      document.removeEventListener("pointerdown", outside);
      document.removeEventListener("keydown", escape);
    };
  }, [isOpen, popupId, popupInput]);

  const { columns, all } = layoutTiles(holdings);
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
  const activeItem = all.find(({ holding }) => holding.code === active?.code);
  const others = columns.flat().find((tile) => "others" in tile);
  const weightOf = (amount: number) => Math.round((amount / grandTotal) * 100);
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
            key={columnIndex}
            className="flex min-w-0 flex-col gap-1"
            // 좁은 열에서도 이름이 몇 글자는 보이게(넓이는 정확한 비례가 아니다 — 범례에 적음)
            style={{ flexGrow: columnTotals[columnIndex], flexBasis: 0, minWidth: columns.length > 1 ? "30%" : undefined }}
          >
            {column.map((tile) => {
              if ("others" in tile) return (
                <div key="others" role="listitem" className="flex min-h-11 min-w-0" style={{ flexGrow: tile.amount, flexBasis: 0 }}>
                  <button
                    type="button"
                    aria-expanded={othersOpen}
                    aria-controls={othersId}
                    aria-label={`그 밖의 ${tile.others.length}종목, 비중 ${weightOf(tile.amount)}%. 누르면 목록이 열려요`}
                    className="relative w-full min-w-0 overflow-hidden rounded-md bg-field text-ink hover:brightness-95 focus-visible:-outline-offset-2"
                    onClick={() => setOthersOpen((open) => !open)}
                  >
                    <HeatmapLabel name={`그 밖의 ${tile.others.length}종목`} signal={othersOpen ? "목록 닫기" : "목록 보기"} weight={weightOf(tile.amount)} />
                  </button>
                </div>
              );
              const { holding, amount } = tile;
              const signal = SIGNAL_META[holding.signalLight];
              return (
                <Link
                  key={holding.code}
                  role="listitem"
                  href={`/stocks/${holding.code}`}
                  aria-label={`${holding.name}, ${holding.quantity}주, ${amountLabel(holding)} ${formatAmount(amount)}, 비중 ${Math.round((amount / grandTotal) * 100)}%, ${HORIZON_AHEAD[20]} ${signal.label} 신호`}
                  aria-describedby={active?.code === holding.code ? popupId : undefined}
                  className="relative min-h-11 min-w-0 overflow-hidden rounded-md text-white hover:text-white hover:no-underline hover:brightness-110 focus-visible:-outline-offset-2"
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
                  <HeatmapLabel name={holding.name} signal={signal.label} weight={weightOf(amount)} />
                </Link>
              );
            })}
          </div>
        ))}
      </div>
      <select
        aria-label="보유 종목 정보 선택"
        value=""
        className="hidden min-h-11 w-full min-w-0 rounded-sm bg-field px-3 text-sm text-ink [@media(any-pointer:coarse)]:block"
        onChange={(event) => {
          const rect = event.currentTarget.getBoundingClientRect();
          setActive({ code: event.currentTarget.value, x: rect.right, y: rect.top, input: "touch" });
        }}
      >
        <option value="" disabled>종목을 골라 정보 보기</option>
        {all.map(({ holding, amount }) => (
          <option key={holding.code} value={holding.code}>
            {holding.name}, 비중 {weightOf(amount)}%
          </option>
        ))}
      </select>
      {others && "others" in others && othersOpen && (
        <ul id={othersId} aria-label="그 밖의 보유 종목" className="group-list m-0 list-none p-0">
          {others.others.map(({ holding, amount }) => (
            <li key={holding.code}>
              <Link
                href={`/stocks/${holding.code}`}
                className="flex min-h-11 items-center gap-3 px-4 py-2 text-sm text-ink hover:bg-field hover:text-ink hover:no-underline"
              >
                <span className="min-w-0 flex-1 truncate font-medium">{holding.name}</span>
                <span className="flex-none text-xs font-semibold" style={{ color: SIGNAL_META[holding.signalLight].ink }}>
                  {SIGNAL_META[holding.signalLight].label}
                </span>
                <span className="flex-none text-xs text-muted tabular-nums">비중 {weightOf(amount)}%</span>
              </Link>
            </li>
          ))}
        </ul>
      )}
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
      {/* 색 범례와 방향 뜻을 한 줄로(기간은 이 문장에 한 번, 사전 참가자 P0 10/13). 읽기 프로그램은 타일 이름에서 듣는다 */}
      <p className="m-0 flex flex-wrap items-center gap-x-3 gap-y-1 text-2xs text-muted">
        <DotLegend items={SIGNAL_LEGEND} />
        <span>{DIRECTION_BASIS}</span>
      </p>
      <div className="text-2xs text-muted">
        <span>
          넓이·비중은 내 보유 평가금액 기준 · 작은 종목은 이름이 보이게 최소 크기로 그려요
          {/* 기준일은 시장 바에 한 번. 종가가 2영업일 넘게 밀렸을 때만 적는다 */}
          {closeAsOf && staleLabel(closeAsOf) && `(${closeAsOf.replaceAll("-", ".")} 종가)`}
          {holdings.some(({ priceBasis }) => priceBasis !== "close") && " · 종가가 없는 종목은 매입금액 기준"}
          {provenance?.kind === "real" ? " · 모델 검증 전" : provenance && " · 예시 데이터"}
        </span>
      </div>
      {withoutSignalCount > 0 && (
        <p className="text-2xs text-muted">
          등록한 종목 중 {withoutSignalCount}개는 오늘 모델 신호가 없어 맵에 넣지 않았어요.
        </p>
      )}
    </div>
  );
}
