import type { ReactNode } from "react";
import { formatKstDateTime } from "@/lib/display";
import type { DataProvenance } from "@/lib/types";

// 페이지 맨 아래 "데이터 출처·기준" 표(상세: 더 알아보기 안, 대시보드: 하단). 카드마다 출처 버튼을 두지 않는다.
export function SourceTable({ rows, children }: { rows: [string, DataProvenance | null][]; children?: ReactNode }) {
  return (
    <dl className="m-0 grid grid-cols-[auto_minmax(0,1fr)] gap-x-4 gap-y-2 text-sm">
      {rows.map(([label, provenance]) => (
        <div key={label} className="contents">
          <dt className="text-body">{label}</dt>
          <dd className="m-0 min-w-0 [overflow-wrap:anywhere]">{provenance ? sourceText(provenance) : "미제공"}</dd>
        </div>
      ))}
      {children}
    </dl>
  );
}

// 출처 전체 목록(더 알아보기)용 한 줄 글.
export function sourceText(provenance: DataProvenance): string {
  if (provenance.kind !== "real") return "예시 데이터";
  return [provenance.source, provenance.asOf && formatKstDateTime(provenance.asOf)].filter(Boolean).join(" · ");
}
