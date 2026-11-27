import { useState, type CSSProperties, type ReactNode } from "react";
import { dec, pct, TERMS, type Metric } from "./metrics";
import type { Point } from "./types";
import styles from "./lab.module.css";

export function Term({ children, definition }: { children: string; definition?: string }) {
  const [position, setPosition] = useState<{ top?: number; bottom?: number; left: number }>();
  const help = [TERMS[children], definition].filter(Boolean).join(" ");
  function anchor(target: HTMLElement) {
    const rect = target.getBoundingClientRect();
    const left = Math.max(8, Math.min(rect.left, window.innerWidth - Math.min(285, window.innerWidth * .7) - 8));
    setPosition(rect.top < 144 ? { top: rect.bottom + 8, left } : { bottom: window.innerHeight - rect.top + 8, left });
  }
  return help
    ? <span className={styles.term} tabIndex={0} aria-label={`${children}. ${help}`}
      onMouseEnter={(event) => anchor(event.currentTarget)} onMouseLeave={() => setPosition(undefined)}
      onFocus={(event) => anchor(event.currentTarget)} onBlur={() => setPosition(undefined)}
      onKeyDown={(event) => { if (event.key === "Escape") setPosition(undefined); }}>
      {children}{position && <span className={styles.tooltip} style={position} aria-hidden>{help}</span>}</span>
    : children;
}
export function Panel({ children, title, action, className = "" }: {
  children: ReactNode; title?: ReactNode; action?: ReactNode; className?: string;
}) {
  return <section className={`surface ${styles.panel} ${className}`}>
    {(title || action) && <div className={styles.head}><h2>{title}</h2>{action}</div>}{children}
  </section>;
}
export function Segments({ options, selected, change, label }: {
  options: { key: string; label: string }[]; selected: string; change: (key: string) => void; label: string;
}) {
  return <div className={styles.segments} role="group" aria-label={label}>
    {options.map((option) => <button type="button" key={option.key} aria-pressed={selected === option.key}
      onClick={() => change(option.key)}>{option.label}</button>)}
  </div>;
}
export function Dot({ color }: { color: string }) {
  return <span className={styles.dot} style={{ background: color }} aria-hidden />;
}
export interface GraphSeries {
  name: string;
  color: string;
  points: Point[];
  dashed?: boolean;
}
export function Legend({ series }: { series: { name: string; color: string }[] }) {
  return <div className={styles.legend}>{series.map((line, i) =>
    <span key={i}><Dot color={line.color} />{line.name}</span>,
  )}</div>;
}
export function Empty({ children }: { children: ReactNode }) {
  return <p className={styles.muted}>{children}</p>;
}
export function Meter({ value, color }: { value: number; color?: string }) {
  return <span
    className={styles.meter}
    style={{ "--fill": color, "--width": `${Math.max(0, Math.min(value, 1)) * 100}%` } as CSSProperties}
  />;
}
export function EquityChart({ series }: { series: GraphSeries[] }) {
  const w = 960, h = 260, left = 62, right = 26, top = 18, bottom = 35;
  const points = series.flatMap((line) => line.points);
  if (points.length === 0) return <Empty>이 기간의 자산 곡선이 없습니다.</Empty>;
  const dates = points.map((point) => Date.parse(point.date)).filter(Number.isFinite);
  if (!dates.length) return <Empty>이 기간의 거래일 정보가 없습니다.</Empty>;
  const start = Math.min(...dates), end = Math.max(...dates);
  const values = points.map((point) => point.value).concat(1);
  const low = Math.min(...values), high = Math.max(...values), pad = (high - low || .1) * .12;
  const x = (date: string) => left + (Date.parse(date) - start) / (end - start || 1) * (w - left - right);
  const y = (value: number) => top + (high + pad - value) / (high - low + pad * 2) * (h - top - bottom);
  const fmt = (point: number) => pct(point - 1, 0);
  const datesShown = [...new Set([start, (start + end) / 2, end].map((stamp) => new Date(stamp).toISOString().slice(0, 10)))];
  return <figure className={styles.figure}>
    <svg viewBox={`0 0 ${w} ${h}`} role="img" aria-label="초기 자산 대비 누적 수익률">
      {[...new Set([high, 1, low])].map((line) => <g key={line}>
        <line x1={left} x2={w - right} y1={y(line)} y2={y(line)} className={line === 1 ? styles.reference : styles.gridLine} />
        <text x={left - 9} y={y(line) + 4} textAnchor="end">{fmt(line)}</text>
      </g>)}
      {datesShown.map((label) => <text x={x(label)} y={h - 10} textAnchor="middle" key={label}>{label}</text>)}
      {series.map((line, i) => <g key={i}>
        <polyline points={line.points.map((point) => `${x(point.date)},${y(point.value)}`).join(" ")}
          fill="none" stroke={line.color} strokeWidth={line.dashed ? 1.75 : 2.5} strokeDasharray={line.dashed ? "5 4" : undefined} />
        {line.points.at(-1) && <circle cx={x(line.points.at(-1)!.date)} cy={y(line.points.at(-1)!.value)} r={3.5} fill={line.color}>
          <title>{line.name} {fmt(line.points.at(-1)!.value)}</title>
        </circle>}
      </g>)}
    </svg>
    <Legend series={series.filter((line) => line.points.length)} />
  </figure>;
}

