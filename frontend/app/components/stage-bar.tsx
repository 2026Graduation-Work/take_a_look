"use client";

import { useRef, type KeyboardEvent, type ReactNode } from "react";
import { STAGE_COUNT, stageOf, stageWord, type AxisScale } from "@/lib/profiling/axis-scale";

// 5칸 단계 막대: 같은 크기 칸 다섯, 내 칸만 진녹. 숫자 대신 단계 말과 양 끝 극 이름만 쓴다(DESIGN.md 화면 숫자 규칙).
// onPick을 넘기면 칸을 눌러(또는 방향키로) 고르는 라디오 묶음이 된다.
export default function StageBar({ axis, value, onPick, title }: {
  axis: AxisScale;
  value: number; // 저장 값(ratio), 화면 방향은 axis.flip이 정한다
  onPick?: (stage: number) => void;
  title?: ReactNode; // 축 이름 대신 쓸 제목(ⓘ 등)
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
      <div className="flex items-baseline justify-between gap-3">
        <span className="text-sm font-medium text-ink">{title ?? axis.name}</span>
        <span className="text-right text-sm text-body">{word}</span>
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
