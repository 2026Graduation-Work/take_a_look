"use client";

import { useState } from "react";
import type { SignalMeta } from "@/lib/display";
import type { ReturnBand, ReturnBin } from "@/lib/types";

// 과거 유사 신호 N건의 실현 수익률 분포. 부채꼴(미래 경로) 대신 쓰는 핵심 근거 시각화 —
// 예측 밴드(-2.0%~+7.4%)가 H10 시점의 "분포 범위"임을 그대로 보여준다.

const VB_W = 860;
const VB_H = 300;
const PAD = { top: 44, right: 14, bottom: 34, left: 40 };
const BAR_GAP = 2; // 인접 막대 사이 표면 여백

function formatSigned(value: number) {
  const text = Number.isInteger(value) ? String(value) : value.toFixed(1);
  return `${value > 0 ? "+" : ""}${text}%`;
}

// 데이터 끝(위)만 둥글고 베이스라인 쪽은 각진 막대
function barPath(x: number, y: number, w: number, h: number, r: number) {
  const rr = Math.min(r, w / 2, h);
  return [
    `M${x},${y + h}`,
    `V${y + rr}`,
    `Q${x},${y} ${x + rr},${y}`,
    `H${x + w - rr}`,
    `Q${x + w},${y} ${x + w},${y + rr}`,
    `V${y + h}`,
    "Z",
  ].join(" ");
}

interface ReturnHistogramProps {
  bins: ReturnBin[];
  band: ReturnBand;
  caseCount: number;
  signal: SignalMeta;
  horizonLabel: string;
}

