"use client";

import { useEffect, useRef, useState } from "react";

// 실제 글자 폭과 높이를 재서 세 정보가 모두 들어갈 때만 타일 안에 표시한다.
// 레이아웃에 영향을 주지 않아 작은 비중의 타일 넓이도 그대로 유지된다.
export default function HeatmapLabel({ name, signal, weight }: { name: string; signal: string; weight: number }) {
  const content = useRef<HTMLSpanElement>(null);
  const [fits, setFits] = useState(false);
  useEffect(() => {
    const element = content.current!;
    const measure = () => {
      const parent = element.parentElement!;
      const style = getComputedStyle(element);
      const children = [...element.children] as HTMLElement[];
      const width = Math.max(...children.map((child) => child.scrollWidth))
        + parseFloat(style.paddingLeft) + parseFloat(style.paddingRight);
      const height = children.reduce((sum, child) => sum + child.getBoundingClientRect().height, 0)
        + parseFloat(style.rowGap) + parseFloat(style.paddingTop) + parseFloat(style.paddingBottom);
      setFits(width <= parent.clientWidth && height <= parent.clientHeight);
    };
    const observer = new ResizeObserver(measure);
    observer.observe(element);
    for (const child of element.children) observer.observe(child);
    // 웹 폰트가 바뀌면 글자의 실제 폭도 다시 확인한다.
    document.fonts.addEventListener("loadingdone", measure);
    return () => {
      observer.disconnect();
      document.fonts.removeEventListener("loadingdone", measure);
    };
  }, [name, signal, weight]);

  return (
    <span
      ref={content}
      aria-hidden="true"
      className={`absolute inset-0 flex flex-col justify-between gap-2 px-3 py-2 ${fits ? "visible" : "invisible"}`}
    >
      <span className="shrink-0 whitespace-nowrap text-base font-semibold">{name}</span>
      <span className="flex shrink-0 items-baseline justify-between gap-2 text-sm font-medium">
        <span className="shrink-0 whitespace-nowrap">{signal}</span>
        <span className="shrink-0 whitespace-nowrap text-xs tabular-nums">비중 {weight}%</span>
      </span>
    </span>
  );
}
