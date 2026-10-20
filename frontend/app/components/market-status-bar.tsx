"use client";

import { useEffect, useState } from "react";
import { changeMeta, formatSignedPercent, MARKET_CONDITION_META } from "@/lib/display";
import { loadLatestMarketStatus, staleLabel } from "@/lib/market-status";
import MarketDetail from "./market-detail";
import type { MarketIndexQuote, MarketStatus } from "@/lib/types";

// 헤더 아래 시장 브리핑: 지수 3개(등락 적/청) + 흔들림, 거래 구간. 점수 숫자는 두지 않는다.
// 기준일은 ⓘ 설명 맨 아래 줄에만 둔다(지수가 먼저, 10/20 사용자 피드백). 2영업일 넘게 밀렸을 때만 바에도 경고를 둔다
const SHOWN = new Set(["KOSPI", "KOSDAQ", "KOSPI200"]);

function formatValue(quote: MarketIndexQuote): string {
  return quote.value.toLocaleString("ko-KR", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

// 390에서는 지수 3개가 한 줄씩 쌓이므로 이름, 값, 등락을 세 칸 표로 맞춘다(값은 오른쪽 정렬). 640 이상은 한 줄에 이어 둔다
function Quote({ quote }: { quote: MarketIndexQuote }) {
  const { color, arrow } = changeMeta(quote.changePercent, 2);
  return (
    <span className="contents sm:flex sm:flex-none sm:items-baseline sm:gap-2 sm:whitespace-nowrap">
      <span className="text-xs text-muted">{quote.label}</span>
      <span className="justify-self-end text-sm font-medium tabular-nums">{formatValue(quote)}</span>
      <span className="text-xs tabular-nums" style={{ color }}>
        {arrow && `${arrow} `}{formatSignedPercent(quote.changePercent, 2)}
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
  const date = status.date.replaceAll("-", ".");

  return (
    <section aria-label="시장 브리핑" className="border-t border-line/60 bg-white/70 shadow-[0_1px_0_rgb(0_0_0/0.06)]">
      <div className="mx-auto flex min-h-10 w-full max-w-[1200px] flex-wrap items-center gap-x-5 gap-y-1 px-4 py-2 sm:px-6 lg:px-8">
        {quotes.length > 0 ? (
          <div className="grid grid-cols-[repeat(3,max-content)] items-baseline gap-x-3 gap-y-1 sm:flex sm:flex-wrap sm:gap-x-5">
            {quotes.map((quote) => <Quote key={quote.symbol} quote={quote} />)}
          </div>
        ) : (
          <span className="text-xs text-muted">지수 데이터가 아직 없어요.</span>
        )}
        {stale && <strong className="flex-none text-xs font-medium text-ink">{stale}</strong>}
        {real ? (
          <MarketDetail
            label={
              <>
                {/* 가운데 점 대신 간격으로 나눈다(10/18 사용자 피드백) */}
                시장 흔들림 <Level score={status.volatilityScore} />
                <span className="ml-3">거래</span> <Level score={status.volumeScore} />
                {/* "자세히" 글자 대신 ⓘ(누르면 열림, 화면 규칙 v2) */}
                <span aria-hidden className="ml-1 text-muted">ⓘ</span>
                <span className="sr-only">설명 보기</span>
              </>
            }
          >
            <p className="m-0">
              흔들림: KOSPI 최근 20거래일 가격 흔들림이 지난 1년 중 아래에서 {status.volatilityScore}% 위치예요.
            </p>
            <p className="m-0 mt-1">거래: 최근 20거래일 평균 거래대금이 지난 1년 중 아래에서 {status.volumeScore}% 위치예요.</p>
            <p className="m-0 mt-2 text-muted">{meta.comment}.</p>
            {/* 연도까지 보인다: 스냅샷이 오래되면 "12.30"만으로는 오늘 값처럼 읽힌다 */}
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