export function Distribution({ values, model, metric }: { values: number[]; model: number | null; metric: Metric }) {
  if (!values.length || model === null) return <Empty>{metric.label} 분포가 없습니다.</Empty>;
  const low = Math.min(model, ...values), high = Math.max(model, ...values), pad = (high - low || 1) * .08;
  const x = (v: number) => 32 + (v - low + pad) / (high - low + pad * 2) * 276;
  const sorted = [...values].sort((a, b) => a - b);
  return <svg viewBox="0 0 340 54" className={styles.strip} role="img" aria-label={`${metric.label} 분포에서 모델 ${metric.fmt(model)}`}>
    <line x1="32" x2="308" y1="19" y2="19" className={styles.gridLine} />
    {sorted.map((value, i) => <circle key={i} cx={x(value)} cy={19 + ((i % 5) - 2) * 3} r="3" fill="var(--color-ghost)" opacity=".65"><title>{metric.fmt(value)}</title></circle>)}
    <line x1={x(model)} x2={x(model)} y1="4" y2="34" stroke="var(--color-brand)" strokeWidth="2" />
    <text x={x(model)} y="51" textAnchor="middle" className={styles.modelMark}>{metric.fmt(model)}</text>
  </svg>;
}

export function Position({ metric, values }: {
  metric: Metric; values: { name: string; value: number; current: boolean }[];
}) {
  const min = Math.min(metric.ref, ...values.map(({ value }) => value)), max = Math.max(metric.good, ...values.map(({ value }) => value));
  const x = (value: number) => 12 + (value - min) / (max - min || 1) * 296;
  return <svg viewBox="0 0 320 32" className={styles.strip} role="img" aria-label={`${metric.label} 모델 비교 위치`}>
    <rect x={x(metric.good)} width={320 - x(metric.good)} y="5" height="22" rx="5" fill="var(--color-brand-soft)" />
    <line x1={x(metric.ref)} x2={x(metric.ref)} y1="3" y2="29" className={styles.reference} />
    {values.map(({ name, value, current }, i) => <circle key={i} cx={x(value)} cy={16 + (current ? 0 : (i % 3 - 1) * 3)}
      r={current ? 5.5 : 3.5} fill={current ? "var(--color-brand)" : "var(--color-ghost)"} stroke="white">
      <title>{name} {metric.fmt(value)}</title></circle>)}
  </svg>;
}

export function Calibration({ series }: {
  series: { name: string; color: string; calibration: { x: number; y: number }[] }[];
}) {
  if (series.every(({ calibration }) => calibration.length === 0)) return <Empty>확률 보정 자료가 없습니다.</Empty>;
  const x = (value: number) => 52 + value * 298, y = (value: number) => 209 - value * 184;
  return <figure className={styles.figure}>
    <svg viewBox="0 0 380 256" className={styles.calibration} role="img" aria-label="예측 상승 확률과 실제 상승 비율">
      <text x="53" y="15">실제 상승 비율</text>
      {[0, .5, 1].map((v) => <g key={v}>
        <line x1={x(0)} x2={x(1)} y1={y(v)} y2={y(v)} className={styles.gridLine} />
        <text x={x(0) - 8} y={y(v) + 4} textAnchor="end">{pct(v, 0)}</text>
        <text x={x(v)} y="229" textAnchor="middle">{pct(v, 0)}</text>
      </g>)}
      <line x1={x(0)} x2={x(1)} y1={y(0)} y2={y(1)} className={styles.reference} />
      {series.map(({ name, color, calibration }, j) => <g key={j}>
        <polyline points={calibration.map((point) => `${x(point.x)},${y(point.y)}`).join(" ")}
          fill="none" stroke={color} strokeWidth="2" />
        {calibration.map((point, i) => <circle key={i} cx={x(point.x)} cy={y(point.y)} r="4.5" fill={color}>
          <title>{name} 예측 {pct(point.x)}, 실제 {pct(point.y)}</title>
        </circle>)}
      </g>)}
      <text x={x(.5)} y="250" textAnchor="middle">예측 상승 확률</text>
    </svg>
  </figure>;
}
export function calibrationVerdict(calibration: { x: number; y: number }[]) {
  const highest = calibration.at(-1);
  if (!highest) return "확률 보정 자료가 없습니다.";
  const gap = highest.x - highest.y;
  const sample = `가장 높은 구간에서 평균 예측 ${pct(highest.x, 0)}, 실제 상승 ${pct(highest.y, 0)}.`;
  if (Math.abs(gap) <= .08) return `가장 높은 구간에서 예측과 실제가 가까워요. ${sample}`;
  return `가장 높은 구간에서 ${dec(Math.abs(gap) * 100, 0)}%p ${gap > 0 ? "높게" : "낮게"} 예측했어요. ${sample}`;
}

