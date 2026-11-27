import { kstDay } from "../display.ts";
import { isCalendarDate, type DisclosureWindow } from "../price-events.ts";
import { getSupabaseClient } from "../supabase.ts";
import type { Disclosure } from "./supabase-insights.ts";

export type SourceUnavailableReason = "query_failed" | "no_response" | "server_error" | "access_denied" |
  "rate_limited" | "timeout" | "invalid_response" | "not_configured" | "usage_not_approved";

type SourceRefresh =
  | { status: "idle" }
  | { status: "loading" }
  | { status: "failed"; reason: SourceUnavailableReason };

export type SourceResult<T> =
  | { status: "loading" }
  | {
      status: "available";
      items: T[];
      fetchedAt: string;
      coverage: "unverified" | "known_partial";
      truncated: boolean;
      emptyReason?: "no_rows" | "missing_value";
      refresh: SourceRefresh;
    }
  | { status: "unavailable"; reason: SourceUnavailableReason };

export type MarketMove = { date: string; changePercent: number };
export type EventDisclosure = Disclosure & { url: string | null };
export type EventNews = {
  id: string;
  title: string;
  press: string;
  url: string | null;
  date: string;
  publishedAt: string | null;
};

const DISCLOSURE_LIMIT = 50;
const NEWS_LIMIT = 50;
const OFFSET_TIMESTAMP = /^(\d{4}-\d{2}-\d{2})T(?:[01]\d|2[0-3]):[0-5]\d:[0-5]\d(?:\.\d+)?(?:Z|[+-](?:[01]\d|2[0-3]):[0-5]\d)$/;

const record = (value: unknown): value is Record<string, unknown> =>
  typeof value === "object" && value !== null && !Array.isArray(value);

function available<T>(items: T[], fetchedAt: string, partial = false, truncated = false): Extract<SourceResult<T>, { status: "available" }> {
  return { status: "available", items, fetchedAt, coverage: partial ? "known_partial" : "unverified", truncated, refresh: { status: "idle" } };
}

export function canRetryEventSource(reason: SourceUnavailableReason): boolean {
  return reason !== "access_denied" && reason !== "not_configured" && reason !== "usage_not_approved";
}

export function isEventNewsEnabled(): boolean {
  return process.env.NEXT_PUBLIC_PRICE_EVENT_NEWS_ENABLED === "1";
}

function readFailure(status: number, error: { code: string } | null): SourceUnavailableReason | undefined {
  if (status >= 200 && status < 300) return error ? "invalid_response" : undefined;
  if (status === 401 || status === 403 || error?.code === "42501") return "access_denied";
  if (status === 429) return "rate_limited";
  if (status >= 500 && status < 600) return "server_error";
  if (status === 0) return "no_response";
  return "query_failed";
}

export function parseEventDisclosures(rows: unknown, code: string, window: DisclosureWindow, fetchedAt: string): SourceResult<EventDisclosure> {
  if (!Array.isArray(rows)) return { status: "unavailable", reason: "invalid_response" };
  const unique = new Map<string, EventDisclosure>();
  const truncated = rows.length >= DISCLOSURE_LIMIT;
  let invalid = 0;
  for (const row of rows.slice(0, DISCLOSURE_LIMIT)) {
    if (!record(row) || row.stock_code !== code || !isCalendarDate(row.filed_on) ||
        row.filed_on < window.from || row.filed_on > window.through ||
        typeof row.rcept_no !== "string" || !row.rcept_no.trim() ||
        typeof row.title !== "string" || !row.title.trim() || typeof row.kind !== "string" || !row.kind.trim()) {
      invalid += 1;
      continue;
    }
    if (!unique.has(row.rcept_no)) {
      unique.set(row.rcept_no, {
        rceptNo: row.rcept_no,
        title: row.title.trim(),
        kind: row.kind,
        filedOn: row.filed_on,
        url: /^\d{14}$/.test(row.rcept_no)
          ? `https://dart.fss.or.kr/dsaf001/main.do?rcpNo=${row.rcept_no}`
          : null,
      });
    }
  }
  if (invalid && !unique.size) return { status: "unavailable", reason: "invalid_response" };
  const items = [...unique.values()].sort((a, b) => b.filedOn.localeCompare(a.filedOn) || b.rceptNo.localeCompare(a.rceptNo));
  return available(items, fetchedAt, invalid > 0, truncated);
}

function newsText(value: unknown): string {
  if (typeof value !== "string") return "";
  const text = value.normalize("NFC").replace(/\s+/gu, " ").trim();
  return /[\p{Cc}\uFFFD]/u.test(text) ? "" : text;
}

