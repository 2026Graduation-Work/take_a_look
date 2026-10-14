"use client";

import { useLayoutEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import Link from "next/link";
import { SIGNAL_META } from "@/lib/display";
import { HORIZON_AHEAD } from "@/lib/copy-glossary";
import type { PortfolioHolding } from "@/lib/types";

export default function HeatmapPopup({
  id, x, y, touch, holding, amount, weight, onClose,
}: {
  id: string;
  x: number;
  y: number;
  touch: boolean;
  holding: PortfolioHolding;
  amount: string;
  weight: number;
  onClose: () => void;
}) {
  const panel = useRef<HTMLDivElement>(null);
  const [position, setPosition] = useState<{ left: number; top: number } | null>(null);
  useLayoutEffect(() => {
    const place = () => {
      const rect = panel.current!.getBoundingClientRect();
      const gap = 12;
      const edge = 16;
      const above = y - rect.height - gap;
      setPosition({
        left: Math.max(edge, Math.min(x + gap, window.innerWidth - rect.width - edge)),
        top: Math.max(edge, Math.min(above >= edge ? above : y + gap, window.innerHeight - rect.height - edge)),
      });
    };
    place();
    const observer = new ResizeObserver(place);
    observer.observe(panel.current!);
    return () => observer.disconnect();
  }, [x, y]);

  const signal = SIGNAL_META[holding.signalLight];
  return createPortal(
    <div
      ref={panel}
      id={id}
      role={touch ? "dialog" : "tooltip"}
      aria-label={touch ? `${holding.name} 보유 정보` : undefined}
      className={`fixed z-50 flex w-64 max-w-[calc(100vw-32px)] max-h-[calc(100dvh-32px)] flex-col gap-4 overflow-y-auto rounded-md bg-surface p-4 text-sm text-ink shadow-lift ${touch ? "" : "pointer-events-none"}`}
      style={{ ...position, visibility: position ? "visible" : "hidden" }}
    >
      <span className="wrap-anywhere text-base font-semibold">{holding.name}</span>
      <div className="flex flex-col gap-1">
        <span className="font-medium" style={{ color: signal.ink }}>{HORIZON_AHEAD[20]} {signal.label}</span>
        <span className="tabular-nums">비중 {weight}%</span>
        <span className="text-xs tabular-nums text-muted">{holding.quantity.toLocaleString("ko-KR")}주, {amount}</span>
      </div>
      {touch && (
        <div className="flex flex-wrap items-center justify-between gap-2">
          <button type="button" className="btn-text" onClick={onClose}>닫기</button>
          <Link href={`/stocks/${holding.code}`} className="btn-text">종목 상세 보기</Link>
        </div>
      )}
    </div>,
    document.body,
  );
}
