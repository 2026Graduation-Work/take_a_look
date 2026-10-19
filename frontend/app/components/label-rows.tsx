import type { ReactNode } from "react";

// 라벨 | 값 2열(공용). 라벨 열 폭은 가장 긴 라벨에 맞춰 고정, 640px 미만은 라벨 위, 값 아래.
export default function LabelRows({ rows, className = "" }: { rows: [ReactNode, ReactNode][]; className?: string }) {
  return (
    <dl className={`m-0 grid grid-cols-1 gap-x-6 gap-y-1 text-sm sm:grid-cols-[max-content_1fr] sm:gap-y-2 ${className}`}>
      {rows.map(([label, value], index) => (
        <div key={index} className="contents">
          <dt className="font-medium text-ink">{label}</dt>
          <dd className="m-0 pb-2 text-body sm:pb-0">{value}</dd>
        </div>
      ))}
    </dl>
  );
}
