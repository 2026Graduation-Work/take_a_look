"use client";

import { CHART } from "@/lib/chart-colors";
import { useRef, useState } from "react";
import type { SignalMeta } from "@/lib/display";
import type { ReturnBand } from "@/lib/types";

// 최근 60거래일 실제 주가 실선. 미래 영역에는 H10 시점의 수익률 분포 범위를
// 나타내는 세로 구간 하나만 둔다.
//
// 표현 규칙(미래 주가 곡선 금지)과의 경계:
// 오늘 종가와 범위 양 끝을 잇는 보조선 두 개는 둔다. 범위가 오늘 가격에서
// 나온 값임을 보여 줄 뿐 경로를 그리지 않기 때문이다. 대신 두 선 사이를
// 채우지는 않는다 — 채우면 "가격이 이 안을 지나간다"는 부채꼴이 되어
// 모델이 하지 않는 경로 예측을 암시한다.

const VB_W = 860;
const VB_H = 264;
const PAD = { top: 20, bottom: 34 };
const X0 = 14; // 실선 시작
const X1 = 668; // 실선 끝 = 오늘
const XH = 780; // H10 세로 구간 중심

function formatSigned(value: number) {
  return `${value > 0 ? "+" : ""}${value.toFixed(1)}%`;
}

// 눈금 간격을 1/2/2.5/5 × 10^n 으로 스냅
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
  asOfLabel: string; // 예: 07.07
  horizonLabel: string; // 예: 2주 뒤
}