export default function ReturnHistogram({
  bins,
  band,
  caseCount,
  signal,
  horizonLabel,
}: ReturnHistogramProps) {
  const [hovered, setHovered] = useState<number | null>(null);

  if (
    bins.length === 0 ||
    bins.some(
      (bin) =>
        !Number.isFinite(bin.from) ||
        !Number.isFinite(bin.to) ||
        !Number.isFinite(bin.count) ||
        bin.from >= bin.to ||
        bin.count < 0,
    ) ||
    !Number.isFinite(band.low) ||
    !Number.isFinite(band.high) ||
    band.low > band.high
  ) {
    return null;
  }

  const xMin = bins[0].from;
  const xMax = bins[bins.length - 1].to;
  if (xMax <= xMin) return null;

  const maxCount = Math.max(...bins.map((bin) => bin.count));
  const yStep = maxCount > 12 ? 5 : 2;
  const yMax = Math.max(yStep, Math.ceil(maxCount / yStep) * yStep);

  const plotW = VB_W - PAD.left - PAD.right;
  const plotH = VB_H - PAD.top - PAD.bottom;
  const baseline = PAD.top + plotH;
  const x = (v: number) => PAD.left + ((v - xMin) / (xMax - xMin)) * plotW;
  const y = (count: number) => baseline - (count / yMax) * plotH;

  const gridCounts: number[] = [];
  for (let count = yStep; count <= yMax; count += yStep) gridCounts.push(count);

  // 68% 구간 강조는 빈 중심 기준 — 구간 경계 음영은 band 값 그대로 그린다
  const isInBand = (bin: ReturnBin) => {
    const center = (bin.from + bin.to) / 2;
    return center >= band.low && center <= band.high;
  };

  const edges = [xMin, ...bins.map((bin) => bin.to)];
  const labelledEdges = bins.length <= 10 ? edges : edges.filter((_, i) => i % 2 === 0);
  const maxIndex = bins.findIndex((bin) => bin.count === maxCount);
  const ciPercent = Math.round(band.ciLevel * 100);

  return (
    <div className="relative">
      <svg
        viewBox={`0 0 ${VB_W} ${VB_H}`}
        className="block w-full"
        role="img"
        aria-label={`과거 유사 신호 ${caseCount}건의 실현 수익률 분포. ${ciPercent}% 구간은 ${formatSigned(band.low)}부터 ${formatSigned(band.high)}까지`}
      >
        {/* 68% 구간 음영 + 경계선 */}
        <rect
          x={x(band.low)}
          y={PAD.top - 14}
          width={x(band.high) - x(band.low)}
          height={plotH + 14}
          style={{ fill: signal.ink }}
          opacity={0.09}
        />
        {[band.low, band.high].map((edge) => (
          <line
            key={edge}
            x1={x(edge)}
            y1={PAD.top - 14}
            x2={x(edge)}
            y2={baseline}
            style={{ stroke: signal.ink }}
            strokeWidth={1}
            strokeDasharray="4 3"
            opacity={0.55}
          />
        ))}
        <text
          x={(x(band.low) + x(band.high)) / 2}
          y={PAD.top - 22}
          textAnchor="middle"
          fontSize={12}
          fontWeight={600}
          style={{ fill: signal.ink }}
        >
          10번 중 {Math.round(ciPercent / 10)}번 {formatSigned(band.low)} ~ {formatSigned(band.high)}
        </text>

        {/* 수평 그리드 + 건수 라벨 */}
        {gridCounts.map((count) => (
          <g key={count}>
            <line
              x1={PAD.left}
              y1={y(count)}
              x2={VB_W - PAD.right}
              y2={y(count)}
              style={{ stroke: "var(--color-line-soft)" }}
              strokeWidth={1}
            />
            <text x={PAD.left - 6} y={y(count) + 4} textAnchor="end" fontSize={11} style={{ fill: "var(--color-muted)" }}>
              {count}
            </text>
          </g>
        ))}
        <text x={PAD.left - 6} y={PAD.top - 22} textAnchor="end" fontSize={11} style={{ fill: "var(--color-muted)" }}>
          건수
        </text>

        {/* 0% 기준선 */}
        <line
          x1={x(0)}
          y1={PAD.top - 4}
          x2={x(0)}
          y2={baseline}
          style={{ stroke: "var(--color-edge)" }}
          strokeWidth={1}
        />

        {/* 막대: 구간 안은 신호 색, 밖은 회색 */}
        {bins.map((bin, i) => {
          const left = x(bin.from) + BAR_GAP;
          const width = x(bin.to) - x(bin.from) - BAR_GAP * 2;
          const top = y(bin.count);
          return (
            <path
              key={bin.from}
              d={barPath(left, top, width, baseline - top, 4)}
              style={{ fill: isInBand(bin) ? signal.ink : "var(--color-edge)" }}
              opacity={hovered === null || hovered === i ? 1 : 0.45}
            />
          );
        })}

        {/* 최빈 구간만 직접 라벨 — 나머지는 호버 툴팁으로 */}
        <text
          x={(x(bins[maxIndex].from) + x(bins[maxIndex].to)) / 2}
          y={y(bins[maxIndex].count) - 6}
          textAnchor="middle"
          fontSize={11.5}
          fontWeight={600}
          style={{ fill: "var(--color-ink)" }}
        >
          {bins[maxIndex].count}건
        </text>

        {/* 베이스라인 + x축 라벨 */}
        <line x1={PAD.left} y1={baseline} x2={VB_W - PAD.right} y2={baseline} style={{ stroke: "var(--color-line)" }} />
        {labelledEdges.map((edge) => (
          <text
            key={edge}
            x={x(edge)}
            y={baseline + 16}
            textAnchor="middle"
            fontSize={11}
            style={{ fill: "var(--color-muted)" }}
          >
            {formatSigned(edge)}
          </text>
        ))}
        <text x={VB_W - PAD.right} y={baseline + 30} textAnchor="end" fontSize={11} style={{ fill: "var(--color-muted)" }}>
          실제 수익률 ({horizonLabel})
        </text>

        {/* 호버 히트 영역 (막대보다 넓게, 플롯 전체 높이) */}
        {bins.map((bin, i) => (
          <rect
            key={bin.from}
            x={x(bin.from)}
            y={PAD.top - 14}
            width={x(bin.to) - x(bin.from)}
            height={plotH + 14}
            fill="transparent"
            onMouseEnter={() => setHovered(i)}
            onMouseLeave={() => setHovered(null)}
          />
        ))}
      </svg>

      {hovered !== null && (
        <div
          className="pointer-events-none absolute z-10 -translate-x-1/2 -translate-y-full whitespace-nowrap surface px-2.5 py-1.5 shadow-lift"
          style={{
            left: `${(((x(bins[hovered].from) + x(bins[hovered].to)) / 2) / VB_W) * 100}%`,
            top: `${((y(bins[hovered].count) - 8) / VB_H) * 100}%`,
          }}
        >
          <span className="text-xs font-medium tabular-nums">
            {formatSigned(bins[hovered].from)} ~ {formatSigned(bins[hovered].to)}
          </span>
          <span className="ml-1.5 text-xs text-muted">
            {bins[hovered].count}건 / {caseCount}건
          </span>
        </div>
      )}
    </div>
  );
}
