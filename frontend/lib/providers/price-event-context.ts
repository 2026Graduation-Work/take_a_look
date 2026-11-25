import { isCalendarDate, type DisclosureWindow } from "../price-events.ts";
import { getSupabaseClient } from "../supabase.ts";
import type { Disclosure } from "./supabase-insights.ts";

export type SourceResult<T> =
  | { status: "loading" }
  | {
      status: "available";
      items: T[];
      fetchedAt: string;
      coverage: "unverified" | "known_partial";
      truncated: boolean;
      refresh: "idle" | "loading" | "failed";
    }
  | { status: "unavailable"; reason: "query_failed" | "invalid_response" | "not_configured" | "usage_not_approved" };

export type MarketMove = { date: string; changePercent: number };
export type EventDisclosure = Disclosure & { url: string | null };

const DISCLOSURE_LIMIT = 50;

const record = (value: unknown): value is Record<string, unknown> =>
  typeof value === "object" && value !== null && !Array.isArray(value);

function available<T>(items: T[], fetchedAt: string, partial = false, truncated = false): SourceResult<T> {
  return { status: "available", items, fetchedAt, coverage: partial ? "known_partial" : "unverified", truncated, refresh: "idle" };
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

export function parseEventMarket(rows: unknown, dates: string[], fetchedAt: string): Map<string, SourceResult<MarketMove>> {
  const invalid = { status: "unavailable", reason: "invalid_response" } as const;
  if (!Array.isArray(rows)) return new Map(dates.map(date => [date, invalid]));
  const hasUnexpectedRow = rows.some(row => !record(row) || !isCalendarDate(row.status_date) || !dates.includes(row.status_date));
  return new Map(dates.map((date) => {
    const matches = rows.filter((row: unknown) => record(row) && row.status_date === date);
    if (!matches.length) return [date, hasUnexpectedRow ? invalid : available<MarketMove>([], fetchedAt)];
    const quotes: unknown = matches[0].index_quotes;
    const kospi = Array.isArray(quotes) ? quotes.filter((quote: unknown) => record(quote) && quote.symbol === "KOSPI") : [];
    const change: unknown = kospi[0]?.changePercent;
    if (matches.length !== 1 || kospi.length !== 1 || typeof change !== "number" || !Number.isFinite(change)) {
      return [date, invalid];
    }
    return [date, available([{ date, changePercent: change }], fetchedAt)];
  }));
}

export async function loadEventDisclosures(code: string, window: DisclosureWindow, signal: AbortSignal): Promise<SourceResult<EventDisclosure>> {
  const client = getSupabaseClient();
  if (!client) return { status: "unavailable", reason: "not_configured" };
  if (!/^[0-9A-Z]{6}$/.test(code) || !isCalendarDate(window.from) || !isCalendarDate(window.through) ||
      window.from > window.through) return { status: "unavailable", reason: "invalid_response" };
  const { data, error } = await client.from("disclosures")
    .select("stock_code,rcept_no,title,kind,filed_on")
    .eq("stock_code", code).gte("filed_on", window.from).lte("filed_on", window.through)
    .order("filed_on", { ascending: false }).order("rcept_no", { ascending: false }).limit(DISCLOSURE_LIMIT)
    .retry(false).abortSignal(signal);
  if (error) return { status: "unavailable", reason: "query_failed" };
  return parseEventDisclosures(data, code, window, new Date().toISOString());
}

export async function loadEventMarket(dates: string[], signal: AbortSignal): Promise<Map<string, SourceResult<MarketMove>>> {
  const unavailable = (reason: "not_configured" | "invalid_response" | "query_failed"): Map<string, SourceResult<MarketMove>> =>
    new Map(dates.map(date => [date, { status: "unavailable", reason }]));
  const client = getSupabaseClient();
  if (!client) return unavailable("not_configured");
  if (!dates.length || dates.length > 3 || !dates.every(isCalendarDate)) return unavailable("invalid_response");
  const { data, error } = await client.from("market_status")
    .select("status_date,index_quotes").in("status_date", dates).limit(dates.length)
    .retry(false).abortSignal(signal);
  if (error) return unavailable("query_failed");
  return parseEventMarket(data, dates, new Date().toISOString());
}
