import MarketDetail from "./market-detail";
import { TERM_INFO, type TermKey } from "@/lib/copy-glossary";

export default function TermLabel({ term }: { term: TermKey }) {
  const { label, define, read, tip } = TERM_INFO[term];
  if (!tip) return <>{label}</>;
  return (
    <span className="inline-flex items-center">
      {label}
      <MarketDetail
        title={`${label} 설명`}
        className="-my-3 inline-flex"
        label={<><span aria-hidden className="px-1 text-muted">ⓘ</span><span className="sr-only">{label} 설명 보기</span></>}
      >
        <p className="m-0">{define} {read}</p>
      </MarketDetail>
    </span>
  );
}
