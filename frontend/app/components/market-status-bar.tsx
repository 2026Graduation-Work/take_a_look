"use client";

import { useEffect, useState } from "react";
import { MARKET_CONDITION_META } from "@/lib/display";
import { loadLatestMarketStatus, staleLabel } from "@/lib/market-status";
import MarketDetail from "./market-detail";
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
    <span className="flex flex-none items-baseline gap-2 whitespace-nowrap">
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
// 회색 → 노랑 → 주황 점 + 본문색 글자. 빨강·파랑은 상승·하락 전용이라 쓰지 않는다(DESIGN.md 1).
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

// 시장 바와 대시보드 출처 표가 같은 값을 쓴다(#278 점검: 바는 최신 행, 출처 표는 스냅샷 날짜를 보여 주던 문제)
export function useMarketStatus(snapshot: MarketStatus): MarketStatus {
  const [status, setStatus] = useState(snapshot);
  useEffect(() => {
    let alive = true;
    void loadLatestMarketStatus()
      .then((latest) => alive && latest && latest.date > snapshot.date && setStatus(latest))
      .catch(() => undefined); // 읽기 실패면 스냅샷 + "N일 전" 표시로 남는다
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

  return (
    <section aria-label="시장 브리핑" className="border-t border-line/60 bg-white/70 shadow-[0_1px_0_rgb(0_0_0/0.06)]">
      <div className="mx-auto flex min-h-10 w-full max-w-[1200px] flex-wrap items-center gap-x-5 gap-y-1 px-4 py-2 sm:px-6 lg:px-8">
        {/* 연도까지 보인다: 스냅샷이 오래되면 "12.30"만으로는 오늘 값처럼 읽힌다. */}
        <span className="flex-none text-xs text-muted tabular-nums">
          {status.date.replaceAll("-", ".")} 기준{stale && <strong className="ml-1 font-medium text-ink">· {stale}</strong>}
        </span>
        {quotes.length > 0 ? (
          quotes.map((quote) => <Quote key={quote.symbol} quote={quote} />)
        ) : (
          <span className="text-xs text-muted">지수 데이터가 아직 없어요.</span>
        )}
        {real ? (
          <MarketDetail
            label={
              <>
                {/* 가운데 점 대신 간격으로 나눈다(10/18 사용자 피드백) */}
                시장 흔들림 <Level score={status.volatilityScore} />
                <span className="ml-3">거래</span> <Level score={status.volumeScore} />
                <span className="ml-1 text-muted underline underline-offset-2">자세히</span>
              </>
            }
          >
            <p className="m-0">
              흔들림: KOSPI 최근 20거래일 가격 흔들림이 지난 1년 중 아래에서 {status.volatilityScore}% 위치예요.
            </p>
            <p className="m-0 mt-1">거래: 최근 20거래일 평균 거래대금이 지난 1년 중 아래에서 {status.volumeScore}% 위치예요.</p>
            <p className="m-0 mt-2 text-muted">{meta.comment}.</p>
          </MarketDetail>
        ) : (
          <span className="flex-none whitespace-nowrap text-xs text-body lg:ml-auto">{meta.comment}</span>
        )}
        {!real && <span className="flex-none text-2xs text-muted">예시 데이터</span>}
      </div>
    </section>
  );
}
