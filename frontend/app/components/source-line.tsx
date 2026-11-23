import type { ReactNode } from "react";
import { formatKstDateTime } from "@/lib/display";
import type { DataProvenance } from "@/lib/types";

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

function sourceText(provenance: DataProvenance): string {
  if (provenance.kind !== "real") return "예시 데이터";
  const source = provenance.source.replaceAll("\u00b7", ", ");
  return [source, provenance.asOf && formatKstDateTime(provenance.asOf)].filter(Boolean).join(", ");
}
