"use client";

import { CHART } from "@/lib/chart-colors";
import { useCallback, useEffect, useId, useLayoutEffect, useRef, useState, type PointerEvent, type ReactNode, type RefObject } from "react";
import { createPortal } from "react-dom";
import { changeMeta, formatKstDateTime, formatSignedPercent, type SignalMeta } from "@/lib/display";
import type { ReturnBand } from "@/lib/types";

const MIN_WIDTH = 560;
const HEIGHT = 264;
const PAD = { top: 20, bottom: 34 };
const X0 = 14;
const POPUP_MARGIN = 16;
const POPUP_WIDTH = 320;
const POPUP_GAP = 24;

type ActiveMarker = {
  date: string;
  anchor: HTMLButtonElement;
  openedBy: "hover" | "press";
};

function PriceEventPopup({
  id, marker, x, y, scroller, close, dismiss, cancelClose, scheduleClose, children,
}: {
  id: string;
  marker: ActiveMarker;
  x: number;
  y: number;
  scroller: RefObject<HTMLDivElement | null>;
  close: () => void;
  dismiss: (date: string) => void;
  cancelClose: () => void;
  scheduleClose: () => void;
  children: ReactNode;
}) {
  const popup = useRef<HTMLDivElement>(null);

  useLayoutEffect(() => {
    const panel = popup.current!;
    const scrollArea = scroller.current!;
    const dot = marker.anchor.firstElementChild!;
    const place = () => {
      const point = dot.getBoundingClientRect();
      const bounds = scrollArea.getBoundingClientRect();
      const centerX = point.left + point.width / 2;
      const centerY = point.top + point.height / 2;
      if (centerX < Math.max(0, bounds.left) || centerX > Math.min(innerWidth, bounds.right) ||
          centerY < 0 || centerY > innerHeight) {
        close();
        return;
      }

      const width = Math.min(POPUP_WIDTH, innerWidth - 2 * POPUP_MARGIN);
      const left = Math.max(POPUP_MARGIN, Math.min(centerX - width / 2, innerWidth - width - POPUP_MARGIN));
      const above = centerY - POPUP_GAP - POPUP_MARGIN;
      const below = innerHeight - centerY - POPUP_GAP - POPUP_MARGIN;
      const heightLimit = innerHeight / 2;
      const placeAbove = above >= Math.min(panel.scrollHeight, heightLimit) || above >= below;
      panel.style.left = `${left}px`;
      panel.style.top = placeAbove ? "auto" : `${centerY + POPUP_GAP}px`;
      panel.style.bottom = placeAbove ? `${innerHeight - centerY + POPUP_GAP}px` : "auto";
      panel.style.maxHeight = `${Math.max(0, Math.min(heightLimit, placeAbove ? above : below))}px`;
    };
    const outside = (event: globalThis.PointerEvent) => {
      // Touch hit adjustment can target the scrollable popup from outside its bounds.
      const target = event.pointerType === "touch" ? document.elementFromPoint(event.clientX, event.clientY) : event.target;
      if (target instanceof Node && !panel.contains(target) && !marker.anchor.contains(target)) close();
    };
    const escape = (event: KeyboardEvent) => {
      if (event.key !== "Escape" || event.defaultPrevented) return;
      event.preventDefault();
      dismiss(marker.date);
      marker.anchor.focus({ preventScroll: true });
    };
    place();
    const observer = new ResizeObserver(place);
    observer.observe(panel.firstElementChild!);
    observer.observe(scrollArea);
    window.addEventListener("resize", place);
    window.addEventListener("scroll", place, true);
    document.addEventListener("pointerdown", outside);
    document.addEventListener("keydown", escape);
    return () => {
      observer.disconnect();
      window.removeEventListener("resize", place);
      window.removeEventListener("scroll", place, true);
      document.removeEventListener("pointerdown", outside);
      document.removeEventListener("keydown", escape);
    };
  }, [close, dismiss, marker, scroller, x, y]);

  useLayoutEffect(() => {
    if (marker.openedBy === "press") popup.current?.focus({ preventScroll: true });
  }, [marker]);

  return createPortal(
    <div
      ref={popup}
      id={id}
      role="dialog"
      aria-label="가격이 크게 움직인 날"
      tabIndex={-1}
      onPointerEnter={cancelClose}
      onPointerLeave={(event) => {
        if (event.pointerType === "mouse" && !event.currentTarget.contains(document.activeElement)) scheduleClose();
      }}
      className="fixed z-50 w-[min(320px,calc(100vw-32px))] overflow-auto overscroll-contain rounded-md bg-surface p-4 shadow-lift"
    >
      {children}
    </div>,
    document.body,
  );
}

