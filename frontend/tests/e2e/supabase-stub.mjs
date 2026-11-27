// 서버 렌더링이 부르는 REST 조회에 빈 결과를 바로 돌려준다(연결 실패 재시도로 느려지지 않게).
import { createServer } from "node:http";
import { readFileSync } from "node:fs";
import { priceEventsFixture } from "./price-events-fixture.mjs";
import { sentimentHistoryFixture } from "./sentiment-history-fixture.mjs";

const snapshots = JSON.parse(readFileSync("../backend/analysis/chart/serving/previews/2026-09-21/snapshots.json", "utf8"));
const chartRows = snapshots.map(payload => ({
  batch_id: payload.batch_id, stock_code: payload.stock_code, horizon: payload.horizon, payload,
}));

const LOADING_STOCK_CODE = "010130";
const STOCKS = {
  [LOADING_STOCK_CODE]: { name: "로딩 확인 종목", market: "KOSPI", risk_grade: 3, risk_flags: [] },
  "418250": { name: "미래에셋비전스팩3호", market: "KOSPI", risk_grade: 3, risk_flags: ["spac"] },
  "035420": { name: "NAVER", market: "KOSPI", risk_grade: 2, risk_flags: [] },
  "247540": { name: "에코프로비엠", market: "KOSDAQ", risk_grade: 1, risk_flags: [] },
  "051910": { name: "LG화학", market: "KOSPI", risk_grade: 3, risk_flags: [] },
};

const PUBLIC_CATALOG = [
  { code: "000660", name: "SK하이닉스" },
  { code: LOADING_STOCK_CODE, name: STOCKS[LOADING_STOCK_CODE].name },
  { code: "005380", name: "현대차" },
  { code: "005930", name: "삼성전자" },
  { code: "035720", name: "카카오" },
  { code: "068270", name: "셀트리온" },
];

// 데모 종목은 빌드 때 미리 렌더돼서, 요청 때 렌더되는 이 종목이어야 운영 빌드에서도 합성 데이터가 보인다.
const BASIS_CODE = "000660";
const NO_BASIS_CODE = "051910";

