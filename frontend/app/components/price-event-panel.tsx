"use client";

import { useState, type ReactNode } from "react";
import { DISCLOSURE_KIND } from "@/lib/copy-glossary";
import { formatKstDateTime, formatSignedPercent } from "@/lib/display";
import { PRICE_EVENT_MULTIPLIER } from "@/lib/price-events";
import type { SourceResult } from "@/lib/providers/price-event-context";
import type { usePriceEvents } from "@/lib/use-price-events";

type PriceEvents = ReturnType<typeof usePriceEvents>;

function SourceDetails<T>({ source, retry, children }: {
  source: SourceResult<T>;
  retry?: () => void;
  children: (items: T[]) => ReactNode;
}) {
  const unavailable = source.status === "unavailable";
  return (
    <>
      {source.status === "loading" && <p className="m-0 text-sm text-muted">자료를 불러오는 중이에요.</p>}
      {source.status === "available" && children(source.items)}
      {unavailable && <p className="m-0 text-sm text-muted">
        {source.reason === "usage_not_approved" || source.reason === "not_configured"
          ? "이 자료는 지금 제공하지 않아요."
          : "자료를 불러오지 못했어요."}
      </p>}
      {source.status === "available" && source.refresh === "loading" && <p className="m-0 text-xs text-muted">새로 확인하는 중이에요.</p>}
      {source.status === "available" && source.refresh === "failed" && <p className="m-0 text-xs text-muted">이전 조회 자료예요.</p>}
      {retry && (
        (unavailable && (source.reason === "query_failed" || source.reason === "invalid_response")) ||
        (source.status === "available" && source.refresh === "failed")
      ) && <button type="button" onClick={retry} className="min-h-11 self-start text-sm text-ink underline underline-offset-4">다시 확인</button>}
    </>
  );
}

function DisclosureItems({ source }: {
  source: Extract<NonNullable<PriceEvents["context"]>["disclosures"], { status: "available" }>;
}) {
  const { items, coverage, truncated } = source;
  const [expanded, setExpanded] = useState(false);
  return (
    <>
      {items.length === 0 && <p className="m-0 text-sm text-body">이 기간에 수집된 공시가 없어요.</p>}
      {items.length > 0 && <ul className="m-0 list-none p-0">
        {(expanded ? items : items.slice(0, 3)).map(item => (
          <li key={item.rceptNo} className="flex flex-col gap-1 py-2">
            {item.url
              ? <a href={item.url} target="_blank" rel="noopener noreferrer" className="min-h-11 content-center text-sm text-ink underline underline-offset-4 [overflow-wrap:anywhere]">{item.title}</a>
              : <span className="text-sm text-ink [overflow-wrap:anywhere]">{item.title}</span>}
            <p className="m-0 flex flex-wrap gap-x-3 text-xs text-muted">
              <time dateTime={item.filedOn}>{formatKstDateTime(item.filedOn)}</time>
              <span>{DISCLOSURE_KIND[item.kind]?.label ?? DISCLOSURE_KIND.other.label}</span>
            </p>
          </li>
        ))}
      </ul>}
      {!expanded && items.length > 3 && <button type="button" onClick={() => setExpanded(true)}
        className="min-h-11 self-start text-sm text-ink underline underline-offset-4">더 보기({items.length - 3})</button>}
      {coverage === "unverified" && <p className="m-0 text-xs text-muted">
        수집 범위를 확인하지 못했어요.{items.length > 0 && " 조회된 자료만 표시해요."}
      </p>}
      {coverage === "known_partial" && <p className="m-0 text-xs text-muted">형식이 맞지 않는 자료를 제외해 일부 자료만 표시해요.</p>}
      {truncated && <p className="m-0 text-xs text-muted">조회 한도에 도달했어요. 일부 자료만 표시해요.</p>}
    </>
  );
}

