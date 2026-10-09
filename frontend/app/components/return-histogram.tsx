"use client";

import { useEffect, useRef, useState } from "react";
import type { SignalMeta } from "@/lib/display";
import { clipReturnBins } from "@/lib/chart-detail";
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
  bins: rawBins,
  band,
  caseCount,
  signal,
  horizonLabel,
}: ReturnHistogramProps) {
  // 누른 막대의 건수를 보인다. 다시 누르거나 바깥을 누르거나 Esc로 닫는다(올리기만으로는 열지 않음)
  const [hovered, setHovered] = useState<number | null>(null);
  const root = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (hovered === null) return;
    const outside = (event: PointerEvent) => !root.current?.contains(event.target as Node) && setHovered(null);
    const escape = (event: KeyboardEvent) => event.key === "Escape" && setHovered(null);
    document.addEventListener("pointerdown", outside);
    document.addEventListener("keydown", escape);
    return () => {
      document.removeEventListener("pointerdown", outside);
      document.removeEventListener("keydown", escape);
    };
  }, [hovered]);

  if (
    rawBins.length === 0 ||
    rawBins.some(
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

  // x축은 분포의 1~99% 구간. 밖은 양 끝 "이하"·"이상" 칸으로 묶는다.
  const bins = clipReturnBins(rawBins);
  const xMin = bins[0].from;
  const xMax = bins[bins.length - 1].to;
  if (xMax <= xMin) return null;

  const maxCount = Math.max(...bins.map((bin) => bin.count));
  // 격자는 4줄 안팎: 1·2·5×10ⁿ 중 maxCount/4 이상인 가장 작은 값. 실제 배치 분포는 한 칸에 수천 건이다
  const rawStep = maxCount / 4;
  const magnitude = 10 ** Math.floor(Math.log10(Math.max(rawStep, 1)));
  const yStep = maxCount <= 12 ? 2 : [1, 2, 5, 10].map((m) => m * magnitude).find((s) => s >= rawStep)!;
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

  const rawXStep = (xMax - xMin) / 6;
  const xMagnitude = 10 ** Math.floor(Math.log10(rawXStep));
  const xStep = [1, 2, 5, 10].map(n => n * xMagnitude).find(n => n >= rawXStep)!;
  const keptMin = bins[0].tail ? bins[0].to : xMin;
  const keptMax = bins[bins.length - 1].tail ? bins[bins.length - 1].from : xMax;
  const labelledEdges = [];
  for (let tick = Math.ceil(keptMin / xStep) * xStep; tick <= keptMax; tick += xStep) labelledEdges.push(tick);
  const binLabel = (bin: (typeof bins)[number]) =>
    bin.tail === "low" ? `${formatSigned(bin.to)} 이하` : bin.tail === "high" ? `${formatSigned(bin.from)} 이상` : `${formatSigned(bin.from)} ~ ${formatSigned(bin.to)}`;
  const maxIndex = bins.findIndex((bin) => bin.count === maxCount);
  const ciPercent = Math.round(band.ciLevel * 100);

  return (
    <div ref={root} className="relative">
      <svg
        viewBox={`0 0 ${VB_W} ${VB_H}`}
        className="block w-full"
        role="img"
        aria-label={`과거 유사 신호 ${caseCount.toLocaleString("ko-KR")}건의 실현 수익률 분포. ${ciPercent}% 구간은 ${formatSigned(band.low)}부터 ${formatSigned(band.high)}까지`}
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
              {count.toLocaleString("ko-KR")}
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
          const bucketWidth = x(bin.to) - x(bin.from);
          const gap = Math.min(BAR_GAP, bucketWidth / 4);
          const left = x(bin.from) + gap;
          const width = bucketWidth - gap * 2;
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
          {bins[maxIndex].count.toLocaleString("ko-KR")}건
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
        {bins.filter((bin) => bin.tail).map((bin) => (
          <text
            key={bin.tail}
            x={(x(bin.from) + x(bin.to)) / 2}
            y={baseline + 16}
            textAnchor="middle"
            fontSize={11}
            style={{ fill: "var(--color-muted)" }}
          >
            {bin.tail === "low" ? "이하" : "이상"}
          </text>
        ))}
        <text x={VB_W - PAD.right} y={baseline + 30} textAnchor="end" fontSize={11} style={{ fill: "var(--color-muted)" }}>
          실제 수익률 ({horizonLabel})
        </text>

        {/* 누르는 영역 (막대보다 넓게, 플롯 전체 높이) */}
        {bins.map((bin, i) => (
          <rect
            key={bin.from}
            x={x(bin.from)}
            y={PAD.top - 14}
            width={x(bin.to) - x(bin.from)}
            height={plotH + 14}
            fill="transparent"
            className="cursor-pointer"
            onClick={() => setHovered((current) => (current === i ? null : i))}
          />
        ))}
      </svg>
      {bins.every(bin => Math.abs(bin.to - bin.from - 2) < 1e-8) && (
        <p className="m-0 text-2xs text-muted">
          막대 한 칸은 수익률 2%p 구간이에요. 68% 범위는 별도로 표시해요.
          {bins.some((bin) => bin.tail) && " 양 끝 칸은 그 바깥을 모두 묶었어요."}
        </p>
      )}

      {hovered !== null && (
        <div
          className="pointer-events-none absolute z-10 -translate-x-1/2 -translate-y-full whitespace-nowrap surface px-3 py-2 shadow-lift"
          style={{
            left: `${(((x(bins[hovered].from) + x(bins[hovered].to)) / 2) / VB_W) * 100}%`,
            top: `${((y(bins[hovered].count) - 8) / VB_H) * 100}%`,
          }}
        >
          <span className="text-xs font-medium tabular-nums">{binLabel(bins[hovered])}</span>
          <span className="ml-2 text-xs text-muted">
            {bins[hovered].count.toLocaleString("ko-KR")}건 / {caseCount.toLocaleString("ko-KR")}건
          </span>
        </div>
      )}
    </div>
  );
}
