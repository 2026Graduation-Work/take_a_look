import type { SupabaseClient } from "@supabase/supabase-js";
import type {
  FinancialMetric,
  FinancialSnapshot,
  Headline,
  NewsTrackCoverage,
  NewsTrackStatus,
  SentimentData,
} from "./index.ts";

export type InsightQueryClient = Pick<SupabaseClient, "from">;

export interface LiveSentimentSummary {
  score: number;
  scoreStd: number | null;
  articleCount: number;
  publisherCount: number;
  status: NewsTrackStatus;
  asOf: string;
  windowStart: string;
  windowEnd: string;
  coverage: NewsTrackCoverage;
}

export interface SupabaseSentimentResult {
  historical: SentimentData | null;
  live: LiveSentimentSummary | null;
  headlines: Headline[];
}

type QueryResult = { data: unknown; error: { message?: string } | null };

interface TrackRow {
  track: "historical" | "live";
  source: "bigkinds" | "newsapi_ai";
  backend: string;
  status: NewsTrackStatus;
  as_of: string;
  window_start: string;
  window_end: string;
  sentiment_mean: number | null;
  sentiment_std: number | null;
  article_count: number;
  publisher_count: number;
  fetched_count: number;
  relevant_count: number;
  newest_published_at: string | null;
  lag_minutes: number | null;
  provider_total_results: number | null;
  provider_returned_count: number | null;
  provider_pages: number | null;
  provider_truncated: boolean;
}

const FINANCIAL_LABEL: Record<string, string> = {
  per: "PER",
  pbr: "PBR",
  roe: "ROE",
  operating_margin: "영업이익률",
  debt_ratio: "부채비율",
  revenue_growth: "매출 증가율(전년 대비)",
};

// DART fs_div 코드 → 화면 말. 정적 스냅샷(demo-snapshot.ts)은 이미 "연결"·"별도"로 저장돼 있다.
const STATEMENT_LABEL: Record<string, string> = { CFS: "연결", OFS: "별도" };

const METRIC_KEYS = Object.keys(FINANCIAL_LABEL);
const REPRESENTATIVE_TITLE_TERMS: Record<string, string[]> = {
  "005930": ["삼성전자"],
  "005380": ["현대차", "현대자동차"],
  "035720": ["카카오"],
  "068270": ["셀트리온"],
};

interface ArticleRow {
  title: string;
  press: string | null;
  url?: string;
  article_date: string;
  published_at: string | null;
  event_id?: string | null;
}

function cleanDisplayText(value: string | null | undefined): string {
  return (value ?? "").normalize("NFC").replace(/\s+/gu, " ").trim();
}

function hasBrokenCharacters(value: string): boolean {
  return value.includes("\uFFFD") || /[\u0000-\u001F]/u.test(value);
}

