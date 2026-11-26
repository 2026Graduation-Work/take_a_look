"use client";

import { useEffect, useState, useSyncExternalStore } from "react";
import { changeMeta, formatSignedPercent, MARKET_CONDITION_META } from "@/lib/display";
import { loadLatestMarketStatus, staleLabel } from "@/lib/market-status";
import MarketDetail from "./market-detail";
import type { MarketIndexQuote, MarketStatus } from "@/lib/types";

const SHOWN = new Set(["KOSPI", "KOSDAQ"]);
const MOBILE_QUOTE_MOTION = "(max-width: 39.999rem) and (prefers-reduced-motion: no-preference)";

function subscribeToMobileQuoteMotion(callback: () => void) {
  const media = window.matchMedia(MOBILE_QUOTE_MOTION);
  media.addEventListener("change", callback);
  return () => media.removeEventListener("change", callback);
}

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

function MobileMarketQuotes({ quotes }: { quotes: MarketIndexQuote[] }) {
  const canAnimate = useSyncExternalStore(
    subscribeToMobileQuoteMotion,
    () => window.matchMedia(MOBILE_QUOTE_MOTION).matches,
    () => false,
  );
  const [position, setPosition] = useState(0);
  const [paused, setPaused] = useState(false);
  const onLoopCopy = position === quotes.length;

  useEffect(() => {
    if (!canAnimate || (paused && !onLoopCopy)) return;
    const timer = window.setTimeout(
      () => setPosition(onLoopCopy ? 0 : position + 1),
      onLoopCopy ? 350 : 4_000,
    );
    return () => window.clearTimeout(timer);
  }, [canAnimate, onLoopCopy, paused, position]);

  return (
    <div role="region" aria-label="시장 지수" className="flex min-w-0 basis-full items-center gap-2 motion-reduce:hidden sm:hidden">
      <ul className="sr-only">
        {quotes.map((quote) => <li key={quote.symbol}><Quote quote={quote} /></li>)}
      </ul>
      <div className="min-w-0 flex-1 overflow-hidden" aria-hidden="true">
        <div
          className={`flex ${position === 0 ? "" : "transition-transform duration-300 ease-in-out"}`}
          style={{ transform: `translateX(-${position * 100}%)` }}
        >
          {[...quotes, quotes[0]].map((quote, index) => (
            <div key={`${quote.symbol}-${index}`} className="w-full shrink-0">
              <Quote quote={quote} />
            </div>
          ))}
        </div>
      </div>
      <button
        type="button"
        className="min-h-11 shrink-0 px-2 text-xs text-muted hover:text-ink"
        aria-label={paused ? "지수 자동 전환 재생" : "지수 자동 전환 일시 정지"}
        onClick={() => setPaused(!paused)}
      >
        {paused ? "재생" : "멈춤"}
      </button>
    </div>
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

export default function MarketStatusBar({ status: snapshot, rotateQuotesOnMobile = false }: {
  status: MarketStatus;
  rotateQuotesOnMobile?: boolean;
}) {
  const status = useMarketStatus(snapshot);
  const stale = staleLabel(status.date);
  const meta = MARKET_CONDITION_META[status.condition];
  const real = status.provenance.kind === "real";
  const quotes = status.indexQuotes.filter(({ symbol }) => SHOWN.has(symbol) || (rotateQuotesOnMobile && symbol === "KOSPI200"));
  const showMobileRotation = rotateQuotesOnMobile && quotes.length > 1;
  const date = status.date.replaceAll("-", ".");

  return (
    <section aria-label="시장 브리핑" className="border-t border-line/60 bg-surface">
      <div className="page flex min-h-11 flex-wrap items-center gap-x-4 pt-2 sm:pt-0">
        {showMobileRotation && <MobileMarketQuotes key={quotes.map(({ symbol }) => symbol).join(",")} quotes={quotes} />}
        {quotes.length > 0 ? (
          <div
            role={rotateQuotesOnMobile ? "region" : undefined}
            aria-label={rotateQuotesOnMobile ? "시장 지수" : undefined}
            tabIndex={showMobileRotation ? 0 : undefined}
            className={rotateQuotesOnMobile
              ? `${showMobileRotation ? "hidden motion-reduce:flex sm:flex" : "flex"} min-w-0 basis-full items-baseline gap-x-5 overflow-x-auto py-1 sm:basis-auto sm:flex-wrap sm:overflow-visible sm:py-0`
              : "flex basis-full flex-wrap items-baseline gap-x-4 gap-y-1 sm:basis-auto"}
          >
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
                <span className="ml-3">거래</span> <Level score={status.volumeScore} />
                <span aria-hidden className="ml-1 text-muted">ⓘ</span>
                <span className="sr-only">설명 보기</span>
              </>
            }
          >
            <p className="m-0">
              KOSPI 최근 20거래일 가격 흔들림이 지난 1년 중 아래에서 {status.volatilityScore}% 위치예요.
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
