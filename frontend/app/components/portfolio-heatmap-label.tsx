"use client";

import { useEffect, useRef, useState } from "react";

export default function HeatmapLabel({ name, detail }: { name: string; detail: string }) {
  const content = useRef<HTMLSpanElement>(null);
  const [mode, setMode] = useState<"stack" | "inline" | "name">("stack");
  useEffect(() => {
    const element = content.current!;
    const measure = () => {
      const parent = element.parentElement!;
      const style = getComputedStyle(element);
      const [nameText, detailText] = [...element.children] as HTMLElement[];
      const paddingX = parseFloat(style.paddingLeft) + parseFloat(style.paddingRight);
      const paddingY = parseFloat(style.paddingTop) + parseFloat(style.paddingBottom);
      const stackFits =
        nameText.offsetHeight + detailText.offsetHeight + parseFloat(style.rowGap) + paddingY <= parent.clientHeight &&
        detailText.scrollWidth + paddingX <= parent.clientWidth;
      const inlineFits = nameText.scrollWidth + detailText.scrollWidth + parseFloat(style.columnGap) + paddingX <= parent.clientWidth;
      setMode(stackFits ? "stack" : inlineFits ? "inline" : "name");
    };
    const observer = new ResizeObserver(measure);
    observer.observe(element);
    document.fonts.addEventListener("loadingdone", measure);
    return () => {
      observer.disconnect();
      document.fonts.removeEventListener("loadingdone", measure);
    };
  }, [name, detail]);

  return (
    <span
      ref={content}
      aria-hidden="true"
      className={`absolute inset-0 flex gap-x-2 gap-y-1 px-2 py-2 ${mode === "stack" ? "flex-col justify-between" : "items-center justify-between"}`}
    >
      <span className="min-w-0 shrink-0 truncate text-sm font-semibold">{name}</span>
      <span className={`shrink-0 whitespace-nowrap text-xs font-medium tabular-nums ${mode === "stack" ? "self-end" : ""} ${mode === "name" ? "invisible absolute" : ""}`}>{detail}</span>
    </span>
  );
}
