"use client";

import { useEffect, useId, useRef, useState, type ReactNode } from "react";
import { createPortal } from "react-dom";

// 시장 흔들림 "자세히": 트리거 바로 아래에 붙는 설명.
// 마우스는 올리면 보이고 벗어나면 사라진다. 키보드는 포커스가 가면 보인다. 터치는 탭으로 열고, 바깥 탭·Esc로 닫는다.
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
    const escape = (event: KeyboardEvent) => event.key === "Escape" && setOpen(false);
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
    <div
      ref={root}
      className="flex-none lg:ml-auto"
      onPointerEnter={(event) => event.pointerType === "mouse" && setOpen(true)}
      onPointerLeave={(event) => event.pointerType === "mouse" && setOpen(false)}
      onBlur={(event) => !root.current?.contains(event.relatedTarget as Node) && setOpen(false)}
    >
      <button
        ref={trigger}
        type="button"
        aria-expanded={open}
        aria-controls={id}
        onFocus={(event) => event.target.matches(":focus-visible") && setOpen(true)}
        // 마우스는 이미 올려서 열려 있으니 누르면 그대로, 터치·키보드는 누를 때마다 열고 닫는다
        onClick={(event) => setOpen((current) => ((event.nativeEvent as PointerEvent).pointerType === "mouse" ? true : !current))}
        className="flex min-h-11 items-center whitespace-nowrap text-xs text-body"
      >
        {label}
      </button>
      {open &&
        createPortal(
          <div
            ref={panel}
            id={id}
            role="tooltip"
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
