import type { SupabaseClient } from "@supabase/supabase-js";
import { kstDay } from "../display.ts";
import type {
  FinancialMetric,
  FinancialSnapshot,
  Headline,
  NewsTrackCoverage,
  NewsTrackStatus,
  SentimentData,
  SentimentDay,
} from "./index.ts";

export type InsightQueryClient = Pick<SupabaseClient, "from">;

export interface LiveSentimentSummary {
  periodDays?: SentimentDay[];
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
// DART 정기보고서 종류(financial_snapshots.report_code, 0012). 비율은 사업보고서(연간)로만 만든다(#292) → "2025년 연간 기준".
// 10/13 이전에 적재된 분기·반기 행은 이름만 '누적'으로 맞춘다(새 적재는 연간만)
const REPORT_LABEL: Record<string, string> = { "11013": "최근 1분기 누적", "11012": "최근 반기 누적", "11014": "최근 3분기 누적", "11011": "연간" };

const METRIC_KEYS = Object.keys(FINANCIAL_LABEL);
const REPRESENTATIVE_TITLE_TERMS: Record<string, string[]> = {
  "005930": ["삼성전자"],
  "005380": ["현대차", "현대자동차"],
  "035720": ["카카오"],
  "068270": ["셀트리온"],
  "035420": ["네이버", "NAVER"],
  "247540": ["에코프로비엠", "에코프로 BM"],
};

const PUBLISHER_NAME_BY_DOMAIN: Record<string, string> = {
  "ajunews.com": "아주경제",
  "asiae.co.kr": "아시아경제",
  "businesspost.co.kr": "비즈니스포스트",
  "chosun.com": "조선일보",
  "donga.com": "동아일보",
  "edaily.co.kr": "이데일리",
  "etnews.com": "전자신문",
  "fnnews.com": "파이낸셜뉴스",
  "hani.co.kr": "한겨레",
  "hankyung.com": "한국경제",
  "it.donga.com": "IT동아",
  "joongang.co.kr": "중앙일보",
  "mk.co.kr": "매일경제",
  "mt.co.kr": "머니투데이",
  "newsis.com": "뉴시스",
  "sedaily.com": "서울경제",
  "segyebiz.com": "세계비즈",
  "seoul.co.kr": "서울신문",
  "yna.co.kr": "연합뉴스",
  "zdnet.co.kr": "지디넷코리아",
};
const PUBLISHER_DOMAINS_BY_LENGTH = Object.keys(PUBLISHER_NAME_BY_DOMAIN)
  .sort((left, right) => right.length - left.length);

interface ArticleRow {
  news_id?: string;
  title: string;
  press: string | null;
  url?: string;
  article_date: string;
  published_at: string | null;
  event_id?: string | null;
  sentiment_score?: number | null;
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
    return new URL(url).hostname.replace(/^(?:www|m)\./, "").toLowerCase();
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
  const domain = publisherDomain(url) || verifiedStoredDomain(press).replace(/^m\./, "");
  const knownDomain = PUBLISHER_DOMAINS_BY_LENGTH
    .find((candidate) => domain === candidate || domain.endsWith(`.${candidate}`));
  return (knownDomain && PUBLISHER_NAME_BY_DOMAIN[knownDomain]) || domain || "언론사 미상";
}

function articleEventKey(article: ArticleRow): string {
  const eventId = cleanDisplayText(article.event_id);
  if (eventId) return `event:${eventId}`;
  return `title:${cleanDisplayText(article.title).replace(/[^0-9A-Za-zㄱ-힝]/gu, "").toLowerCase()}`;
}

function sentimentDistance(article: ArticleRow, sentimentMean: number | null | undefined): number {
  return typeof sentimentMean === "number" && typeof article.sentiment_score === "number"
    ? Math.abs(article.sentiment_score - sentimentMean)
    : Number.POSITIVE_INFINITY;
}

function selectRepresentativeHeadlines(
  code: string,
  rows: ArticleRow[],
  sentimentMean: number | null | undefined,
): Headline[] {
  const terms = REPRESENTATIVE_TITLE_TERMS[code] ?? [];
  const candidates = rows
    .map((article) => ({ ...article, title: cleanDisplayText(article.title) }))
    .filter(({ title }) => title && !hasBrokenCharacters(title));
  const bySentimentDistance = (left: ArticleRow, right: ArticleRow) => {
    const leftDistance = sentimentDistance(left, sentimentMean);
    const rightDistance = sentimentDistance(right, sentimentMean);
    return leftDistance === rightDistance ? 0 : leftDistance - rightDistance;
  };
  const direct = candidates
    .filter(({ title }) => terms.some((term) => title.includes(term)))
    .sort(bySentimentDistance);
  const indirect = candidates
    .filter(({ title }) => !terms.some((term) => title.includes(term)))
    .sort(bySentimentDistance);
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

function articleDay(article: ArticleRow): string {
  const timestamp = article.published_at ? Date.parse(article.published_at) : NaN;
  return Number.isFinite(timestamp)
    ? kstDay(timestamp)
    : article.article_date;
}

function articleKeys(article: ArticleRow): string[] {
  const keys = article.news_id ? [`id:${article.news_id}`] : [];
  if (article.url) {
    try {
      const url = new URL(article.url);
      url.hash = "";
      for (const key of [...url.searchParams.keys()]) {
        if (key.startsWith("utm_") || key === "fbclid" || key === "gclid") url.searchParams.delete(key);
      }
      url.searchParams.sort();
      keys.push(`url:${url.toString()}`);
    } catch { /* A missing or malformed URL still permits title/ID matching. */ }
  }
  if (article.title && article.press) {
    keys.push(`title:${articleDay(article)}:${article.press.trim()}:${article.title.replace(/\s+/g, " ").trim()}`);
  }
  return keys;
}

export function liveArticlePeriodDays(live: ArticleRow[], historical: ArticleRow[]): SentimentDay[] {
  const seen = new Set(historical.flatMap(articleKeys));
  const groups = new Map<string, { sum: number; count: number }>();
  for (const article of live) {
    const score = article.sentiment_score;
    if (typeof score !== "number" || !Number.isFinite(score) || score < -1 || score > 1) continue;
    const keys = articleKeys(article);
    if (keys.some((key) => seen.has(key))) continue;
    keys.forEach((key) => seen.add(key));
    const date = articleDay(article);
    if (!/^\d{4}-\d{2}-\d{2}$/.test(date)) continue;
    const group = groups.get(date) ?? { sum: 0, count: 0 };
    group.sum += score;
    group.count++;
    groups.set(date, group);
  }
  return [...groups].sort(([left], [right]) => left.localeCompare(right))
    .map(([date, group]) => ({date, score: group.sum / group.count, articleCount: group.count}));
}

async function sentimentArticles(client: InsightQueryClient, code: string, track: string, dates?: string[]): Promise<ArticleRow[]> {
  const rows: ArticleRow[] = [];
  for (let offset = 0; ; offset += 1000) {
    let query = client.from("news_articles")
      .select("news_id,title,press,url,article_date,published_at,event_id,sentiment_score")
      .eq("stock_code", code).eq("track", track);
    if (dates) query = query.in("article_date", dates);
    const result = await query.order("published_at", { ascending: false, nullsFirst: false })
      .order("news_id", { ascending: true }).range(offset, offset + 999) as QueryResult;
    const page = (unwrap(result, "news_articles") ?? []) as ArticleRow[];
    rows.push(...page);
    if (page.length < 1000) return rows;
  }
}

export async function loadSupabaseSentiment(
  code: string,
  client: InsightQueryClient,
): Promise<SupabaseSentimentResult> {
  const tracksResult = await client
    .from("news_sentiment_tracks")
    .select("*")
    .eq("stock_code", code) as QueryResult;
  const dailyRows: unknown[] = [];
  const pageSize = 1000;
  for (let offset = 0; ; offset += pageSize) {
    const pageResult = await client
      .from("news_sentiment_daily")
      .select("sentiment_date,status,sentiment_mean,sentiment_std,article_count,publisher_count")
      .eq("stock_code", code)
      .eq("track", "historical")
      .not("sentiment_mean", "is", null)
      .order("sentiment_date", { ascending: false })
      .range(offset, offset + pageSize - 1) as QueryResult;
    const page = (unwrap(pageResult, "news_sentiment_daily") ?? []) as unknown[];
    dailyRows.push(...page);
    if (page.length < pageSize) break;
  }
  const articleResult = await client.from("news_articles")
    .select("news_id,title,press,url,article_date,published_at,event_id,sentiment_score")
    .eq("stock_code", code).eq("track", "live")
    .order("published_at", { ascending: false, nullsFirst: false })
    .order("news_id", { ascending: true }).limit(25) as QueryResult;
  const articles = (unwrap(articleResult, "news_articles") ?? []) as ArticleRow[];
  const tracks = (unwrap(tracksResult, "news_sentiment_tracks") ?? []) as TrackRow[];
  const historicalTrack = tracks.find(({ track }) => track === "historical");
  const liveTrack = tracks.find(({ track }) => track === "live");
  const liveEnd = liveTrack ? Date.parse(liveTrack.as_of) : NaN;
  const liveStart = liveEnd - 24 * 3_600_000;
  // Live 일별 행은 저장된 기사 전체로 날짜마다 다시 집계된다(supabase_store.live_daily_rows). 수집한 모든 날을 잇는다.
  const liveDailyResult = liveTrack
    ? await client.from("news_sentiment_daily")
      .select("sentiment_date,sentiment_mean,article_count")
      .eq("stock_code", code).eq("track", "live")
      .order("sentiment_date", { ascending: true }) as QueryResult
    : {data: [], error: null};
  const liveDaily = (unwrap(liveDailyResult, "news_sentiment_daily") ?? []) as Array<{
    sentiment_date: string; sentiment_mean: number | null; article_count: number;
  }>;
  const daily = dailyRows as Array<{
    sentiment_date: string;
    sentiment_mean: number | null;
    article_count: number;
  }>;
  const days = daily
    .filter(({ sentiment_mean }) => sentiment_mean !== null)
    .map(({ sentiment_date, sentiment_mean, article_count }) => ({
      date: sentiment_date,
      score: sentiment_mean as number,
      articleCount: article_count,
    }))
    .sort((left, right) => left.date.localeCompare(right.date));
  const liveDays = liveDaily.filter((row) =>
    row.sentiment_mean !== null && Number.isFinite(row.sentiment_mean) && row.article_count > 0)
    .map((row) => ({date:row.sentiment_date,score:row.sentiment_mean as number,articleCount:row.article_count}));
  const historicalDates = new Set(days.map(({date}) => date));
  const overlappingDates = liveDays.map(({date}) => date).filter((date) => historicalDates.has(date));
  // Stored Live daily scores already split the rolling window by KST date.
  // Only overlapping days need article-level deduplication against historical.
  let periodDays = liveDays;
  if (overlappingDates.length) {
    const [overlappingLive, overlappingHistorical] = await Promise.all([
      sentimentArticles(client, code, "live", overlappingDates),
      sentimentArticles(client, code, "historical", overlappingDates),
    ]);
    const currentArticles = overlappingLive.filter((article) => {
      const timestamp = article.published_at ? Date.parse(article.published_at) : NaN;
      return Number.isFinite(timestamp) && timestamp >= liveStart && timestamp <= liveEnd;
    });
    periodDays = [...liveDays.filter(({date}) => !overlappingDates.includes(date)),
      ...liveArticlePeriodDays(currentArticles, overlappingHistorical)]
      .sort((left,right) => left.date.localeCompare(right.date));
  }
  const headlines = selectRepresentativeHeadlines(code, articles, liveTrack?.sentiment_mean);

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
          periodDays,
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

function positiveFinite(value: unknown): value is number {
  return typeof value === "number" && Number.isFinite(value) && value > 0;
}

function validPriceDay(value: unknown): value is string {
  if (typeof value !== "string" || !/^\d{4}-\d{2}-\d{2}$/.test(value)) return false;
  const time = Date.parse(`${value}T00:00:00Z`);
  return Number.isFinite(time) && new Date(time).toISOString().slice(0, 10) === value;
}

export async function loadSupabaseFinancial(
  code: string,
  client: InsightQueryClient,
): Promise<FinancialSnapshot | null> {
  const snapshotResult = await client
    .from("financial_snapshots")
    .select("id,as_of,fiscal_year,report_code,statement,receipt_no,filed_at,shares_basis,price,price_as_of,price_source")
    .eq("stock_code", code)
    .order("as_of", { ascending: false })
    .limit(1)
    .maybeSingle() as QueryResult;
  const snapshot = unwrap(snapshotResult, "financial_snapshots") as {
    id: string;
    as_of?: string;
    fiscal_year: number;
    report_code: string | null;
    statement: string;
    receipt_no: string;
    filed_at: string;
    shares_basis: string;
    price: number | null;
    price_as_of: string | null;
    price_source: string | null;
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
  // 보고서 수집과 가격 갱신을 분리한다. 같은 이익·자본·주식수 기준에서는
  // PER/PBR(new) = 저장 배수 × 새 종가 / 저장 주가. 매 조회마다 원본 DB 값에서
  // 계산하므로 일별 반올림 오차가 누적되지 않는다(저장 배수의 소수점 4자리 정밀도).
  let priceAsOf = snapshot.price_as_of;
  let priceSource = snapshot.price_source;
  let asOf = snapshot.as_of;
  if (positiveFinite(snapshot.price) && validPriceDay(snapshot.price_as_of)) {
    try {
      const quoteResult = await client.from("latest_chart_signal_snapshots")
        .select("close:payload->inference->close,as_of:payload->>data_asof,source:payload->prices->>source,history:payload->prices->history")
        .eq("stock_code", code)
        .eq("horizon", 20)
        .maybeSingle() as QueryResult;
      const quote = unwrap(quoteResult, "latest_chart_signal_snapshots") as {
        close: number; as_of: string; source?: string; history?: Array<{ date: string; close: number }>;
      } | null;
      if (quote && positiveFinite(quote.close) && validPriceDay(quote.as_of)
        && quote.as_of > snapshot.price_as_of) {
        // 액면분할 뒤의 최신 이력은 과거 가격도 같은 단위로 수정된다.
        // 원래 기준일이 이력에 없으면 호환성을 확인할 수 없어 갱신하지 않는다.
        const baseline = quote.history?.find(({ date }) => date === snapshot.price_as_of)?.close;
        const factor = positiveFinite(baseline) ? quote.close / baseline : NaN;
        const valuation = metrics.filter(({ key }) => key === "per" || key === "pbr");
        // 비정상 가격비나 저장값이면 기존 값·날짜를 함께 유지한다.
        if (positiveFinite(factor) && valuation.every(({ value }) => value === null
          || (Number.isFinite(value) && Number.isFinite(value * factor)))) {
          priceSource = (quote.source || "KRX").replace("KRX adjusted daily OHLCV", "KRX 수정종가");
          for (const metric of valuation) {
            if (metric.value === null) continue; // 적자·결측은 주가로 채우지 않는다.
            const original = metric.value;
            metric.value = Number((original * factor).toFixed(4));
            metric.basis = `기존 ${original}배 × (${quote.as_of} ${priceSource} ${quote.close.toLocaleString("ko-KR")}원 ÷ ${snapshot.price_as_of} 수정종가 ${baseline!.toLocaleString("ko-KR")}원), 기존 재무 계산: ${metric.basis}`;
          }
          priceAsOf = quote.as_of;
          asOf = snapshot.as_of && snapshot.as_of > quote.as_of ? snapshot.as_of : quote.as_of;
        }
      }
    } catch {
      // 가격 공급원 장애가 재무표 전체를 숨기지 않게 기존 주가 기준을 유지한다.
    }
  }
  const priceLabel = priceAsOf ? `, 주가 ${priceAsOf} 종가${priceSource ? ` (${priceSource})` : ""}` : "";
  return {
    period: `${snapshot.fiscal_year}년 ${REPORT_LABEL[snapshot.report_code ?? "11011"]} 기준`,
    filing: `${STATEMENT_LABEL[snapshot.statement] ?? snapshot.statement}재무제표, ${snapshot.filed_at} 공시(접수번호 ${snapshot.receipt_no}), 주식수 ${snapshot.shares_basis}${priceLabel}`,
    metrics,
    asOf,
  };
}

export interface Disclosure {
  rceptNo: string;
  title: string;
  kind: string;
  filedOn: string;
}

// DART 공시 목록(제목·날짜·유형만 저장). 원문은 DART 링크로 연다.
export async function loadSupabaseDisclosures(code: string, client: InsightQueryClient): Promise<Disclosure[]> {
  const result = await client.from("disclosures")
    .select("rcept_no,title,kind,filed_on")
    .eq("stock_code", code)
    .order("filed_on", { ascending: false })
    .order("rcept_no", { ascending: false })
    .limit(8) as QueryResult;
  const rows = (unwrap(result, "disclosures") ?? []) as Array<{ rcept_no: string; title: string; kind: string; filed_on: string }>;
  return rows.map((row) => ({ rceptNo: row.rcept_no, title: row.title, kind: row.kind, filedOn: row.filed_on }));
}

// 투자자별 순매수(주, 0013). 최근 20영업일, 날짜 오름차순.
export async function loadSupabaseSupply(code: string, client: InsightQueryClient) {
  const result = await client.from("supply_demand")
    .select("trade_date,retail,foreign_investor,institution")
    .eq("stock_code", code)
    .order("trade_date", { ascending: false })
    .limit(20) as QueryResult;
  const rows = (unwrap(result, "supply_demand") ?? []) as Array<{
    trade_date: string; retail: number; foreign_investor: number; institution: number;
  }>;
  return rows.reverse().map((row) => ({
    date: row.trade_date, retail: Number(row.retail), foreign: Number(row.foreign_investor), institution: Number(row.institution),
  }));
}

// 가격 흐름 분위기(psychology_market_v1의 psych_greed_fear_axis)를 최신 게시 차트의 종가·거래량으로 같은 산식으로 계산한다.
// 원본: backend/analysis/chart/experiments/features/psychology/market_psychology.py · frontend/scripts/build_demo_snapshot.py mood_word
export function psychologyAxis(history: Array<{ close: number; volume: number }>): number | null {
  // 요약축에 필요한 건 20일 수익(종가 21개)과 60일 거래량가중 평균가(60개)뿐이라 60거래일이면 된다(게시 차트가 60개를 싣는다).
  if (history.length < 60) return null;
  const tail = history.slice(-60);
  const returns = tail.slice(-21).map(({ close }, index, rows) => index ? Math.log(close / rows[index - 1].close) : NaN).slice(1);
  const mean = returns.reduce((sum, value) => sum + value, 0) / returns.length;
  const std = Math.sqrt(returns.reduce((sum, value) => sum + (value - mean) ** 2, 0) / (returns.length - 1));
  const window = tail.slice(-60);
  const traded = window.reduce((sum, { volume }) => sum + volume, 0);
  const reference = window.reduce((sum, { close, volume }) => sum + close * volume, 0) / traded;
  const close = tail.at(-1)!.close;
  if (!(std > 0) || !(traded > 0) || !(reference > 0)) return null;
  const fearGreed = Math.tanh((mean * returns.length) / (std * Math.sqrt(20)));
  const disposition = Math.tanh((close - reference) / reference / 0.1);
  const axis = (fearGreed + disposition) / 2;
  return Number.isFinite(axis) ? axis : null;
}

export function moodWord(axis: number): string {
  return axis >= 0.5 ? "많이 들뜸" : axis >= 0.2 ? "조금 들뜸" : axis > -0.2 ? "차분함" : axis > -0.5 ? "조금 움츠러듦" : "많이 움츠러듦";
}

export async function loadSupabasePsychology(code: string, client: InsightQueryClient) {
  const result = await client.from("latest_chart_signal_snapshots")
    .select("as_of:payload->>data_asof,history:payload->prices->history")
    .eq("stock_code", code).eq("horizon", 20).maybeSingle() as QueryResult;
  const row = unwrap(result, "latest_chart_signal_snapshots") as { as_of: string; history: Array<{ close: number; volume: number }> | null } | null;
  const axis = row?.history ? psychologyAxis(row.history) : null;
  return axis === null ? null : { axis, word: moodWord(axis), asOf: row!.as_of };
}
