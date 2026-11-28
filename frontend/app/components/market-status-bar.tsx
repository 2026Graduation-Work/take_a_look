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

  // 헤더 유리와 한 층으로 보이게 반투명 흰 면(v1.1.0). 지수가 먼저, 흔들림과 거래는 오른쪽 끝, 기준일은 ⓘ 안(10/20, 11/27 사용자 피드백)
  return (
    <section aria-label="시장 브리핑" className="border-t border-line/60 bg-white/70 shadow-[0_1px_0_rgb(0_0_0/0.06)]">
      <div className="page flex min-h-11 flex-wrap items-center gap-x-5 gap-y-1 py-2">
        {quotes.length > 0 ? (
          <div className="flex flex-wrap items-baseline gap-x-4 gap-y-1">
            {quotes.map((quote) => <Quote key={quote.symbol} quote={quote} />)}
          </div>
        ) : (
          <span className="text-xs text-muted">지수 데이터가 아직 없어요.</span>
        )}
        {stale && <strong className="flex-none text-xs font-semibold text-ink">{stale}</strong>}
        {real ? (
          <MarketDetail
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
            {/* 연도까지 보인다: 스냅샷이 오래되면 "12.30"만으로는 오늘 값처럼 읽힌다 */}
            <p className="m-0 mt-2 text-muted tabular-nums">시세 {date} 종가 기준, 실시간 아님</p>
          </MarketDetail>
        ) : (
          <span className="flex-none text-xs text-muted tabular-nums lg:ml-auto">예시 데이터, {date} 기준</span>
        )}
      </div>
    </section>
  );
}
