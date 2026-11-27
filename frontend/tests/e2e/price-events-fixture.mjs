import { readFileSync } from "node:fs";

const snapshots = JSON.parse(readFileSync("../backend/analysis/chart/serving/previews/2026-09-21/snapshots.json", "utf8"));
export const eventStocks = { "005930": "삼성전자", "005380": "현대차", "068270": "셀트리온", "035720": "카카오" };
const asOf = "2026-09-21";
const dates = [];
for (let day = Date.parse(asOf); dates.length < 61; day -= 86_400_000) {
  const date = new Date(day);
  if (date.getUTCDay() !== 0 && date.getUTCDay() !== 6) dates.unshift(date.toISOString().slice(0, 10));
}
export const eventDates = [dates[60], dates[48], dates[20]];
const adjustedClose = index => index >= 60 ? 12000 : index >= 48 ? 10200 : index >= 20 ? 11400 : 10500;
export const eventBars = dates.map((date, index) => ({ date, close: adjustedClose(index), volume: 2100 }));

export function eventChartRows(code) {
  if (!Object.hasOwn(eventStocks, code)) return [];
  const priceHash = "a".repeat(64);
  return [5, 20].map(horizon => {
    const payload = structuredClone(snapshots.find(row => row.stock_code === "005930" && row.horizon === horizon));
    Object.assign(payload, { stock_code: code, stock_name: eventStocks[code], data_asof: asOf, batch_id: "synthetic-issue-492" });
    payload.sources = { ...payload.sources, prices_sha256: priceHash };
    payload.prices = {
      ...payload.prices,
      history: eventBars.slice(1),
      event_basis: {
        method: "daily-log-std-250-v1", daily_sigma: .03, return_count: 60,
        period_start: dates[1], period_end: asOf, input_sha256: priceHash,
        previous_bar: eventBars[0],
      },
    };
    return { stock_code: code, horizon, batch_id: payload.batch_id, payload };
  });
}

export const eventMarketRows = eventDates.map((date, index) => ({
  status_date: date,
  index_quotes: [{ symbol: "KOSPI", changePercent: [0, -.51, .75][index] }],
}));

export function eventDisclosures(code, date) {
  if (!Object.hasOwn(eventStocks, code)) return [];
  return Array.from({ length: 4 }, (_, index) => ({
    stock_code: code, filed_on: date, rcept_no: `${date.replaceAll("-", "")}${String(5 - index).padStart(6, "0")}`,
    kind: "earnings",
    title: index === 3 ? `${eventStocks[code]} ${"가상의긴공시제목".repeat(12)}` : `${eventStocks[code]} 가상 공시 ${index + 1}`,
  }));
}

export const eventNewsSelect = "stock_code,track,news_id,title,press,url,article_date,published_at";
export function isEventNewsQuery(url) {
  return url.pathname.endsWith("/news_articles") && url.searchParams.get("select") === eventNewsSelect;
}

export function eventNews(code, date) {
  if (!Object.hasOwn(eventStocks, code) || !eventDates.includes(date)) return [];
  return [5, 4, 3, null].map((hour, index) => ({
    stock_code: code, track: "live", article_date: date, news_id: `${date}-${index + 1}`,
    title: `${eventStocks[code]} 가상 뉴스 ${index + 1}`, press: "가상 언론사",
    url: index === 2 ? "javascript:alert(1)" : `https://example.test/news/${code}/${date}/${index + 1}`,
    published_at: hour === null ? null : `${date}T0${hour}:00:00+00:00`,
  }));
}

export function priceEventsFixture(url) {
  const { pathname, searchParams } = url;
  const select = searchParams.get("select");
  if (pathname.endsWith("/latest_chart_signal_snapshots") && select === "batch_id,stock_code,horizon,payload") {
    const codes = searchParams.get("stock_code")?.match(/^in\.\((.*)\)$/)?.[1].split(",") ?? [];
    return codes.flatMap(eventChartRows);
  }
  if (pathname.endsWith("/market_status") && select === "status_date,index_quotes") {
    const requested = searchParams.get("status_date")?.match(/^in\.\((.*)\)$/)?.[1].split(",") ?? [];
    return eventMarketRows.filter(row => requested.includes(row.status_date));
  }
  if (pathname.endsWith("/disclosures") && /^stock_code,rcept_no,title,(?:kind,)?filed_on$/.test(select ?? "")) {
    const code = searchParams.get("stock_code")?.replace(/^eq\./, "");
    const filters = searchParams.getAll("filed_on");
    const from = filters.find(value => value.startsWith("gte."))?.slice(4);
    const through = filters.find(value => value.startsWith("lte."))?.slice(4);
    return eventDates.filter(date => from <= date && date <= through).flatMap(date => eventDisclosures(code, date));
  }
  if (isEventNewsQuery(url)) {
    if (searchParams.get("track") !== "eq.live") return [];
    const code = searchParams.get("stock_code")?.replace(/^eq\./, "");
    const date = searchParams.get("article_date")?.replace(/^eq\./, "");
    return eventNews(code, date);
  }
  return null;
}
