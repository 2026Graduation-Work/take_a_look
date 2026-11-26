"use client";

import { useRef, useState, type ReactNode } from "react";
import { DISCLOSURE_KIND } from "@/lib/copy-glossary";
import { formatKstDateTime, formatSignedPercent } from "@/lib/display";
import { priceEventSourceMessages, priceMoveMessages, type EventSource } from "@/lib/price-event-messages";
import { PRICE_EVENT_MULTIPLIER } from "@/lib/price-events";
import type { SourceResult } from "@/lib/providers/price-event-context";
import type { usePriceEvents } from "@/lib/use-price-events";

type PriceEvents = ReturnType<typeof usePriceEvents>;

const sourceStatusLabels: Record<EventSource, string> = {
  market: "코스피 조회 상태",
  disclosures: "공시 조회 상태",
  news: "뉴스 조회 상태",
};

function SourceDetails<T>({ name, source, retry, children }: {
  name: EventSource;
  source: SourceResult<T>;
  retry?: () => void;
  children: (items: T[]) => ReactNode;
}) {
  const announcement = useRef<HTMLDivElement>(null);
  const { message, coverageNote, refreshNote, lastCheckedAt, canRetry } = priceEventSourceMessages(name, source);
  const items = source.status === "available" && source.items.length > 0 ? children(source.items) : null;
  return (
    <>
      {name !== "market" && items}
      <div ref={announcement} role="status" aria-label={sourceStatusLabels[name]} aria-live="polite" aria-atomic="true"
        tabIndex={-1} className="flex flex-col gap-2">
        {name === "market" && items}
        {message && <p className="m-0 text-sm text-muted">{message}</p>}
        {coverageNote && <p className="m-0 text-xs text-muted">{coverageNote}</p>}
        {refreshNote && <p className="m-0 text-xs text-muted">{refreshNote}</p>}
        {lastCheckedAt && <p className="m-0 text-xs text-muted">
          마지막 확인 <time dateTime={lastCheckedAt}>{formatKstDateTime(lastCheckedAt)}</time>
        </p>}
      </div>
      {retry && canRetry && <button type="button" onClick={() => {
        announcement.current?.focus();
        retry();
      }} className="min-h-11 self-start text-sm text-ink underline underline-offset-4">다시 확인</button>}
    </>
  );
}

function DisclosureItems({ items }: {
  items: Extract<NonNullable<PriceEvents["context"]>["disclosures"], { status: "available" }>["items"];
}) {
  const [expanded, setExpanded] = useState(false);
  return (
    <>
      <ul className="m-0 list-none p-0">
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
      </ul>
      {!expanded && items.length > 3 && <button type="button" onClick={() => setExpanded(true)}
        className="min-h-11 self-start text-sm text-ink underline underline-offset-4">더 보기({items.length - 3})</button>}
    </>
  );
}

export default function PriceEventPanel({ events }: { events: PriceEvents }) {
  const { basis, result, moves, move, context, select, retry } = events;
  const { message, coverageNote } = priceMoveMessages(result);
  return (
    <section aria-labelledby="price-events-title" className="flex min-w-0 flex-col gap-6">
      <div className="flex flex-col gap-2">
        <h3 id="price-events-title" className="m-0 text-xl font-semibold">가격이 크게 움직인 날</h3>
        {message && <p className="m-0 text-sm text-muted">{message}</p>}
        {coverageNote && <p className="m-0 text-xs text-muted">{coverageNote}</p>}
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
            <SourceDetails name="market" source={context.market} retry={() => retry("market", move.date)}>
              {items => <p className="m-0 text-sm tabular-nums text-body">코스피 {formatSignedPercent(items[0].changePercent, 2)}</p>}
            </SourceDetails>
          </section>
          <p className="m-0 text-xs text-muted">날짜가 가까운 자료를 함께 보고 있어요. 가격이 움직인 이유는 이 자료만으로 알 수 없어요.</p>
        </div>
        <div className="grid min-w-0 gap-6 lg:grid-cols-2">
          <section aria-label="앞뒤 거래일에 나온 공시" className="flex min-w-0 flex-col gap-2">
            <h4 className="m-0 text-base font-semibold">앞뒤 거래일에 나온 공시</h4>
            <p className="m-0 text-xs tabular-nums text-muted">{formatKstDateTime(context.disclosureWindow.from)} ~ {formatKstDateTime(context.disclosureWindow.through)}</p>
            {context.disclosureWindow.endReason === "snapshot_boundary" && <p className="m-0 text-xs text-muted">차트 기준일까지 나온 자료만 확인했어요.</p>}
            <SourceDetails name="disclosures" source={context.disclosures} retry={() => retry("disclosures", move.date)}>
              {items => <DisclosureItems key={move.date} items={items} />}
            </SourceDetails>
          </section>
          <section aria-label="이날 뉴스" className="flex flex-col gap-2">
            <h4 className="m-0 text-base font-semibold">이날 뉴스</h4>
            <SourceDetails name="news" source={context.news}>{() => null}</SourceDetails>
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
