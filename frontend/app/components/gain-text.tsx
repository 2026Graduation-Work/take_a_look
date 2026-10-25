import { changeMeta, formatWonChange, signedPercent } from "@/lib/display";
import { gainRatio } from "@/lib/holdings-rules";

// 평단 대비 평가손익(#255). 숫자만 굵게, 상승 빨강·하락 파랑. 매수·매도 문구 없음.
// 평균 매입가가 없으면 아무것도 그리지 않는다. 무엇이 보이는지 안내는 부르는 화면이 한 번만 쓴다(10/20 피드백: 행마다 반복).
export default function GainText({ avgBuyPrice, close, aligned = false }: {
  avgBuyPrice: number | null;
  close: number | undefined;
  aligned?: boolean; // 종목 상세 헤더: 전일 대비와 같은 두 칸 정렬
}) {
  const ratio = gainRatio(avgBuyPrice, close);
  if (!avgBuyPrice || avgBuyPrice <= 0) return null;
  // "미제공"은 종가 데이터가 없을 때만
  if (ratio === null) return <span className="text-xs text-muted">평단 대비 미제공</span>;
  const { color, arrow } = changeMeta(ratio * 100, 1);
  return (
    <span className={`text-xs text-muted tabular-nums ${aligned ? "inline-grid grid-cols-[4rem_auto] items-baseline gap-x-2" : ""}`}>
      <span>평단 대비</span>{!aligned && " "}
      <span className={aligned ? "whitespace-nowrap text-right text-sm" : undefined} style={{ color }}>
        {arrow && `${arrow} `}
        {/* 종목 상세 머리는 전일 대비와 같은 형식(1주당 원과 %, 10/26 사용자 피드백) */}
        <strong className="font-semibold">{aligned && close ? formatWonChange(close - avgBuyPrice, ratio * 100) : signedPercent(ratio)}</strong>
      </span>
    </span>
  );
}
