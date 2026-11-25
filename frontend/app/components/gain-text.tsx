import { changeMeta, formatWonChange, signedPercent } from "@/lib/display";
import { gainRatio } from "@/lib/holdings-rules";

export default function GainText({ avgBuyPrice, close, aligned = false }: {
  avgBuyPrice: number | null;
  close: number | undefined;
  aligned?: boolean;
}) {
  const ratio = gainRatio(avgBuyPrice, close);
  if (!avgBuyPrice || avgBuyPrice <= 0) return null;
  if (ratio === null) return <span className="text-xs text-muted">평단 대비 미제공</span>;
  const { color, arrow } = changeMeta(ratio * 100, 1);
  return (
    <span className={`text-xs text-muted tabular-nums ${aligned ? "inline-grid grid-cols-[4rem_auto] items-baseline gap-x-2" : ""}`}>
      <span>평단 대비</span>{!aligned && " "}
      <span className={aligned ? "whitespace-nowrap text-right text-sm" : undefined} style={{ color }}>
        {arrow && `${arrow} `}
        <strong className="font-semibold">{aligned && close ? formatWonChange(close - avgBuyPrice, ratio * 100) : signedPercent(ratio)}</strong>
      </span>
    </span>
  );
}
