"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { selectPriceMoves, type DisclosureWindow } from "./price-events.ts";
import { canRetryEventSource, isEventNewsEnabled, loadEventDisclosures, loadEventMarket, loadEventNews, type EventDisclosure, type EventNews, type MarketMove, type SourceResult, type SourceUnavailableReason } from "./providers/price-event-context.ts";
import type { ChartSnapshot } from "./chart-public.ts";

const LOADING = { status: "loading" } as const;
const QUERY_FAILED = { status: "unavailable", reason: "query_failed" } as const;
const NEWS_DISABLED = { status: "unavailable", reason: "usage_not_approved" } as const;

type Requests = {
  stockCode: string;
  dates: string[];
  windows: Record<string, DisclosureWindow>;
};
type ContextRows = {
  market: Map<string, SourceResult<MarketMove>>;
  disclosures: Map<string, SourceResult<EventDisclosure>>;
  news: Map<string, SourceResult<EventNews>>;
};
type ContextSession = {
  key: string;
  refresh: () => void;
  retry: (source: keyof ContextRows, date: string) => void;
  dispose: () => void;
};

const disclosureKey = ({ from, through }: DisclosureWindow) => `${from}/${through}`;

function createSession(key: string, { stockCode, dates, windows }: Requests, publish: (rows: ContextRows) => void): ContextSession {
  const rows: ContextRows = { market: new Map(), disclosures: new Map(), news: new Map() };
  const pending = new Map<string, number>();
  const queue: Array<() => Promise<void>> = [];
  const active = new Set<AbortController>();
  let disposed = false;
  let sequence = 0;
  let running = 0;

  const emit = () => publish({ market: new Map(rows.market), disclosures: new Map(rows.disclosures), news: new Map(rows.news) });
  const runNext = () => {
    while (!disposed && running < 4 && queue.length) {
      const task = queue.shift()!;
      running += 1;
      void task().finally(() => {
        running -= 1;
        runNext();
      });
    }
  };

  function enqueue<T>(source: keyof ContextRows, table: Map<string, SourceResult<T>>, requested: string[],
    read: (keys: string[], signal: AbortSignal) => Promise<Map<string, SourceResult<T>>>) {
    const keys = requested.filter(id => {
      if (pending.has(`${source}:${id}`)) return false;
      const last = table.get(id);
      if (last?.status === "unavailable") return canRetryEventSource(last.reason);
      if (last?.status === "available" && last.refresh.status === "failed") return canRetryEventSource(last.refresh.reason);
      return true;
    });
    if (!keys.length) return;
    const attempt = ++sequence;
    const previous = new Map(keys.map(id => [id, table.get(id)]));
    for (const id of keys) {
      pending.set(`${source}:${id}`, attempt);
      const last = previous.get(id);
      table.set(id, last?.status === "available" ? { ...last, refresh: { status: "loading" } } : LOADING);
    }
    emit();

    queue.push(async () => {
      const controller = new AbortController();
      active.add(controller);
      let timer: number | undefined;
      const aborted = new Promise<SourceUnavailableReason>(resolve => {
        controller.signal.addEventListener("abort", () => resolve("query_failed"), { once: true });
        timer = window.setTimeout(() => {
          resolve("timeout");
          controller.abort();
        }, 10_000);
      });
      let results: Map<string, SourceResult<T>> | SourceUnavailableReason;
      try {
        results = await Promise.race([read(keys, controller.signal), aborted]);
      } catch {
        results = "query_failed";
      } finally {
        window.clearTimeout(timer);
        active.delete(controller);
      }
      if (disposed) return;

      for (const id of keys) {
        const requestKey = `${source}:${id}`;
        if (pending.get(requestKey) !== attempt) continue;
        pending.delete(requestKey);
        const next = typeof results === "string"
          ? { status: "unavailable" as const, reason: results }
          : results.get(id) ?? QUERY_FAILED;
        const last = previous.get(id);
        table.set(id, next.status === "unavailable" && last?.status === "available"
          ? { ...last, refresh: { status: "failed", reason: next.reason } }
          : next);
      }
      emit();
    });
    runNext();
  }

  const queryMarket = (selected: string[]) => enqueue("market", rows.market, selected, loadEventMarket);
  const queryDisclosures = (window: DisclosureWindow) => {
    const id = disclosureKey(window);
    enqueue("disclosures", rows.disclosures, [id], async (_, signal) =>
      new Map([[id, await loadEventDisclosures(stockCode, window, signal)]]));
  };
  const queryNews = (date: string) => {
    if (!isEventNewsEnabled()) return;
    enqueue("news", rows.news, [date], async (_, signal) =>
      new Map([[date, await loadEventNews(stockCode, date, signal)]]));
  };
  return {
    key,
    refresh() {
      if (disposed) return;
      queryMarket(dates);
      for (const window of Object.values(windows)) queryDisclosures(window);
      for (const date of dates) queryNews(date);
    },
    retry(source, date) {
      if (disposed || !windows[date]) return;
      if (source === "market") queryMarket([date]);
      else if (source === "disclosures") queryDisclosures(windows[date]);
      else queryNews(date);
    },
    dispose() {
      disposed = true;
      queue.length = 0;
      for (const controller of active) controller.abort();
    },
  };
}

