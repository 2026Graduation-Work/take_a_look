"use client";

import { useEffect, useState } from "react";
import { changeMeta, formatSignedPercent, MARKET_CONDITION_META } from "@/lib/display";
import { loadLatestMarketStatus, staleLabel } from "@/lib/market-status";
import MarketDetail from "./market-detail";
import type { MarketIndexQuote, MarketStatus } from "@/lib/types";

const SHOWN = new Set(["KOSPI", "KOSDAQ"]);

function formatValue(quote: MarketIndexQuote): string {
  return quote.value.toLocaleString("ko-KR", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function Quote({ quote }: { quote: MarketIndexQuote }) {
  const { color } = changeMeta(quote.changePercent, 2);
  return (
    <span className="inline-flex flex-none items-baseline gap-1 whitespace-nowrap sm:gap-2">
      <span className="text-xs text-muted">{quote.label}</span>
      <span className="text-sm font-medium tabular-nums">{formatValue(quote)}</span>
      <span className="text-xs tabular-nums" style={{ color }}>
        {formatSignedPercent(quote.changePercent, 2)}
      </span>
    </span>
  );
}

// 백분위(0~100) → 구간 말. 산식: frontend/scripts/build_demo_snapshot.py
const level = (score: number) => (score < 100 / 3 ? "낮음" : score < 200 / 3 ? "보통" : "높음");
const LEVEL_DOT = { 낮음: "bg-ghost", 보통: "bg-caution-soft", 높음: "bg-caution-mark" } as const;

function Level({ score }: { score: number }) {
  const word = level(score);
  return (
    <strong className="mx-1 inline-flex items-center gap-1 font-medium text-ink">
      <span aria-hidden className={`size-1.5 rounded-full ${LEVEL_DOT[word]}`} />
      {word}
    </strong>
  );
}

export function useMarketStatus(snapshot: MarketStatus): MarketStatus {
  const [status, setStatus] = useState(snapshot);
  useEffect(() => {
    let alive = true;
    void loadLatestMarketStatus()
      .then((latest) => alive && latest && latest.date > snapshot.date && setStatus(latest))
      .catch(() => undefined);
    return () => {
      alive = false;
    };
  }, [snapshot.date]);
  return status;
}

export default function MarketStatusBar({ status: snapshot }: { status: MarketStatus }) {
  const status = useMarketStatus(snapshot);
  const stale = staleLabel(status.date);
  const meta = MARKET_CONDITION_META[status.condition];
  const real = status.provenance.kind === "real";
  const quotes = status.indexQuotes.filter(({ symbol }) => SHOWN.has(symbol));
  const date = status.date.replaceAll("-", ".");

  return (
    <section aria-label="시장 브리핑" className="border-t border-line/60 bg-surface">
      <div className="page flex min-h-11 flex-wrap items-center gap-x-4 pt-2 sm:pt-0">
        {quotes.length > 0 ? (
          <div className="flex basis-full flex-wrap items-baseline gap-x-4 gap-y-1 sm:basis-auto">
            {quotes.map((quote) => <Quote key={quote.symbol} quote={quote} />)}
          </div>
        ) : (
          <span className="basis-full text-xs text-muted sm:basis-auto">지수 데이터가 아직 없어요.</span>
        )}
        {stale && <strong className="text-xs font-semibold text-ink">{stale}</strong>}
        {real ? (
          <MarketDetail
            className="ml-auto flex-none"
            label={
              <>
                시장 흔들림 <Level score={status.volatilityScore} />
                <span aria-hidden className="ml-1 text-muted">ⓘ</span>
                <span className="sr-only">설명 보기</span>
              </>
            }
          >
            <p className="m-0">
              KOSPI 최근 20거래일 가격 흔들림이 지난 1년 중 아래에서 {status.volatilityScore}% 위치예요.
            </p>
            <p className="m-0 mt-2">
              거래 <Level score={status.volumeScore} />
            </p>
            <p className="m-0 mt-1">최근 20거래일 평균 거래대금이 지난 1년 중 아래에서 {status.volumeScore}% 위치예요.</p>
            <p className="m-0 mt-2 text-muted">{meta.comment}.</p>
            <p className="m-0 mt-2 text-muted tabular-nums">{date} 기준</p>
          </MarketDetail>
        ) : (
          <span className="flex-none whitespace-nowrap text-xs text-muted lg:ml-auto">{meta.comment}</span>
        )}
        {!real && <span className="flex-none text-2xs text-muted tabular-nums">예시 데이터, {date} 기준</span>}
      </div>
    </section>
  );
}
