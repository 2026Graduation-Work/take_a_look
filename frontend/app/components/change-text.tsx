import type { ReactNode } from "react";
import { changeMeta } from "@/lib/display";

export default function ChangeText({ value, precision, children, className = "" }: {
  value: number;
  precision?: number;
  children: ReactNode;
  className?: string;
}) {
  const { color, arrow } = changeMeta(value, precision);
  return <span className={`tabular-nums ${className}`} style={{ color }}>{arrow && `${arrow} `}{children}</span>;
}
