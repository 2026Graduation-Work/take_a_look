"use client";

import { useRef, useState, type ReactNode } from "react";
import { DISCLOSURE_KIND } from "@/lib/copy-glossary";
import { changeMeta, formatKstDateTime, formatSignedPercent } from "@/lib/display";
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
        {message && <p className="m-0 text-xs text-muted">{message}</p>}
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

type EventItem = { id: string; title: string; url: string | null; date: string; detail: string };

function EventItems({ items }: { items: EventItem[] }) {
  const [expanded, setExpanded] = useState(false);
  return (
    <>
      <ul className="m-0 list-none p-0">
        {(expanded ? items : items.slice(0, 3)).map(item => (
          <li key={item.id} className="flex flex-col gap-1 py-2">
            {item.url
              ? <a href={item.url} target="_blank" rel="noopener noreferrer" className="min-h-11 content-center text-sm text-ink underline underline-offset-4 [overflow-wrap:anywhere]">{item.title}</a>
              : <span className="text-sm text-ink [overflow-wrap:anywhere]">{item.title}</span>}
            <p className="m-0 flex flex-wrap gap-x-3 text-xs text-muted">
              <time dateTime={item.date}>{formatKstDateTime(item.date)}</time>
              {item.detail && <span>{item.detail}</span>}
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
  const { basis, result, move, context, retry } = events;
  if (!move || !context) return null;
  const { coverageNote } = priceMoveMessages(result);

  return (
    <div className="flex min-w-0 flex-col gap-3">
      <p aria-live="polite" aria-atomic="true" className="m-0 flex flex-wrap items-baseline gap-x-3 text-sm tabular-nums text-ink">
        <time dateTime={move.date}>{formatKstDateTime(move.date)}</time>
        <strong className="font-semibold">종목 <span style={{ color: changeMeta(move.changePercent, 2).color }}>{formatSignedPercent(move.changePercent, 2)}</span></strong>
      </p>
      <section aria-label="같은 날 코스피">
        <SourceDetails name="market" source={context.market} retry={() => retry("market", move.date)}>
          {items => <p className="m-0 text-xs tabular-nums text-body">코스피 <span style={{ color: changeMeta(items[0].changePercent, 2).color }}>{formatSignedPercent(items[0].changePercent, 2)}</span></p>}
        </SourceDetails>
      </section>
      <section aria-label="앞뒤 거래일에 나온 공시" className="flex min-w-0 flex-col gap-1">
        <h4 className="m-0 text-sm font-semibold">앞뒤 거래일 공시</h4>
        <p className="m-0 text-xs tabular-nums text-muted">{formatKstDateTime(context.disclosureWindow.from)} ~ {formatKstDateTime(context.disclosureWindow.through)}</p>
        {context.disclosureWindow.endReason === "snapshot_boundary" && <p className="m-0 text-xs text-muted">차트 기준일까지 나온 자료만 확인했어요.</p>}
        <SourceDetails name="disclosures" source={context.disclosures} retry={() => retry("disclosures", move.date)}>
          {items => <EventItems key={move.date} items={items.map(item => ({
            id: item.rceptNo, title: item.title, url: item.url, date: item.filedOn,
            detail: DISCLOSURE_KIND[item.kind]?.label ?? DISCLOSURE_KIND.other.label,
          }))} />}
        </SourceDetails>
      </section>
      <section aria-label="이날 뉴스" className="flex min-w-0 flex-col gap-1">
        <h4 className="m-0 text-sm font-semibold">이날 뉴스</h4>
        <SourceDetails name="news" source={context.news} retry={() => retry("news", move.date)}>
          {items => <EventItems key={move.date} items={items.map(item => ({
            id: item.id, title: item.title, url: item.url, date: item.publishedAt ?? item.date, detail: item.press || "언론사 미상",
          }))} />}
        </SourceDetails>
      </section>
      <div className="flex flex-col gap-1 text-xs text-muted">
        <p className="m-0">가격이 움직인 이유는 이 자료만으로 알 수 없어요.</p>
        {basis && <p className="m-0">수정종가 등락 폭이 평소 하루 변동 폭({(basis.dailySigma * 100).toFixed(2)}%)의 {PRICE_EVENT_MULTIPLIER}배를 넘은 날 중 등락 폭이 큰 최대 3일을 표시해요.</p>}
        {coverageNote && <p className="m-0">{coverageNote}</p>}
        <p className="m-0">코스피 KRX, 공시 DART{context.news.status === "available" && ", 뉴스 NewsAPI.ai"}</p>
      </div>
    </div>
  );
}
