"use client";

import { useEffect, useRef, useState } from "react";

// 칸 안에는 이름과 '평가금액 (비중)'만(신호는 색과 범례가 말한다, 10/20 사용자 피드백). 이름은 늘 보인다(길면 말줄임).
// 실제 글자 크기를 재서 두 줄이 들어가면 두 줄(이름 왼쪽 위, 금액 오른쪽 아래), 높이가 모자라면 한 줄에 나란히, 폭도 모자라면 이름만. 타일 밖으로 넘치지 않는다.
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
    // 웹 폰트가 바뀌면 글자의 실제 폭도 다시 확인한다.
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
      className={`absolute inset-0 flex gap-x-2 gap-y-1 px-2.5 py-1.5 ${mode === "stack" ? "flex-col justify-between" : "items-center justify-between"}`}
    >
      <span className="min-w-0 shrink-0 truncate text-sm font-semibold">{name}</span>
      {/* 평가금액 (비중)은 예전 '비중' 자리처럼 오른쪽 아래(10/20 사용자 피드백) */}
      <span className={`shrink-0 whitespace-nowrap text-xs font-medium tabular-nums ${mode === "stack" ? "self-end" : ""} ${mode === "name" ? "invisible absolute" : ""}`}>{detail}</span>
    </span>
  );
}
