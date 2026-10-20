import type { ReactNode } from "react";
import { changeMeta } from "@/lib/display";

// 증감 값만 사용한다. 가격 수준·재무 비율·감성 점수에는 사용하지 않는다.
export default function ChangeText({ value, precision, children, className = "" }: {
  value: number;
  precision?: number;
  children: ReactNode;
  className?: string;
}) {
  const { color, arrow } = changeMeta(value, precision);
  return <span className={`tabular-nums ${className}`} style={{ color }}>{arrow && `${arrow} `}{children}</span>;
}
