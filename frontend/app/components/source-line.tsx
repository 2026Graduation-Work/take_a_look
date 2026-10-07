import type { ReactNode } from "react";
import { formatKstDateTime } from "@/lib/display";
import type { DataProvenance } from "@/lib/types";

// 출처 줄(화면 공통). 수치 옆에는 "출처 · 10.06 기준" 한 줄만 두고, 누르면 공급원·모델·검증 상태가 펼쳐진다.
// 실데이터가 기본이라 예시(픽스처·데모 시드)만 "예시 데이터"로 적는다. 조용한 회색 — 출처는 경고가 아니라 각주다.
export default function SourceLine({
  provenance,
  label = "출처",
  detail,
  href,
}: {
  provenance: DataProvenance;
  label?: string;
  detail?: ReactNode; // 펼쳤을 때 공급원 뒤에 붙는 설명(공시 번호 등)
  href?: string; // 원문 링크(DART 등)
}) {
  if (provenance.kind !== "real") return <span className="text-2xs text-muted">예시 데이터</span>;
  const stamp = provenance.asOf ? shortStamp(provenance.asOf) : "";
  return (
    <details className="text-2xs text-muted [&[open]]:basis-full [&[open]>summary>span]:rotate-180">
      <summary className="inline-flex min-h-11 cursor-pointer list-none items-center gap-1 tabular-nums hover:text-ink">
        {label}
        {stamp && ` · ${stamp} 기준`}
        <span aria-hidden>▾</span>
      </summary>
      <p className="m-0 max-w-2xl pb-2 text-body [overflow-wrap:anywhere]">
        {provenance.source}
        {detail && <> · {detail}</>}
        {href && (
          <>
            {" · "}
            <a href={href} target="_blank" rel="noreferrer" className="text-brand hover:underline">
              원문 보기
            </a>
          </>
        )}
      </p>
    </details>
  );
}

// 출처 전체 목록(더 알아보기)용 한 줄 글.
export function sourceText(provenance: DataProvenance): string {
  if (provenance.kind !== "real") return "예시 데이터";
  return [provenance.source, provenance.asOf && formatKstDateTime(provenance.asOf)].filter(Boolean).join(" · ");
}

// 10.06 / 10.07 16:32. 올해가 아니면 연도까지(2025.12.30) — 오래된 값을 오늘 값으로 읽지 않게.
function shortStamp(asOf: string): string {
  const full = formatKstDateTime(asOf); // 2026.10.06 또는 2026.10.07 16:32
  return full.startsWith(`${new Date().getFullYear()}.`) ? full.slice(5) : full;
}
