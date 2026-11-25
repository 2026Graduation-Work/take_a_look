"use client";

import { useEffect, useState, type ReactNode } from "react";

export const WAIT_DELAY_MS = 300;

export function useDelayed(active: boolean, ms = WAIT_DELAY_MS): boolean {
  const [shown, setShown] = useState(false);
  useEffect(() => {
    const timer = setTimeout(() => setShown(active), active ? ms : 0);
    return () => clearTimeout(timer);
  }, [active, ms]);
  return active && shown;
}

export function Spinner({ label, size = "md", active = true }: { label?: ReactNode; size?: "sm" | "md"; active?: boolean }) {
  if (!useDelayed(active)) return null;
  return (
    <span role="status" className="inline-flex items-center gap-2 text-sm text-body">
      <span aria-hidden className={`${size === "sm" ? "size-4" : "size-6"} flex-none animate-spin rounded-full border-2 border-brand/20 border-t-brand motion-reduce:hidden`} />
      {label ?? <span className="sr-only">처리 중</span>}
    </span>
  );
}

export function ProgressBar({ value, label, detail, active = true }: { value: number; label: ReactNode; detail?: ReactNode; active?: boolean }) {
  const percent = Math.round(Math.min(1, Math.max(0, value)) * 100);
  if (!useDelayed(active)) return null;
  return (
    <div role="status" className="flex max-w-sm flex-col gap-2">
      <p className="m-0 flex justify-between gap-3 text-sm text-body tabular-nums">
        <span>{label}</span>
        <span>{percent}%</span>
      </p>
      <div aria-hidden className="h-1 overflow-hidden rounded-full bg-track motion-reduce:hidden">
        <div className="h-full rounded-full bg-brand-accent transition-[width] duration-200 motion-reduce:transition-none" style={{ width: `${percent}%` }} />
      </div>
      {detail && <p className="m-0 text-xs text-muted tabular-nums">{detail}</p>}
    </div>
  );
}

export function BusyLabel({ busy, children }: { busy: boolean; children: ReactNode }) {
  const spinning = useDelayed(busy);
  return (
    <span className="grid place-items-center">
      <span className={`[grid-area:1/1] ${spinning ? "invisible motion-reduce:visible" : ""}`}>{children}</span>
      {spinning && (
        <span role="status" className="[grid-area:1/1] flex">
          <span aria-hidden className="size-4 animate-spin rounded-full border-2 border-current border-t-transparent motion-reduce:hidden" />
          <span className="sr-only">처리 중</span>
        </span>
      )}
    </span>
  );
}