createServer((request, response) => {
  const rest = request.url?.startsWith("/rest/v1/");
  const headers = {
    "Content-Type": "application/json",
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Methods": "GET,POST,PATCH,DELETE,OPTIONS",
    "Access-Control-Allow-Headers": "apikey,authorization,content-type,x-client-info,prefer,accept-profile,content-profile",
  };
  if (request.method === "OPTIONS") {
    response.writeHead(204, headers);
    response.end();
    return;
  }
  response.writeHead(rest ? 200 : 404, headers);
  const chart = request.url?.startsWith("/rest/v1/latest_chart_signal_snapshots?");
  const url = new URL(request.url || "/", "http://localhost");
  const sentiment = sentimentHistoryFixture(url);
  const priceEvents = process.env.PRICE_EVENTS_FIXTURE === "1" ? priceEventsFixture(url) : null;
  const basisFixture = url.searchParams.get("stock_code") === `eq.${BASIS_CODE}` || url.searchParams.get("code") === `eq.${BASIS_CODE}`;
  const signalCode = chart && [BASIS_CODE, NO_BASIS_CODE, LOADING_STOCK_CODE].find(code => url.searchParams.get("stock_code") === `in.(${code})`);
  const basisSignals = signalCode
    ? chartRows.filter(row => row.stock_code === "005930").map(row => ({ ...row, stock_code: signalCode, payload: { ...row.payload, stock_code: signalCode } }))
    : null;
  const basisChart = basisFixture && chart && url.searchParams.get("select")?.includes("history:payload")
    ? (() => {
        const payload = chartRows.find(row => row.stock_code === "005930" && row.horizon === 20).payload;
        return { as_of: payload.data_asof, history: payload.prices.history };
      })()
    : null;
  const basisSupply = basisFixture && url.pathname === "/rest/v1/supply_demand" ? [
    { trade_date: "2026-09-21", retail: 10, foreign_investor: -5, institution: -5 },
  ] : null;
  const basisNewsDays = basisFixture && url.pathname === "/rest/v1/news_sentiment_daily"
    ? [
        { sentiment_date: "2026-09-17", sentiment_mean: -0.3, article_count: 6 },
        { sentiment_date: "2026-09-18", sentiment_mean: 0.05, article_count: 3 },
        { sentiment_date: "2026-09-21", sentiment_mean: 0.5, article_count: 8 },
      ].reverse().map(day => ({ ...day, status: "ok", sentiment_std: 0.1, publisher_count: 2 }))
    : null;
  const basisNewsTrack = basisFixture && url.pathname === "/rest/v1/news_sentiment_tracks"
    ? [{ track: "historical", backend: "kr-finbert", status: "ok", source: "bigkinds",
        as_of: "2026-09-21T18:00:00+09:00", window_start: "2026-09-17", window_end: "2026-09-21",
        article_count: 17, publisher_count: 2, fetched_count: 17, relevant_count: 17,
        sentiment_mean: 0.14, sentiment_std: 0.1 }]
    : null;
  const basisFinancial = basisFixture && url.pathname === "/rest/v1/financial_snapshots" ? [{
    id: "e2e-basis", as_of: "2026-09-21", fiscal_year: 2026, report_code: "11012",
    statement: "CFS", receipt_no: "20260921000001", filed_at: "2026-08-14", shares_basis: "보고서",
    price: null, price_as_of: "2026-09-21", price_source: "KRX",
  }] : null;
  const basisMetrics = url.searchParams.get("snapshot_id") === "eq.e2e-basis" && url.pathname === "/rest/v1/financial_metrics"
    ? [["revenue_growth", 5.6], ["operating_margin", 6.6], ["roe", 9.4], ["debt_ratio", 104.8], ["per", 8.6], ["pbr", 0.8]]
        .map(([metric_key, value]) => ({ metric_key, value, unit: ["per", "pbr"].includes(metric_key) ? "multiple" : "percent", basis: "가상 보고서", note: null }))
    : null;
  const basisDisclosures = basisFixture && url.pathname === "/rest/v1/disclosures" ? [
    { rcept_no: "20260921000001", title: "가상 공시 테스트", kind: "other", filed_on: "2026-09-21" },
  ] : null;
  const basisMaster = basisFixture && url.pathname === "/rest/v1/stocks" ? [{
    code: BASIS_CODE, name: "SK하이닉스", market: "KOSPI", risk_grade: 3, risk_flags: [],
    volatility_annual: 0.2, volatility_percentile: 0.5, risk_as_of: "2026-09-21",
  }] : null;
  const catalog = url.pathname === "/rest/v1/stocks" && url.searchParams.get("select") === "code,name" ? PUBLIC_CATALOG : null;
  const stock = url.pathname === "/rest/v1/stocks" && STOCKS[url.searchParams.get("code")?.replace("eq.", "") ?? ""];
  const strong = chart && url.searchParams.get("select")?.includes("scores:") && chartRows.filter(row => row.horizon === 20).map(({ stock_code, payload }) => ({
    stock_code, name: payload.stock_name, as_of: payload.data_asof, status: payload.inference.status,
    scores: payload.inference.scores, why: payload.inference.features?.[0]?.label_ko ?? null,
  })).concat({ stock_code: "418250", name: "미래에셋비전스팩3호", as_of: "2026-09-21", status: "available",
    scores: { down: 0.1, neutral: 0.2, up: 0.7 }, why: null });
  const codes = url.pathname === "/rest/v1/stocks" && url.searchParams.get("code")?.match(/^in\.\((.*)\)$/)?.[1].split(",");
  const master = codes && codes.map(code => ({ code, market: "KOSPI", risk_grade: 3, risk_flags: [], ...STOCKS[code] }));
  response.end(rest && request.method === "GET" ? JSON.stringify(priceEvents ?? basisChart ?? basisSignals ?? basisSupply ?? basisFinancial ?? basisMetrics ?? basisDisclosures ?? basisMaster ?? catalog ?? sentiment ?? basisNewsDays ?? basisNewsTrack ?? (stock ? [stock] : strong || master || (chart ? chartRows : []))) : "{}");
}).listen(Number(process.env.SUPABASE_STUB_PORT ?? "54321"), "127.0.0.1");
