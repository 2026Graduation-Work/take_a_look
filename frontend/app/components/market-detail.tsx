"use client";

import { useEffect, useId, useRef, useState, type ReactNode, type PointerEvent as ReactPointerEvent } from "react";
import { createPortal } from "react-dom";

// 시장 흔들림 "자세히": 트리거 바로 아래에 붙는 설명.
// 기본은 클릭으로 열고 다시 클릭/바깥 클릭/Esc로 닫는다. 피처 설명만 hover를 켜고, 포털로 이동하는 동안 닫힘을 잠시 늦춘다.
// 시장 막대가 가로 스크롤(overflow)이라 absolute는 잘린다 → 열 때 트리거 위치로 fixed 좌표를 계산한다.
// 헤더의 backdrop-filter가 fixed의 기준 상자가 되므로 설명은 body로 portal한다.
export default function MarketDetail({
  label,
  children,
  title = "시장 흔들림 설명",
  className = "flex-none lg:ml-auto",
  hover = false,
}: {
  label: ReactNode;
  children: ReactNode;
  title?: string;
  className?: string;
  hover?: boolean;
}) {
  const id = useId();
  const root = useRef<HTMLDivElement>(null);
  const trigger = useRef<HTMLButtonElement>(null);
  const panel = useRef<HTMLDivElement>(null);
  const [open, setOpen] = useState(false);
  const closeTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const openedByHover = useRef(false);
  const cancelClose = () => {
    if (closeTimer.current !== null) clearTimeout(closeTimer.current);
  };
  const leave = () => {
    if (!hover) return;
    cancelClose();
    closeTimer.current = setTimeout(() => setOpen(false), 150);
  };
  const enter = (event: ReactPointerEvent) => {
    if (!hover || event.pointerType !== "mouse") return;
    cancelClose();
    openedByHover.current = true;
    setOpen(true);
  };
  useEffect(() => () => {
    if (closeTimer.current !== null) clearTimeout(closeTimer.current);
  }, []);
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
    <div ref={root} className={className} onPointerEnter={enter} onPointerLeave={leave}>
      <button
        ref={trigger}
        type="button"
        aria-expanded={open}
        aria-controls={id}
        onClick={() => {
          cancelClose();
          // 포인터 진입 직후 클릭해도 호버로 연 설명이 곧바로 닫히지 않게 한다.
          const keepOpen = hover && openedByHover.current;
          openedByHover.current = false;
          setOpen(current => keepOpen || !current);
        }}
        className="flex min-h-11 items-center whitespace-nowrap text-xs text-body"
      >
        {label}
      </button>
      {open &&
        createPortal(
          <div
            ref={panel}
            onPointerEnter={enter}
            onPointerLeave={leave}
            id={id}
            role="region"
            aria-label={title}
            style={{ top: position.top, left: position.left }}
            className="glass fixed z-50 w-[min(320px,calc(100vw-32px))] rounded-md bg-white/90 p-4 text-xs text-body"
          >
            {children}
          </div>,
          document.body,
        )}
    </div>
  );
}
