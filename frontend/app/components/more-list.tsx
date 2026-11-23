"use client";

import { useState, type ReactNode } from "react";

const FIRST = 3;

export default function MoreList<T>({ items, label, render }: { items: T[]; label: string; render: (item: T) => ReactNode }) {
  const [open, setOpen] = useState(false);
  const rest = items.length - FIRST;
  return (
    <>
      <ul aria-label={label} className="m-0 flex list-none flex-col gap-2 p-0">
        {(open || rest <= 0 ? items : items.slice(0, FIRST)).map(render)}
      </ul>
      {rest > 0 && (
        <button type="button" className="btn-text min-h-11 self-start text-sm" aria-expanded={open} onClick={() => setOpen(!open)}>
          {open ? "접기" : `더 보기(${rest})`}
        </button>
      )}
    </>
  );
}
