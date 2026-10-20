import { changeMeta, signedPercent } from "@/lib/display";
import { gainRatio } from "@/lib/holdings-rules";

// 평단 대비 평가손익(#255). 숫자만 굵게, 상승 빨강·하락 파랑. 매수·매도 문구 없음.
export default function GainText({ avgBuyPrice, close, aligned = false }: {
  avgBuyPrice: number | null;
  close: number | undefined;
  aligned?: boolean;
}) {
  const ratio = gainRatio(avgBuyPrice, close);
  // 평단을 비워 둔 것은 사용자가 채울 수 있다 — "미제공"은 종가 데이터가 없을 때만
  if (!avgBuyPrice || avgBuyPrice <= 0) return <span className="text-xs text-muted">평균 매입가를 넣으면 보여요</span>;
  if (ratio === null) return <span className="text-xs text-muted">평단 대비 미제공</span>;
  const { color, arrow } = changeMeta(ratio * 100, 1);
  return (
    <span className={`text-xs text-muted tabular-nums ${aligned ? "inline-grid grid-cols-[4rem_7rem] items-baseline gap-x-2" : ""}`}>
      <span>평단 대비</span>{!aligned && " "}
      <span className={aligned ? "text-right text-sm" : undefined} style={{ color }}>
        {arrow && `${arrow} `}
        <strong className="font-semibold">{signedPercent(ratio)}</strong>
      </span>
    </span>
  );
}