export function usePriceEvents(chart: ChartSnapshot | undefined, chartRevision: number) {
  const eventBasis = chart?.prices.eventBasis;
  const basis = eventBasis?.status === "available" ? eventBasis.basis : undefined;
  const result = useMemo(() => {
    if (!chart) return selectPriceMoves([], undefined, "");
    const eventBasis = chart.prices.eventBasis;
    return eventBasis.status === "unavailable" ? eventBasis
      : selectPriceMoves(chart.prices.history, eventBasis.basis, chart.data_asof);
  }, [chart]);
  const moves = result.status === "ready" ? result.moves : [];
  const stockCode = chart?.stock_code ?? "";
  const key = chart && moves.length ? JSON.stringify([
    stockCode, chart.batch_id, chart.data_asof, moves.map(move => [move.date, move.disclosureWindow]),
  ]) : "";
  const [selected, setSelected] = useState<{ stockCode: string; date: string } | null>(null);
  if (chart && selected && (selected.stockCode !== stockCode || !moves.some(item => item.date === selected.date))) {
    setSelected(null);
  }
  const move = (selected?.stockCode === stockCode && moves.find(item => item.date === selected.date)) || moves[0];
  const [data, setData] = useState<{ key: string; rows: ContextRows } | null>(null);
  const session = useRef<ContextSession | null>(null);
  if (data && data.key !== key) setData(null);

  useEffect(() => {
    if (!key) return;
    const [stockCode, , , ranges] = JSON.parse(key) as [string, string, string, Array<[string, DisclosureWindow]>];
    const runtime = createSession(key, {
      stockCode,
      dates: ranges.map(([date]) => date),
      windows: Object.fromEntries(ranges),
    }, rows => setData({ key, rows }));
    session.current = runtime;
    return () => {
      runtime.dispose();
      session.current = null;
    };
  }, [key]);

  useEffect(() => {
    const runtime = session.current;
    // Defer initial publication until after the effect and its strict-mode cleanup.
    if (runtime?.key === key) queueMicrotask(runtime.refresh);
  }, [key, chartRevision]);

  const rows = data?.key === key ? data.rows : null;
  const context = move && chart ? {
    stockCode,
    batchId: chart.batch_id,
    dataAsOf: chart.data_asof,
    date: move.date,
    disclosureWindow: move.disclosureWindow,
    market: rows?.market.get(move.date) ?? LOADING,
    disclosures: rows?.disclosures.get(disclosureKey(move.disclosureWindow)) ?? LOADING,
    news: isEventNewsEnabled() ? rows?.news.get(move.date) ?? LOADING : NEWS_DISABLED,
  } : null;

  return {
    basis, result, moves, move, context,
    select: (date: string) => {
      if (moves.some(item => item.date === date)) setSelected({ stockCode, date });
    },
    retry: (source: keyof ContextRows, date: string) => {
      if (session.current?.key === key) session.current.retry(source, date);
    },
  };
}
