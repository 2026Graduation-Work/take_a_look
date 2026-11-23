"use client";

import { useRef, type KeyboardEvent, type ReactNode } from "react";
import { STAGE_COUNT, stageOf, stageWord, type AxisScale } from "@/lib/profiling/axis-scale";

export default function StageBar({ axis, value, onPick, title, stacked = false }: {
  axis: AxisScale;
  value: number;
  onPick?: (stage: number) => void;
  title?: ReactNode;
  stacked?: boolean;
}) {
  const stage = stageOf(axis, value);
  const word = stageWord(axis, stage);
  const cells = useRef<(HTMLButtonElement | null)[]>([]);
  const move = (event: KeyboardEvent, from: number) => {
    const step = { ArrowRight: 1, ArrowDown: 1, ArrowLeft: -1, ArrowUp: -1 }[event.key];
    const to = event.key === "Home" ? 0 : event.key === "End" ? STAGE_COUNT - 1 : step ? from + step : -1;
    if (to < 0 || to >= STAGE_COUNT) return;
    event.preventDefault();
    onPick?.(to);
    cells.current[to]?.focus();
  };
  return (
    <div className="flex min-w-0 flex-col gap-2" data-stage={stage}>
      <div className={stacked ? "flex flex-col gap-1" : "flex items-baseline justify-between gap-3"}>
        <span className="whitespace-nowrap text-sm font-medium text-ink">{title ?? axis.name}</span>
        <span className={`whitespace-nowrap text-sm text-body ${stacked ? "" : "text-right"}`}>{word}</span>
      </div>
      {onPick ? (
        <div role="radiogroup" aria-label={`${axis.name}, 왼쪽 ${axis.left}부터 오른쪽 ${axis.right}`} className="grid grid-cols-5 gap-1">
          {Array.from({ length: STAGE_COUNT }, (_, index) => (
            <button key={index} type="button" role="radio" aria-checked={index === stage} aria-label={stageWord(axis, index)}
              ref={(el) => { cells.current[index] = el; }}
              tabIndex={index === stage ? 0 : -1}
              onClick={() => onPick(index)} onKeyDown={(event) => move(event, index)}
              className="group flex h-11 items-center rounded-sm">
              <span className={`h-2 w-full rounded-sm transition-colors ${index === stage ? "bg-brand" : "bg-track group-hover:bg-line"}`} />
            </button>
          ))}
        </div>
      ) : (
        <div role="img" aria-label={`${axis.name}: ${word}. 다섯 칸 중 왼쪽에서 ${stage + 1}번째, 왼쪽 ${axis.left}, 오른쪽 ${axis.right}`}
          className="grid grid-cols-5 gap-1">
          {Array.from({ length: STAGE_COUNT }, (_, index) => (
            <span key={index} className={`h-2 rounded-sm ${index === stage ? "bg-brand" : "bg-track"}`} />
          ))}
        </div>
      )}
      <div aria-hidden="true" className="flex justify-between gap-3 text-2xs text-muted">
        <span>{axis.left}</span>
        <span className="text-right">{axis.right}</span>
      </div>
    </div>
  );
}
