"use client";

import { CHART } from "@/lib/chart-colors";
import { useEffect, useRef, useState } from "react";
import { changeMeta, formatKstDateTime, formatSignedPercent, type SignalMeta } from "@/lib/display";
import type { ReturnBand } from "@/lib/types";

const MIN_WIDTH = 560;
const HEIGHT = 264;
const PAD = { top: 20, bottom: 34 };
const X0 = 14;

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
  const [hoverIndex, setHovered] = useState<number | null>(null);
  const hovered = hoverIndex !== null && hoverIndex < prices.length ? hoverIndex : null;
  const [width, setWidth] = useState(MIN_WIDTH);
  const hasPrices = prices.length >= 2 && prices.every(Number.isFinite);

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

  if (!hasPrices) return null;

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
        return <button
          type="button"
          key={marker.date}
          aria-label={`차트에서 ${formatKstDateTime(marker.date)} ${formatSignedPercent(marker.changePercent, 2)} 선택`}
          aria-pressed={priceEvents.selectedDate === marker.date}
          onClick={(event) => {
            const rect = svgRef.current?.getBoundingClientRect();
            if (!event.detail || !rect) {
              priceEvents.select(marker.date);
              return;
            }
            // Adjacent 44px targets can overlap, so pointer clicks select the nearest visible point.
            const x = event.clientX - rect.left;
            const y = event.clientY - rect.top;
            const distance = (point: typeof marker) => (point.x - x) ** 2 + (point.y - y) ** 2;
            const closest = markers.reduce((best, point) => distance(point) < distance(best) ? point : best, marker);
            priceEvents.select(closest.date);
          }}
          className="group absolute z-10 grid size-11 -translate-x-1/2 -translate-y-1/2 place-items-center rounded-full"
          style={{ left, top: marker.y }}
        >
          <span className="size-3.5 rounded-full border-2 border-ink bg-surface shadow-sm group-aria-pressed:bg-ink"
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
    </div>
  );
}
