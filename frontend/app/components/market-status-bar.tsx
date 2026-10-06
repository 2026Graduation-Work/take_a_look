import { MARKET_CONDITION_META } from "@/lib/display";
import MarketDetail from "./market-detail";
import SourceChip from "./source-chip";
import type { MarketIndexQuote, MarketStatus } from "@/lib/types";

// 헤더 아래 시장 브리핑: 지수 3개(등락 적/청) + 한 문장. 점수 숫자는 두지 않는다.
const SHOWN = new Set(["KOSPI", "KOSDAQ", "KOSPI200"]);

function formatValue(quote: MarketIndexQuote): string {
  return quote.value.toLocaleString("ko-KR", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function Quote({ quote }: { quote: MarketIndexQuote }) {
  const color =
    quote.change > 0 ? "var(--color-up)" : quote.change < 0 ? "var(--color-down)" : "var(--color-muted)";
  const arrow = quote.change > 0 ? "▲" : quote.change < 0 ? "▼" : "";
  return (
    <span className="flex flex-none items-baseline gap-1.5 whitespace-nowrap">
      <span className="text-xs text-muted">{quote.label}</span>
      <span className="text-sm font-medium tabular-nums">{formatValue(quote)}</span>
      <span className="text-xs tabular-nums" style={{ color }}>
        {arrow}
        {Math.abs(quote.changePercent).toFixed(2)}%
      </span>
    </span>
  );
}

// 백분위(0~100) → 구간 말. 산식: frontend/scripts/build_demo_snapshot.py
const level = (score: number) => (score < 100 / 3 ? "낮음" : score < 200 / 3 ? "보통" : "높음");

export default function MarketStatusBar({ status }: { status: MarketStatus }) {
  const meta = MARKET_CONDITION_META[status.condition];
  const real = status.provenance.kind === "real";
  const quotes = status.indexQuotes.filter(({ symbol }) => SHOWN.has(symbol));

  return (
    <section aria-label="시장 브리핑" className="border-t border-line/60">
      <div className="mx-auto flex min-h-10 w-full max-w-[1200px] items-center gap-5 overflow-x-auto px-4 py-2 [scrollbar-width:none] sm:px-6 lg:px-8 [&::-webkit-scrollbar]:hidden">
        {/* 연도까지 보인다: 스냅샷이 오래되면 "12.30"만으로는 오늘 값처럼 읽힌다. */}
        <span className="flex-none text-xs text-muted tabular-nums">{status.date.replaceAll("-", ".")} 기준</span>
        {quotes.length > 0 ? (
          quotes.map((quote) => <Quote key={quote.symbol} quote={quote} />)
        ) : (
          <span className="text-xs text-muted">지수 데이터가 아직 없어요</span>
        )}
        {real ? (
          <MarketDetail
            label={
              <>
                시장 흔들림 <strong className="mx-1 font-medium text-ink">{level(status.volatilityScore)}</strong> · 거래
                <strong className="mx-1 font-medium text-ink">{level(status.volumeScore)}</strong>
                <span className="ml-1 text-muted underline underline-offset-2">자세히</span>
              </>
            }
          >
            <p className="m-0">
              흔들림: KOSPI 최근 20거래일 가격 흔들림이 지난 1년 중 아래에서 {status.volatilityScore}% 위치예요.
            </p>
            <p className="m-0 mt-1">거래: 최근 20거래일 평균 거래대금이 지난 1년 중 아래에서 {status.volumeScore}% 위치예요.</p>
            <p className="m-0 mt-2 text-muted">3등분해 낮음·보통·높음으로 불러요. {meta.comment}.</p>
            <p className="m-0 mt-2 text-muted">출처 {status.provenance.source}</p>
          </MarketDetail>
        ) : (
          <span className="flex-none whitespace-nowrap text-xs text-body lg:ml-auto">{meta.comment}</span>
        )}
        {!real && <SourceChip provenance={status.provenance} />}
      </div>
    </section>
  );
}
