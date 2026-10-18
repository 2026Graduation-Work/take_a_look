import { signedPercent } from "@/lib/display";
import { gainRatio } from "@/lib/holdings-rules";

// 평단 대비 평가손익(#255). 숫자만 굵게, 상승 빨강·하락 파랑. 매수·매도 문구 없음.
export default function GainText({ avgBuyPrice, close }: { avgBuyPrice: number | null; close: number | undefined }) {
  const ratio = gainRatio(avgBuyPrice, close);
  // 평단을 비워 둔 것은 사용자가 채울 수 있다 — "미제공"은 종가 데이터가 없을 때만
  if (!avgBuyPrice || avgBuyPrice <= 0) return <span className="text-xs text-muted">평균 매입가를 넣으면 보여요</span>;
  if (ratio === null) return <span className="text-xs text-muted">평단 대비 미제공</span>;
  const color = ratio > 0 ? "var(--color-up)" : ratio < 0 ? "var(--color-down)" : "var(--color-body)";
  const arrow = ratio > 0 ? "▲ " : ratio < 0 ? "▼ " : "";
  return (
    <span className="text-xs text-muted tabular-nums">
      평단 대비{" "}
      <span style={{ color }}>
        {arrow}
        <strong className="font-semibold">{signedPercent(ratio)}</strong>
      </span>
    </span>
  );
}