function publisherDomain(url: string | undefined): string {
  if (!url || !/^https?:\/\//i.test(url)) return "";
  try {
    return new URL(url).hostname.replace(/^www\./, "");
  } catch {
    return "";
  }
}

function verifiedStoredDomain(press: string | null): string {
  const candidate = cleanDisplayText(press).replace(/^www\./i, "").toLowerCase();
  const domainLabel = "[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?";
  return new RegExp(`^${domainLabel}(?:\\.${domainLabel})+$`, "i").test(candidate) ? candidate : "";
}

function displayPublisher(url: string | undefined, press: string | null): string {
  return publisherDomain(url) || verifiedStoredDomain(press) || "언론사 미상";
}

function articleEventKey(article: ArticleRow): string {
  const eventId = cleanDisplayText(article.event_id);
  if (eventId) return `event:${eventId}`;
  return `title:${cleanDisplayText(article.title).replace(/[^0-9A-Za-zㄱ-힝]/gu, "").toLowerCase()}`;
}

function selectRepresentativeHeadlines(code: string, rows: ArticleRow[]): Headline[] {
  const terms = REPRESENTATIVE_TITLE_TERMS[code] ?? [];
  const candidates = rows
    .map((article) => ({ ...article, title: cleanDisplayText(article.title) }))
    .filter(({ title }) => title && !hasBrokenCharacters(title));
  const direct = candidates.filter(({ title }) => terms.some((term) => title.includes(term)));
  const indirect = candidates.filter(({ title }) => !terms.some((term) => title.includes(term)));
  const selected: Array<ArticleRow & { press: string }> = [];
  const seenEvents = new Set<string>();
  const seenPublishers = new Set<string>();

  const addCandidates = (pool: ArticleRow[], requireNewPublisher: boolean) => {
    for (const article of pool) {
      if (selected.length >= 3) break;
      const eventKey = articleEventKey(article);
      const press = displayPublisher(article.url, article.press);
      if (seenEvents.has(eventKey) || (requireNewPublisher && seenPublishers.has(press))) continue;
      selected.push({ ...article, press });
      seenEvents.add(eventKey);
      seenPublishers.add(press);
    }
  };
  addCandidates(direct, true);
  addCandidates(direct, false);
  addCandidates(indirect, true);
  addCandidates(indirect, false);

  return selected.map(({ article_date, title, press, url, published_at }) => ({
    date: article_date,
    title,
    press,
    // DB 값이 그대로 href가 되므로 http(s)만 링크로 쓴다.
    url: url && /^https?:\/\//.test(url) ? url : undefined,
    publishedAt: published_at ?? undefined,
  }));
}

function unwrap(result: QueryResult, table: string): unknown {
  if (result.error) throw new Error(`${table}: ${result.error.message ?? "query failed"}`);
  return result.data;
}

function coverage(row: TrackRow): NewsTrackCoverage {
  return {
    fetched_count: row.fetched_count,
    relevant_count: row.relevant_count,
    publisher_count: row.publisher_count,
    newest_published_at: row.newest_published_at,
    lag_minutes: row.lag_minutes,
    provider_total_results: row.provider_total_results,
    provider_returned_count: row.provider_returned_count,
    provider_pages: row.provider_pages,
    provider_truncated: row.provider_truncated,
  };
}

export async function loadSupabaseSentiment(
  code: string,
  client: InsightQueryClient,
): Promise<SupabaseSentimentResult> {
  const tracksResult = await client
    .from("news_sentiment_tracks")
    .select("*")
    .eq("stock_code", code) as QueryResult;
  const dailyResult = await client
    .from("news_sentiment_daily")
    .select("sentiment_date,status,sentiment_mean,sentiment_std,article_count,publisher_count")
    .eq("stock_code", code)
    .eq("track", "historical")
    .not("sentiment_mean", "is", null)
    .order("sentiment_date", { ascending: false })
    .limit(20) as QueryResult;
  const articleResult = await client
    .from("news_articles")
    .select("news_id,title,press,url,article_date,published_at,event_id")
    .eq("stock_code", code)
    .eq("track", "live")
    .order("published_at", { ascending: false, nullsFirst: false })
    .order("news_id", { ascending: true })
    .limit(25) as QueryResult;

  const tracks = (unwrap(tracksResult, "news_sentiment_tracks") ?? []) as TrackRow[];
  const daily = (unwrap(dailyResult, "news_sentiment_daily") ?? []) as Array<{
    sentiment_date: string;
    sentiment_mean: number | null;
    article_count: number;
  }>;
  const articles = (unwrap(articleResult, "news_articles") ?? []) as ArticleRow[];
  const historicalTrack = tracks.find(({ track }) => track === "historical");
  const liveTrack = tracks.find(({ track }) => track === "live");
  const days = daily
    .filter(({ sentiment_mean }) => sentiment_mean !== null)
    .slice(0, 20)
    .map(({ sentiment_date, sentiment_mean, article_count }) => ({
      date: sentiment_date,
      score: sentiment_mean as number,
      articleCount: article_count,
    }))
    .sort((left, right) => left.date.localeCompare(right.date));
  const headlines = selectRepresentativeHeadlines(code, articles);

  return {
    historical: historicalTrack && days.length
      ? {
          days,
          headlines,
          source: "real",
          track: "historical",
          provider: "bigkinds",
          backend: historicalTrack.backend,
          status: historicalTrack.status,
          asOf: historicalTrack.as_of,
          coverage: coverage(historicalTrack),
        }
      : null,
    live: liveTrack && liveTrack.sentiment_mean !== null
      ? {
          score: liveTrack.sentiment_mean,
          scoreStd: liveTrack.sentiment_std,
          articleCount: liveTrack.article_count,
          publisherCount: liveTrack.publisher_count,
          status: liveTrack.status,
          asOf: liveTrack.as_of,
          windowStart: liveTrack.window_start,
          windowEnd: liveTrack.window_end,
          coverage: coverage(liveTrack),
        }
      : null,
    headlines,
  };
}

export async function loadSupabaseFinancial(
  code: string,
  client: InsightQueryClient,
): Promise<FinancialSnapshot | null> {
  const snapshotResult = await client
    .from("financial_snapshots")
    .select("id,as_of,fiscal_year,statement,receipt_no,filed_at,shares_basis,price_as_of")
    .eq("stock_code", code)
    .order("as_of", { ascending: false })
    .limit(1)
    .maybeSingle() as QueryResult;
  const snapshot = unwrap(snapshotResult, "financial_snapshots") as {
    id: string;
    as_of?: string;
    fiscal_year: number;
    statement: string;
    receipt_no: string;
    filed_at: string;
    shares_basis: string;
    price_as_of: string | null;
  } | null;
  if (!snapshot) return null;

  const metricsResult = await client
    .from("financial_metrics")
    .select("metric_key,value,unit,basis,note")
    .eq("snapshot_id", snapshot.id)
    .order("metric_key") as QueryResult;
  const rows = (unwrap(metricsResult, "financial_metrics") ?? []) as Array<{
    metric_key: string;
    value: number | null;
    unit: "multiple" | "percent";
    basis: string;
    note: string | null;
  }>;
  if (!METRIC_KEYS.every((key) => rows.some(({ metric_key }) => metric_key === key))) return null;
  const byKey = new Map(rows.map((row) => [row.metric_key, row]));
  const metrics: FinancialMetric[] = METRIC_KEYS.map((key) => {
    const row = byKey.get(key)!;
    return {
      key,
      label: FINANCIAL_LABEL[key],
      value: row.value,
      unit: row.unit === "multiple" ? "배" : "%",
      basis: row.basis,
      note: row.note,
    };
  });
  const priceLabel = snapshot.price_as_of ? ` · 주가 ${snapshot.price_as_of} 종가` : "";
  return {
    period: `${snapshot.fiscal_year} 사업연도 · ${STATEMENT_LABEL[snapshot.statement] ?? snapshot.statement}재무제표 · 사업보고서 ${snapshot.filed_at} 공시(접수번호 ${snapshot.receipt_no}) · 주식수 ${snapshot.shares_basis}${priceLabel}`,
    metrics,
    asOf: snapshot.as_of,
  };
}
