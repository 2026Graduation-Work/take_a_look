import type { ReactNode } from "react";

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