export default function PriceEventPanel({ events }: { events: PriceEvents }) {
  const { basis, result, moves, move, context, select, retry } = events;
  return (
    <section aria-labelledby="price-events-title" className="flex min-w-0 flex-col gap-6">
      <div className="flex flex-col gap-2">
        <h3 id="price-events-title" className="m-0 text-xl font-semibold">가격이 크게 움직인 날</h3>
        {result.status === "unavailable" && <p className="m-0 text-sm text-muted">변동일을 확인할 가격 자료가 부족해요.</p>}
        {result.status === "ready" && !moves.length && <p className="m-0 text-sm text-body">기준을 넘은 날이 없어요.</p>}
        {move && context && (
          <div role="group" aria-label="변동일 선택" className="flex flex-wrap gap-x-4">
            {moves.map(item => (
              <button type="button" key={item.date} aria-pressed={item.date === move.date} onClick={() => select(item.date)}
                className="min-h-11 text-sm tabular-nums text-muted aria-pressed:font-semibold aria-pressed:text-ink aria-pressed:underline aria-pressed:underline-offset-4">
                {formatKstDateTime(item.date)}
              </button>
            ))}
          </div>
        )}
      </div>
      {move && context && <>
        <div className="flex flex-col gap-2">
          <p aria-live="polite" aria-atomic="true" className="m-0 flex flex-wrap gap-x-4 gap-y-1 text-sm tabular-nums text-ink">
            <time dateTime={move.date}>{formatKstDateTime(move.date)}</time>
            <strong>종목 {formatSignedPercent(move.changePercent, 2)}</strong>
          </p>
          <section aria-label="같은 날 코스피" className="flex flex-col gap-2">
            <SourceDetails source={context.market} retry={() => retry("market", move.date)}>
              {items => <p className="m-0 text-sm tabular-nums text-body">코스피 {items.length ? formatSignedPercent(items[0].changePercent, 2) : "미제공"}</p>}
            </SourceDetails>
          </section>
          <p className="m-0 text-xs text-muted">날짜가 가까운 자료를 함께 보고 있어요. 가격이 움직인 이유는 이 자료만으로 알 수 없어요.</p>
        </div>
        <div className="grid min-w-0 gap-6 lg:grid-cols-2">
          <section aria-label="앞뒤 거래일에 나온 공시" className="flex min-w-0 flex-col gap-2">
            <h4 className="m-0 text-base font-semibold">앞뒤 거래일에 나온 공시</h4>
            <p className="m-0 text-xs tabular-nums text-muted">{formatKstDateTime(context.disclosureWindow.from)} ~ {formatKstDateTime(context.disclosureWindow.through)}</p>
            {context.disclosureWindow.endReason === "snapshot_boundary" && <p className="m-0 text-xs text-muted">차트 기준일까지 나온 자료만 확인했어요.</p>}
            <SourceDetails source={context.disclosures} retry={() => retry("disclosures", move.date)}>
              {() => context.disclosures.status === "available" && <DisclosureItems key={move.date} source={context.disclosures} />}
            </SourceDetails>
          </section>
          <section aria-label="이날 뉴스" className="flex flex-col gap-2">
            <h4 className="m-0 text-base font-semibold">이날 뉴스</h4>
            <SourceDetails source={context.news}>{() => null}</SourceDetails>
          </section>
        </div>
      </>}
      {basis && result.status === "ready" && <details className="disclosure">
        <summary>계산 근거</summary>
        <div className="flex flex-col gap-2 text-xs text-muted">
          <p className="m-0">수정종가로 전 거래일 대비 등락률을 계산했어요. 최근 거래일 중 {result.evaluatedDays}일을 비교했어요.
            {result.excludedDays > 0 && ` 거래량 또는 직전 가격 자료가 부족한 ${result.excludedDays}일은 제외했어요.`}</p>
          <p className="m-0">{formatKstDateTime(basis.periodStart)} ~ {formatKstDateTime(basis.periodEnd)}의 일간 로그수익률 {basis.returnCount}개로 표본 표준편차를 구했어요.
            평소 하루 변동 폭({(basis.dailySigma * 100).toFixed(2)}%)의 {PRICE_EVENT_MULTIPLIER}배를 넘은 날 중 등락 폭이 큰 최대 3일을 표시해요.</p>
          {context && <p className="m-0">코스피 자료는 KRX, 공시 자료는 금융감독원 전자공시(DART)에서 가져와요.</p>}
        </div>
      </details>}
    </section>
  );
}