function newsUrl(value: unknown): string | null {
  if (typeof value !== "string" || !/^https?:\/\//i.test(value.trim())) return null;
  try {
    const url = new URL(value);
    return url.username || url.password ? null : url.href;
  } catch {
    return null;
  }
}

function isPublicationOn(value: unknown, date: string): value is string {
  if (typeof value !== "string" || !isCalendarDate(OFFSET_TIMESTAMP.exec(value)?.[1])) return false;
  const timestamp = Date.parse(value);
  return Number.isFinite(timestamp) && kstDay(timestamp) === date;
}

export function parseEventNews(rows: unknown, code: string, date: string, fetchedAt: string): SourceResult<EventNews> {
  const malformed = { status: "unavailable", reason: "invalid_response" } as const;
  if (!Array.isArray(rows) || !isCalendarDate(date)) return malformed;
  const unique = new Map<string, EventNews>();
  let invalid = 0;
  for (const row of rows.slice(0, NEWS_LIMIT)) {
    if (!record(row) || row.stock_code !== code || row.track !== "live" || row.article_date !== date ||
        typeof row.news_id !== "string" || !row.news_id.trim() ||
        (row.published_at !== null && !isPublicationOn(row.published_at, date))) {
      invalid += 1;
      continue;
    }
    const title = newsText(row.title);
    if (!title) {
      invalid += 1;
      continue;
    }
    const id = row.news_id.trim();
    if (!unique.has(id)) unique.set(id, {
      id, title, press: newsText(row.press), url: newsUrl(row.url), date, publishedAt: row.published_at,
    });
  }
  if (invalid && !unique.size) return malformed;
  const result = available([...unique.values()], fetchedAt, invalid > 0, rows.length >= NEWS_LIMIT);
  return rows.length ? result : { ...result, emptyReason: "no_rows" };
}

export function parseEventMarket(rows: unknown, dates: string[], fetchedAt: string): Map<string, SourceResult<MarketMove>> {
  const invalid = { status: "unavailable", reason: "invalid_response" } as const;
  if (!Array.isArray(rows)) return new Map(dates.map(date => [date, invalid]));
  const hasUnexpectedRow = rows.some(row => !record(row) || !isCalendarDate(row.status_date) || !dates.includes(row.status_date));
  return new Map(dates.map((date): [string, SourceResult<MarketMove>] => {
    const matches = rows.filter((row: unknown) => record(row) && row.status_date === date);
    if (!matches.length) {
      return [date, hasUnexpectedRow ? invalid : { ...available<MarketMove>([], fetchedAt), emptyReason: "no_rows" }];
    }
    const quotes: unknown = matches[0].index_quotes;
    if (matches.length !== 1 || !Array.isArray(quotes)) return [date, invalid];
    const kospi = quotes.filter((quote: unknown) => record(quote) && quote.symbol === "KOSPI");
    if (kospi.length > 1) return [date, invalid];
    const change: unknown = kospi[0]?.changePercent;
    if (change === undefined || change === null) {
      const unknownSymbol = quotes.some((quote: unknown) => !record(quote) ||
        typeof quote.symbol !== "string" || !quote.symbol.trim() || quote.symbol.trim() !== quote.symbol);
      if (unknownSymbol) return [date, invalid];
      return [date, { ...available<MarketMove>([], fetchedAt), emptyReason: "missing_value" }];
    }
    if (typeof change !== "number" || !Number.isFinite(change)) return [date, invalid];
    return [date, available([{ date, changePercent: change }], fetchedAt)];
  }));
}

export async function loadEventDisclosures(code: string, window: DisclosureWindow, signal: AbortSignal): Promise<SourceResult<EventDisclosure>> {
  const client = getSupabaseClient();
  if (!client) return { status: "unavailable", reason: "not_configured" };
  if (!/^[0-9A-Z]{6}$/.test(code) || !isCalendarDate(window.from) || !isCalendarDate(window.through) ||
      window.from > window.through) return { status: "unavailable", reason: "invalid_response" };
  const { data, error, status } = await client.from("disclosures")
    .select("stock_code,rcept_no,title,kind,filed_on")
    .eq("stock_code", code).gte("filed_on", window.from).lte("filed_on", window.through)
    .order("filed_on", { ascending: false }).order("rcept_no", { ascending: false }).limit(DISCLOSURE_LIMIT)
    .retry(false).abortSignal(signal);
  const reason = readFailure(status, error);
  if (reason) return { status: "unavailable", reason };
  return parseEventDisclosures(data, code, window, new Date().toISOString());
}

export async function loadEventNews(code: string, date: string, signal: AbortSignal): Promise<SourceResult<EventNews>> {
  if (!isEventNewsEnabled()) return { status: "unavailable", reason: "usage_not_approved" };
  if (!/^[0-9A-Z]{6}$/.test(code) || !isCalendarDate(date)) return { status: "unavailable", reason: "invalid_response" };
  const client = getSupabaseClient();
  if (!client) return { status: "unavailable", reason: "not_configured" };
  const { data, error, status } = await client.from("news_articles")
    .select("stock_code,track,news_id,title,press,url,article_date,published_at")
    .eq("stock_code", code).eq("track", "live").eq("article_date", date)
    .order("published_at", { ascending: false, nullsFirst: false }).order("news_id").limit(NEWS_LIMIT)
    .retry(false).abortSignal(signal);
  const reason = readFailure(status, error);
  if (reason) return { status: "unavailable", reason };
  return parseEventNews(data, code, date, new Date().toISOString());
}

export async function loadEventMarket(dates: string[], signal: AbortSignal): Promise<Map<string, SourceResult<MarketMove>>> {
  const unavailable = (reason: SourceUnavailableReason): Map<string, SourceResult<MarketMove>> =>
    new Map(dates.map(date => [date, { status: "unavailable", reason }]));
  const client = getSupabaseClient();
  if (!client) return unavailable("not_configured");
  if (!dates.length || dates.length > 3 || !dates.every(isCalendarDate)) return unavailable("invalid_response");
  const { data, error, status } = await client.from("market_status")
    .select("status_date,index_quotes").in("status_date", dates).limit(dates.length)
    .retry(false).abortSignal(signal);
  const reason = readFailure(status, error);
  if (reason) return unavailable(reason);
  return parseEventMarket(data, dates, new Date().toISOString());
}
