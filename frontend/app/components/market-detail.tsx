"use client";

import { useEffect, useId, useRef, useState, type ReactNode } from "react";
import { createPortal } from "react-dom";

// 시장 흔들림 "자세히": 트리거 바로 아래에 붙는 설명.
// 누르면 열리고 다시 누르거나 바깥을 누르거나 Esc로 닫힌다(마우스·키보드·터치 모두 같음). 올리기·포커스만으로는 열리지 않는다.
// 시장 막대가 가로 스크롤(overflow)이라 absolute는 잘린다 → 열 때 트리거 위치로 fixed 좌표를 계산한다.
// 헤더의 backdrop-filter가 fixed의 기준 상자가 되므로 설명은 body로 portal한다.
export default function MarketDetail({ label, children }: { label: ReactNode; children: ReactNode }) {
  const id = useId();
  const root = useRef<HTMLDivElement>(null);
  const trigger = useRef<HTMLButtonElement>(null);
  const panel = useRef<HTMLDivElement>(null);
  const [open, setOpen] = useState(false);
  const [position, setPosition] = useState({ top: 0, left: 0 });

  useEffect(() => {
    if (!open) return;
    const place = () => {
      const rect = trigger.current!.getBoundingClientRect();
      const width = Math.min(320, window.innerWidth - 32);
      setPosition({ top: rect.bottom + 8, left: Math.max(16, Math.min(rect.left, window.innerWidth - width - 16)) });
    };
    const outside = (event: PointerEvent) => {
      const target = event.target as Node;
      if (!root.current?.contains(target) && !panel.current?.contains(target)) setOpen(false);
    };
    const escape = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      setOpen(false);
      trigger.current?.focus(); // 닫은 뒤 키보드 위치를 트리거로
    };
    place();
    window.addEventListener("resize", place);
    window.addEventListener("scroll", place, true);
    document.addEventListener("pointerdown", outside);
    document.addEventListener("keydown", escape);
    return () => {
      window.removeEventListener("resize", place);
      window.removeEventListener("scroll", place, true);
      document.removeEventListener("pointerdown", outside);
      document.removeEventListener("keydown", escape);
    };
  }, [open]);

  return (
    <div ref={root} className="flex-none lg:ml-auto">
      <button
        ref={trigger}
        type="button"
        aria-expanded={open}
        aria-controls={id}
        onClick={() => setOpen((current) => !current)}
        className="flex min-h-11 items-center whitespace-nowrap text-xs text-body"
      >
        {label}
      </button>
      {open &&
        createPortal(
          <div
            ref={panel}
            id={id}
            role="region"
            aria-label="시장 흔들림 설명"
            style={{ top: position.top, left: position.left }}
            className="glass fixed z-50 w-[min(320px,calc(100vw-32px))] rounded-md bg-white/90 p-4 text-xs leading-5 text-body"
          >
            {children}
          </div>,
          document.body,
        )}
    </div>
  );
}