type DuelSeries = { name: string; color: string; values: Map<string, number | null> };
export function YearDuel({ series, metric, labels, reference = "무작위 수준" }: {
  series: DuelSeries[]; metric: Metric; labels: string[]; reference?: string;
}) {
  const all = series.flatMap((line) => [...line.values.values()].filter((x) => x !== null));
  if (!all.length) return <Empty>이 지표로 비교할 수 있는 결과가 없습니다.</Empty>;
  const low = Math.min(metric.ref, metric.good, ...all), high = Math.max(metric.ref, metric.good, ...all), range = high - low;
  const width = Math.max(760, labels.length * 108 + 126);
  const left = 53, right = 80, plotWidth = width - left - right;
  const x = (index: number) => left + (index + .5) / labels.length * plotWidth;
  const y = (value: number) => 26 + (high + range * .12 - value) / (range * 1.24) * 190;
  const rankings = labels.map((label) => series.flatMap((line, index) => {
    const value = line.values.get(label);
    return value == null ? [] : [{ index, value }];
  }).sort((a, b) => b.value - a.value));
  const winners = rankings.map((ranking) =>
    ranking.length > 1 && metric.fmt(ranking[0].value) !== metric.fmt(ranking[1].value) ? ranking[0].index : -1,
  );
  const wins = series.map((_, i) => winners.filter((winner) => winner === i).length);
  const compared = rankings.filter((ranking) => ranking.length > 1).length;
  return <div className={styles.duelLayout}><div className={styles.scroll}><div className={styles.duel} style={{ minWidth: width * .8 }}>
    <svg viewBox={`0 0 ${width} 255`} role="img" aria-label={`연도별 ${metric.label} 비교`}>
      {[[metric.ref, reference, styles.reference], [metric.good, "좋음 기준", styles.goodReference]].map(([value, label, css]) => <g key={String(label)}>
        <line x1={left} x2={width - right} y1={y(Number(value))} y2={y(Number(value))} className={String(css)} />
        <text x={width - right + 6} y={y(Number(value)) + 4}>{label}</text>
      </g>)}
      {labels.map((label, i) => <text key={label} x={x(i)} y="240" textAnchor="middle">{label}</text>)}
      {series.map((line, i) => {
        let open = false;
        const path = labels.map((label, j) => {
          const value = line.values.get(label);
          if (value == null) { open = false; return ""; }
          const instruction = `${open ? "L" : "M"}${x(j)} ${y(value)}`;
          open = true;
          return instruction;
        }).join(" ");
        return <g key={i}><path d={path} stroke={line.color} strokeWidth="2.5" fill="none" />
          {labels.map((label, j) => {
            const value = line.values.get(label), winner = winners[j] === i;
            if (value == null) return null;
            return <g key={label}><circle cx={x(j)} cy={y(value)} r={winner ? 6.5 : 4} fill={winner ? line.color : "white"}
              stroke={line.color} strokeWidth="2"><title>{line.name} {label} {metric.fmt(value)}</title></circle>
              {winner && <text x={x(j)} y={y(value) - 12} textAnchor="middle" className={styles.modelMark}>{metric.fmt(value)}</text>}</g>;
          })}
        </g>;
      })}
    </svg>
    <div className={styles.duelWinners} style={{ marginInline: `${left / width * 100}% ${right / width * 100}%`, gridTemplateColumns: `repeat(${labels.length}, minmax(0,1fr))` }}>
      {rankings.map((ranking, i) => {
        const winner = winners[i], line = series[winner];
        return <div key={labels[i]} title={line?.name} style={{ borderTopColor: line?.color }}>
          {winner < 0 ? <span>{ranking.length > 1 ? "비슷" : "비교 자료 없음"}</span> : <>
            <strong>{line.name}</strong><span>{metric.fmt(ranking[0].value - ranking[1].value)} 앞섬</span>
          </>}
        </div>;
      })}
    </div>
  </div></div>
    <div className={styles.duelTotals}><span>이긴 기간</span>
      {series.map((line, i) => <div key={i} title={line.name}><Dot color={line.color} />{wins[i]}/{compared}</div>)}
    </div>
  </div>;
}
