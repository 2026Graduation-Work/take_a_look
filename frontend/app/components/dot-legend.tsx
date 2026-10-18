import { SIGNAL_WORD } from "@/lib/copy-glossary";

// 색 범례: 시장 바와 같은 색 점 + 단어(● 상승 쪽 ● 중립 ● 하락 쪽). 글자로 색 이름을 늘어놓지 않는다.
export default function DotLegend({ items }: { items: [color: string, word: string][] }) {
  return (
    <span className="inline-flex flex-wrap items-center gap-x-3">
      {items.map(([color, word]) => (
        <span key={word} className="inline-flex items-center gap-1">
          <span aria-hidden className="size-2 rounded-full" style={{ backgroundColor: color }} />
          {word}
        </span>
      ))}
    </span>
  );
}

export const SIGNAL_LEGEND: [string, string][] = [
  ["var(--color-sig-p-solid)", SIGNAL_WORD.up],
  ["var(--color-sig-n-solid)", SIGNAL_WORD.flat],
  ["var(--color-sig-ng-solid)", SIGNAL_WORD.down],
];
