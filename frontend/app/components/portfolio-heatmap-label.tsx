"use client";

import { useEffect, useRef, useState } from "react";

// 이름은 늘 보인다(길면 말줄임, #326 후속). 아래 줄은 실제 글자 크기를 재서
// 높이가 모자라면 줄 전체를, 폭이 모자라면 '비중'만 숨긴다. 타일 밖으로 넘치지 않는다.
export default function HeatmapLabel({ name, signal, weight }: { name: string; signal: string; weight: number | null }) {
  const content = useRef<HTMLSpanElement>(null);
  const [fits, setFits] = useState({ row: true, weight: true });
  useEffect(() => {
    const element = content.current!;
    const measure = () => {
      const parent = element.parentElement!;
      const style = getComputedStyle(element);
      const [nameLine, rowLine] = [...element.children] as HTMLElement[];
      const [signalText, weightText] = [...rowLine.children] as HTMLElement[];
      const paddingX = parseFloat(style.paddingLeft) + parseFloat(style.paddingRight);
      const height = nameLine.offsetHeight + rowLine.offsetHeight + parseFloat(style.rowGap)
        + parseFloat(style.paddingTop) + parseFloat(style.paddingBottom);
      const width = signalText.scrollWidth + (weightText?.scrollWidth ?? 0) + parseFloat(getComputedStyle(rowLine).columnGap) + paddingX;
      setFits({ row: height <= parent.clientHeight, weight: width <= parent.clientWidth });
    };
    const observer = new ResizeObserver(measure);
    observer.observe(element);
    // 웹 폰트가 바뀌면 글자의 실제 폭도 다시 확인한다.
    document.fonts.addEventListener("loadingdone", measure);
    return () => {
      observer.disconnect();
      document.fonts.removeEventListener("loadingdone", measure);
    };
  }, [name, signal, weight]);

  return (
    <span ref={content} aria-hidden="true" className="absolute inset-0 flex flex-col justify-between gap-1 px-2.5 py-1.5">
      <span className="truncate text-sm font-semibold">{name}</span>
      <span className={`relative flex items-baseline justify-between gap-2 text-xs font-medium ${fits.row ? "" : "invisible"}`}>
        <span className="truncate">{signal}</span>
        {weight !== null && <span className={`shrink-0 whitespace-nowrap tabular-nums ${fits.weight ? "" : "invisible absolute right-0"}`}>비중 {weight}%</span>}
      </span>
    </span>
  );
}
