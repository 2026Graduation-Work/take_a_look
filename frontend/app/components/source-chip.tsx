import { formatKstDateTime } from "@/lib/display";
import type { DataProvenance } from "@/lib/types";

// 수치 옆에 붙이는 출처 표시. 실데이터가 기본이라 "출처 · 기준일"만 쓰고,
// 나머지(픽스처·mock·데모 시드)만 "예시 데이터"로 표시한다.
//
// 색 있는 알약이 아니라 조용한 회색 글씨로 둔다 — 출처는 늘 붙어 있는
// 각주지 경고가 아니다. 다만 "예시 데이터"는 신뢰와 직결되므로 점 하나로
// 구분하지 않는다 — 주의(주황)와 뜻이 섞이지 않게 조용한 회색 한 줄로 둔다.
export default function SourceChip({ provenance }: { provenance: DataProvenance }) {
  const real = provenance.kind === "real";
  const label = real
    ? [provenance.source, provenance.asOf && formatKstDateTime(provenance.asOf)]
        .filter(Boolean)
        .join(" · ")
    : "예시 데이터";

  return (
    <span className="inline-flex flex-none items-center gap-1.5 whitespace-nowrap text-2xs text-muted">
      {label}
    </span>
  );
}