function niceStep(rough: number) {
  if (!Number.isFinite(rough) || rough <= 0) return 1;
  const power = 10 ** Math.floor(Math.log10(rough));
  const unit = rough / power;
  if (unit <= 1) return power;
  if (unit <= 2) return 2 * power;
  if (unit <= 2.5) return 2.5 * power;
  if (unit <= 5) return 5 * power;
  return 10 * power;
}

interface PriceHistoryChartProps {
  prices: number[];
  band?: ReturnBand;
  signal: SignalMeta;
  horizonLabel: string;
  asOfLabel: string;
  avgBuyPrice?: number;
  priceEvents?: {
    dates: string[];
    moves: { date: string; changePercent: number }[];
    selectedDate?: string;
    select: (date: string) => void;
    content: ReactNode;
    emptyStatus?: ReactNode;
  };
}

export default function PriceHistoryChart({
  prices,
  band,
  signal,
  horizonLabel,
  asOfLabel,
  avgBuyPrice,
  priceEvents,
}: PriceHistoryChartProps) {
  const svgRef = useRef<SVGSVGElement>(null);
  const scrollRef = useRef<HTMLDivElement>(null);
  const popupId = useId();
  const markerButtons = useRef(new Map<string, HTMLButtonElement>());
  const dismissedHoverDate = useRef<string | undefined>(undefined);
  const closeTimer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  const [activeMarker, setActiveMarker] = useState<ActiveMarker | null>(null);
  const [hoverIndex, setHovered] = useState<number | null>(null);
  const hovered = hoverIndex !== null && hoverIndex < prices.length ? hoverIndex : null;
  const [width, setWidth] = useState(MIN_WIDTH);
  const hasPrices = prices.length >= 2 && prices.every(Number.isFinite);
  if (activeMarker) {
    const index = priceEvents?.dates.indexOf(activeMarker.date) ?? -1;
    if (!hasPrices || index < 0 || index >= prices.length || !priceEvents?.moves.some(({ date }) => date === activeMarker.date)) {
      setActiveMarker(null);
    }
  }

  const cancelClose = useCallback(() => clearTimeout(closeTimer.current), []);
  const closePopup = useCallback(() => {
    cancelClose();
    setActiveMarker(null);
  }, [cancelClose]);
  const dismissPopup = useCallback((date: string) => {
    dismissedHoverDate.current = date;
    closePopup();
  }, [closePopup]);
  const scheduleClose = () => {
    if (activeMarker?.openedBy !== "hover") return;
    cancelClose();
    closeTimer.current = setTimeout(closePopup, 240);
  };
  useEffect(() => cancelClose, [cancelClose]);

  useEffect(() => {
    const svg = svgRef.current;
    if (!hasPrices || !svg) return;
    const observer = new ResizeObserver(([entry]) => {
      setWidth(Math.max(MIN_WIDTH, entry.contentRect.width));
    });
    observer.observe(svg);
    return () => observer.disconnect();
  }, [hasPrices]);

  useEffect(() => {
    const scroller = scrollRef.current;
    if (scroller) scroller.scrollLeft = scroller.scrollWidth;
  }, [prices]);

  if (!hasPrices) return priceEvents?.emptyStatus ?? null;

  const rangeBand = band && Number.isFinite(band.low) && Number.isFinite(band.high) && band.low <= band.high ? band : null;
  const X1 = width - (rangeBand ? 186 : 100);
  const XAXIS = X1 + 10;
  const XH = width - 60;
  const last = prices[prices.length - 1];
  const bandHighPrice = rangeBand ? last * (1 + rangeBand.high / 100) : last;
  const bandLowPrice = rangeBand ? last * (1 + rangeBand.low / 100) : last;
  const avg = avgBuyPrice && Number.isFinite(avgBuyPrice) && avgBuyPrice > 0 ? avgBuyPrice : null;
  const rawMin = Math.min(...prices, bandLowPrice, avg ?? Infinity);
  const rawMax = Math.max(...prices, bandHighPrice, avg ?? -Infinity);
  const rawRange = rawMax - rawMin;
  const padValue = rawRange > 0 ? rawRange * 0.08 : Math.max(Math.abs(rawMax) * 0.01, 1);
  const vMin = rawMin - padValue;
  const vMax = rawMax + padValue;

  const plotH = HEIGHT - PAD.top - PAD.bottom;
  const baseline = PAD.top + plotH;
  const y = (v: number) => PAD.top + ((vMax - v) / (vMax - vMin)) * plotH;
  const xAt = (i: number) => X0 + (i / (prices.length - 1)) * (X1 - X0);

  const step = niceStep(rawRange / 3);
  const ticks: number[] = [];
  for (let v = Math.ceil(vMin / step) * step; v <= vMax; v += step) ticks.push(v);

  const points = prices.map((p, i) => `${xAt(i).toFixed(1)},${y(p).toFixed(1)}`).join(" ");
  const maxIndex = prices.indexOf(Math.max(...prices));
  const minIndex = prices.indexOf(Math.min(...prices));
  const clampX = (x: number) => Math.min(Math.max(x, X0 + 40), X1 - 40);
  const yLast = y(last);
  const yHigh = y(bandHighPrice);
  const yLow = y(bandLowPrice);
  const markers = priceEvents?.moves.flatMap((move) => {
    const index = priceEvents.dates.indexOf(move.date);
    return index >= 0 && index < prices.length
      ? [{ ...move, x: xAt(index), y: y(prices[index]) }]
      : [];
  }) ?? [];
  const activePoint = markers.find(({ date }) => date === activeMarker?.date);
  const closestMarker = (clientX: number, clientY: number, fallback: typeof markers[number]) => {
    const rect = svgRef.current!.getBoundingClientRect();
    const bounds = scrollRef.current!.getBoundingClientRect();
    const distance = (point: typeof fallback) => (point.x + rect.left - clientX) ** 2 + (point.y + rect.top - clientY) ** 2;
    const visible = markers.filter(({ x }) => x + rect.left >= bounds.left && x + rect.left <= bounds.right);
    return visible.reduce((best, point) => distance(point) < distance(best) ? point : best, visible[0] ?? fallback);
  };
  const openPopup = (date: string, openedBy: ActiveMarker["openedBy"]) => {
    cancelClose();
    const anchor = markerButtons.current.get(date);
    if (!anchor || !priceEvents) return;
    if (activeMarker?.date === date) {
      if (openedBy === "hover") return;
      if (activeMarker.openedBy !== "hover") {
        closePopup();
        return;
      }
    }
    setHovered(null);
    priceEvents.select(date);
    setActiveMarker({ date, anchor, openedBy });
  };

  const handleMove = (event: React.MouseEvent<SVGSVGElement>) => {
    const vx = event.clientX - event.currentTarget.getBoundingClientRect().left;
    if (vx < X0 || vx > X1 + 20) {
      setHovered(null);
      return;
    }
    const index = Math.round(((vx - X0) / (X1 - X0)) * (prices.length - 1));
    setHovered(Math.max(0, Math.min(prices.length - 1, index)));
  };

  return (
    <div className="@container min-w-0">
    <div ref={scrollRef} role="region" aria-label="주가 차트 좌우 탐색" tabIndex={0} className="overflow-x-auto [scrollbar-width:thin]">
    <div className="relative min-w-[560px]">
      <svg
        ref={svgRef}
        height={HEIGHT}
        className="block w-full"
        role="img"
        aria-label="최근 주가 흐름"
        aria-describedby={rangeBand ? "overview-return-range" : undefined}
        onMouseMove={handleMove}
        onMouseLeave={() => setHovered(null)}
      >
        {ticks.map((tick) => (
          <g key={tick}>
            <line x1={X0} y1={y(tick)} x2={width - 10} y2={y(tick)} style={{ stroke: "var(--color-line-soft)" }} />
            {Math.abs(y(tick) - yLast) > 16 && (
              <text x={XAXIS} y={y(tick) + 4} fontSize={13} style={{ fill: "var(--color-muted)" }}>
                {tick.toLocaleString("ko-KR")}
              </text>
            )}
          </g>
        ))}

        <line x1={X1} y1={PAD.top} x2={X1} y2={baseline} style={{ stroke: "var(--color-line)" }} />
        <text x={X0} y={baseline + 17} fontSize={13} style={{ fill: "var(--color-muted)" }}>
          3개월 전
        </text>
        <text x={X1} y={baseline + 17} fontSize={13} style={{ fill: "var(--color-muted)" }} textAnchor="end">
          {asOfLabel || "최근 종가"}
        </text>

        {avg !== null && (
          <g data-avg-buy-price>
            <line x1={X0} y1={y(avg)} x2={X1} y2={y(avg)} style={{ stroke: CHART.ghost }} strokeWidth={1.5} />
            <text x={X0 + 4} y={y(avg) + (y(avg) - PAD.top < 16 ? 14 : -6)} fontSize={13} style={{ fill: "var(--color-body)" }}>
              평균 매입가 {Math.round(avg).toLocaleString("ko-KR")}원
            </text>
          </g>
        )}

        <polyline
          points={points}
          fill="none"
          style={{ stroke: CHART.priceLine }}
          strokeWidth={2}
          strokeLinejoin="round"
        />
        <circle cx={X1} cy={yLast} r={4} style={{ fill: CHART.priceLine }} stroke="#ffffff" strokeWidth={1.5} />
        <text x={XAXIS} y={yLast + 4} fontSize={14} fontWeight={600} style={{ fill: "var(--color-ink)" }}>
          {last.toLocaleString("ko-KR")}원
        </text>
        {maxIndex !== prices.length - 1 && (
          <text x={clampX(xAt(maxIndex))} y={y(prices[maxIndex]) - 8} fontSize={13} textAnchor="middle" style={{ fill: "var(--color-body)" }}>
            최고 {prices[maxIndex].toLocaleString("ko-KR")}원
          </text>
        )}
        {minIndex !== prices.length - 1 && (
          <text x={clampX(xAt(minIndex))} y={y(prices[minIndex]) + 16} fontSize={13} textAnchor="middle" style={{ fill: "var(--color-body)" }}>
            최저 {prices[minIndex].toLocaleString("ko-KR")}원
          </text>
        )}

        {rangeBand && (
          <g>
            <rect
              x={XH - 8}
              y={yHigh}
              width={16}
              height={yLow - yHigh}
              rx={8}
              style={{ fill: signal.ink }}
              opacity={0.16}
            />
            <line
              x1={XH - 11}
              y1={yHigh}
              x2={XH + 11}
              y2={yHigh}
              style={{ stroke: signal.ink }}
              strokeWidth={2.5}
              strokeLinecap="round"
            />
            <line
              x1={XH - 11}
              y1={yLow}
              x2={XH + 11}
              y2={yLow}
              style={{ stroke: signal.ink }}
              strokeWidth={2.5}
              strokeLinecap="round"
            />
            <line x1={XH} y1={yHigh + 3} x2={XH} y2={yLow - 3} style={{ stroke: signal.ink }} strokeWidth={1.5} />
            <text
              x={XH}
              y={yHigh - 9}
              fontSize={14}
              fontWeight={600}
              style={{ fill: changeMeta(rangeBand.high, 1).color }}
              textAnchor="middle"
            >
              {formatSignedPercent(rangeBand.high)}
            </text>
            <text
              x={XH}
              y={yLow + 17}
              fontSize={14}
              fontWeight={600}
              style={{ fill: changeMeta(rangeBand.low, 1).color }}
              textAnchor="middle"
            >
              {formatSignedPercent(rangeBand.low)}
            </text>
            <text x={XH} y={baseline + 17} fontSize={13} style={{ fill: "var(--color-muted)" }} textAnchor="middle">
              {horizonLabel}
            </text>
          </g>
        )}

        {hovered !== null && (
          <g pointerEvents="none">
            <line
              x1={xAt(hovered)}
              y1={PAD.top}
              x2={xAt(hovered)}
              y2={baseline}
              style={{ stroke: "var(--color-edge)" }}
              strokeWidth={1}
            />
            <circle
              cx={xAt(hovered)}
              cy={y(prices[hovered])}
              r={4.5}
              style={{ fill: CHART.priceLine }}
              stroke="#ffffff"
              strokeWidth={2}
            />
          </g>
        )}
      </svg>
      {priceEvents && markers.map((marker) => {
        const left = Math.max(22, marker.x);
        const expanded = activeMarker?.date === marker.date;
        const hoverMarker = (event: PointerEvent<HTMLButtonElement>) => {
          if (event.pointerType !== "mouse") return;
          const { date } = closestMarker(event.clientX, event.clientY, marker);
          if (date === dismissedHoverDate.current) return;
          dismissedHoverDate.current = undefined;
          openPopup(date, "hover");
        };
        return <button
          type="button"
          key={marker.date}
          ref={(button) => {
            if (button) markerButtons.current.set(marker.date, button);
            else markerButtons.current.delete(marker.date);
          }}
          data-price-event-marker
          aria-label={`차트에서 ${formatKstDateTime(marker.date)} ${formatSignedPercent(marker.changePercent, 2)} 선택`}
          aria-haspopup="dialog"
          aria-expanded={expanded}
          aria-controls={expanded ? popupId : undefined}
          onPointerEnter={(event) => {
            if (event.pointerType !== "mouse") return;
            const previous = event.relatedTarget;
            if (!(previous instanceof Element && previous.closest("[data-price-event-marker]"))) {
              dismissedHoverDate.current = undefined;
            }
            hoverMarker(event);
          }}
          onPointerMove={hoverMarker}
          onPointerLeave={(event) => {
            if (event.pointerType === "mouse") scheduleClose();
          }}
          onClick={(event) => {
            if (event.detail === 0) openPopup(marker.date, "press");
            else openPopup(closestMarker(event.clientX, event.clientY, marker).date, "press");
          }}
          className="group absolute z-10 grid size-11 -translate-x-1/2 -translate-y-1/2 place-items-center rounded-full"
          style={{ left, top: marker.y }}
        >
          <span className="size-3.5 rounded-full border-2 border-ink bg-surface shadow-sm group-aria-expanded:bg-ink"
            style={{ transform: `translateX(${marker.x - left}px)` }} aria-hidden />
        </button>;
      })}

      {hovered !== null && (
        <div
          className="pointer-events-none absolute z-10 -translate-x-1/2 -translate-y-full whitespace-nowrap surface px-3 py-2 shadow-lift"
          style={{
            left: xAt(hovered),
            top: y(prices[hovered]) - 10,
          }}
        >
          <span className="text-xs text-muted">
            {hovered === prices.length - 1 ? "최근 종가" : `${prices.length - 1 - hovered}거래일 전`}
          </span>
          <span className="ml-2 text-xs font-medium tabular-nums">
            {prices[hovered].toLocaleString("ko-KR")}원
          </span>
        </div>
      )}
    </div>
    </div>
    <p className="m-0 mt-2 text-2xs text-muted @min-[560px]:hidden">차트를 좌우로 밀면 지난 주가와 기준 가격을 볼 수 있어요.</p>
    {markers.length === 0 && priceEvents?.emptyStatus}
    {activeMarker && activePoint && activeMarker.date === priceEvents?.selectedDate && (
      <PriceEventPopup id={popupId} marker={activeMarker} x={activePoint.x} y={activePoint.y} scroller={scrollRef}
        close={closePopup} dismiss={dismissPopup} cancelClose={cancelClose} scheduleClose={scheduleClose}>
        {priceEvents.content}
      </PriceEventPopup>
    )}
    </div>
  );
}