export default function PriceHistoryChart({
  prices,
  band,
  signal,
  asOfLabel,
  horizonLabel,
}: PriceHistoryChartProps) {
  const svgRef = useRef<SVGSVGElement>(null);
  const [hovered, setHovered] = useState<number | null>(null);

  if (
    prices.length < 2 ||
    prices.some((price) => !Number.isFinite(price)) ||
    (band && (!Number.isFinite(band.low) || !Number.isFinite(band.high) || band.low > band.high))
  ) {
    return null;
  }

  const last = prices[prices.length - 1];
  const bandHighPrice = band ? last * (1 + band.high / 100) : last;
  const bandLowPrice = band ? last * (1 + band.low / 100) : last;
  const rawMin = Math.min(...prices, bandLowPrice);
  const rawMax = Math.max(...prices, bandHighPrice);
  const rawRange = rawMax - rawMin;
  const padValue = rawRange > 0 ? rawRange * 0.08 : Math.max(Math.abs(rawMax) * 0.01, 1);
  const vMin = rawMin - padValue;
  const vMax = rawMax + padValue;

  const plotH = VB_H - PAD.top - PAD.bottom;
  const baseline = PAD.top + plotH;
  const y = (v: number) => PAD.top + ((vMax - v) / (vMax - vMin)) * plotH;
  const xAt = (i: number) => X0 + (i / (prices.length - 1)) * (X1 - X0);

  const step = niceStep(rawRange / 3);
  const ticks: number[] = [];
  for (let v = Math.ceil(vMin / step) * step; v <= vMax; v += step) ticks.push(v);

  const points = prices.map((p, i) => `${xAt(i).toFixed(1)},${y(p).toFixed(1)}`).join(" ");
  const yHigh = y(bandHighPrice);
  const yLow = y(bandLowPrice);

  const handleMove = (event: React.MouseEvent<SVGSVGElement>) => {
    const rect = svgRef.current?.getBoundingClientRect();
    if (!rect) return;
    const vx = ((event.clientX - rect.left) / rect.width) * VB_W;
    if (vx < X0 || vx > X1 + 20) {
      setHovered(null);
      return;
    }
    const index = Math.round(((vx - X0) / (X1 - X0)) * (prices.length - 1));
    setHovered(Math.max(0, Math.min(prices.length - 1, index)));
  };

  return (
    <div className="relative">
      <svg
        ref={svgRef}
        viewBox={`0 0 ${VB_W} ${VB_H}`}
        className="block w-full"
        role="img"
        aria-label={`최근 60거래일 주가 흐름. ${band ? `${horizonLabel} 수익률 범위 ${formatSigned(band.low)}부터 ${formatSigned(band.high)}까지` : "수익률 범위 미제공"}`}
        onMouseMove={handleMove}
        onMouseLeave={() => setHovered(null)}
      >
        {/* 수평 그리드 + 가격 라벨 */}
        {ticks.map((tick) => (
          <g key={tick}>
            <line x1={X0} y1={y(tick)} x2={VB_W - 10} y2={y(tick)} style={{ stroke: "var(--color-line-soft)" }} />
            <text x={X0 + 4} y={y(tick) - 5} fontSize={11} style={{ fill: "var(--color-muted)" }}>
              {tick.toLocaleString("ko-KR")}
            </text>
          </g>
        ))}

        {/* 오늘 경계선 — 오른쪽 미래 영역에는 H10 세로 구간 외에 아무것도 그리지 않는다 */}
        <line x1={X1} y1={PAD.top} x2={X1} y2={baseline} style={{ stroke: "var(--color-line)" }} />
        <text x={X0} y={baseline + 17} fontSize={11} style={{ fill: "var(--color-muted)" }}>
          3개월 전
        </text>
        <text x={X1} y={baseline + 17} fontSize={11} style={{ fill: "var(--color-muted)" }} textAnchor="end">
          오늘 ({asOfLabel})
        </text>

        {/* 실제 주가 실선 */}
        <polyline
          points={points}
          fill="none"
          style={{ stroke: CHART.priceLine }}
          strokeWidth={2}
          strokeLinejoin="round"
        />
        <circle cx={X1} cy={y(last)} r={4} style={{ fill: CHART.priceLine }} stroke="#ffffff" strokeWidth={1.5} />

        {/* 오늘 종가 → H10 범위 양 끝 보조선. 가늘고 점선이라 경로가 아니라
            "여기서 나온 값"이라는 연결 표시로 읽힌다. 사이는 채우지 않는다. */}
        {band && <>
        <g style={{ stroke: signal.ink }} strokeWidth={1} strokeDasharray="3 4" opacity={0.45}>
          <line x1={X1} y1={y(last)} x2={XH - 11} y2={yHigh} />
          <line x1={X1} y1={y(last)} x2={XH - 11} y2={yLow} />
        </g>

        {/* H10 세로 구간: 분포 범위(경로 아님)를 캡슐 하나로 */}
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
          fontSize={12}
          fontWeight={600}
          style={{ fill: signal.ink }}
          textAnchor="middle"
        >
          {formatSigned(band.high)}
        </text>
        <text
          x={XH}
          y={yLow + 17}
          fontSize={12}
          fontWeight={600}
          style={{ fill: signal.ink }}
          textAnchor="middle"
        >
          {formatSigned(band.low)}
        </text>
        <text x={XH} y={baseline + 17} fontSize={11} style={{ fill: "var(--color-muted)" }} textAnchor="middle">
          {horizonLabel}
        </text>
        </>}

        {/* 호버 크로스헤어 */}
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

      {hovered !== null && (
        <div
          className="pointer-events-none absolute z-10 -translate-x-1/2 -translate-y-full whitespace-nowrap surface px-2.5 py-1.5 shadow-lift"
          style={{
            left: `${(xAt(hovered) / VB_W) * 100}%`,
            top: `${((y(prices[hovered]) - 10) / VB_H) * 100}%`,
          }}
        >
          <span className="text-xs text-muted">
            {hovered === prices.length - 1 ? "오늘" : `${prices.length - 1 - hovered}거래일 전`}
          </span>
          <span className="ml-1.5 text-xs font-medium tabular-nums">
            {prices[hovered].toLocaleString("ko-KR")}원
          </span>
        </div>
      )}
    </div>
  );
}
