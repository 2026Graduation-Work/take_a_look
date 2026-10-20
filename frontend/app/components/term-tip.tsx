import MarketDetail from "./market-detail";
import { TERM_INFO, type TermKey } from "@/lib/copy-glossary";

// 용어 이름 + ⓘ(누르면 정의와 읽는 법). tip이 false인 일상어는 이름만(DESIGN.md '용어 설명 단계').
export default function TermLabel({ term }: { term: TermKey }) {
  const { label, define, read, tip } = TERM_INFO[term];
  if (!tip) return <>{label}</>;
  return (
    <span className="inline-flex items-center">
      {label}
      <MarketDetail
        title={`${label} 설명`}
        className="-my-3 inline-flex" // 누르는 높이 44px는 두고 줄 높이는 늘리지 않는다
        label={<><span aria-hidden className="px-1 text-muted">ⓘ</span><span className="sr-only">{label} 설명 보기</span></>}
      >
        <p className="m-0">{define} {read}</p>
      </MarketDetail>
    </span>
  );
}
