// e2e용 빈 Supabase: 서버 렌더링이 부르는 REST 조회에 빈 결과를 바로 돌려준다(연결 실패 재시도로 느려지지 않게).
// 브라우저 쪽 Auth 흐름은 각 테스트가 page.route로 따로 흉내 낸다(supabase-mock.ts).
import { createServer } from "node:http";
import { readFileSync } from "node:fs";
import { sentimentHistoryFixture } from "./sentiment-history-fixture.mjs";

const snapshots = JSON.parse(readFileSync("../backend/analysis/chart/serving/previews/2026-09-21/snapshots.json", "utf8"));
const chartRows = snapshots.map(payload => ({
  batch_id: payload.batch_id, stock_code: payload.stock_code, horizon: payload.horizon, payload,
}));

const STOCKS = {
  "418250": { name: "미래에셋비전스팩3호", market: "KOSPI", risk_grade: 3, risk_flags: ["spac"] },
  "035420": { name: "NAVER", market: "KOSPI", risk_grade: 2, risk_flags: [] },
  "247540": { name: "에코프로비엠", market: "KOSDAQ", risk_grade: 1, risk_flags: [] },
};

let basisFixture = false;
createServer(async (request, response) => {
  // 계산 근거 E2E 전용 합성 데이터. 테스트가 끝나면 바로 해제한다.
  if (request.method === "POST" && request.url === "/__test/basis-fixture") {
    let body = "";
    for await (const chunk of request) body += chunk;
    basisFixture = JSON.parse(body).enabled === true;
    response.writeHead(200, { "Content-Type": "application/json" });
    response.end("{}");
    return;
  }
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
  const basisChart = basisFixture && chart && url.searchParams.get("select")?.includes("history:payload")
    ? (() => {
        const payload = chartRows.find(row => row.stock_code === "005930" && row.horizon === 20).payload;
        return { as_of: payload.data_asof, history: payload.prices.history };
      })()
    : null;
  const basisSupply = basisFixture && url.pathname === "/rest/v1/supply_demand" ? [
    { trade_date: "2026-09-21", retail: 10, foreign_investor: -5, institution: -5 },
  ] : null;
  const basisMaster = basisFixture && url.pathname === "/rest/v1/stocks" && url.searchParams.get("code") === "eq.005930" ? [{
    code: "005930", name: "삼성전자", market: "KOSPI", risk_grade: 3, risk_flags: [],
    volatility_annual: 0.2, volatility_percentile: 0.5, risk_as_of: "2026-09-21",
  }] : null;
  // 상세 화면 서버 렌더가 종목 마스터에서 찾는 종목(데모 예시 밖)
  const stock = url.pathname === "/rest/v1/stocks" && STOCKS[url.searchParams.get("code")?.replace("eq.", "") ?? ""];
  // 대시보드 "오늘 신호가 강한 종목"(lib/strong-signals.ts): 별칭 select는 평평한 행, 종목 마스터는 code=in.(...)
  const strong = chart && url.searchParams.get("select")?.includes("scores:") && chartRows.filter(row => row.horizon === 20).map(({ stock_code, payload }) => ({
    stock_code, name: payload.stock_name, as_of: payload.data_asof, status: payload.inference.status,
    scores: payload.inference.scores, why: payload.inference.features?.[0]?.label_ko ?? null,
  })).concat({ stock_code: "418250", name: "미래에셋비전스팩3호", as_of: "2026-09-21", status: "available",
    scores: { down: 0.1, neutral: 0.2, up: 0.7 }, why: null }); // SPAC 회피를 고른 사용자에게는 "직접 고른 제외 항목"으로
  const codes = url.pathname === "/rest/v1/stocks" && url.searchParams.get("code")?.match(/^in\.\((.*)\)$/)?.[1].split(",");
  const master = codes && codes.map(code => ({ code, market: "KOSPI", risk_grade: 3, risk_flags: [], ...STOCKS[code] }));
  response.end(rest && request.method === "GET" ? JSON.stringify(basisChart ?? basisSupply ?? basisMaster ?? sentiment ?? (stock ? [stock] : strong || master || (chart ? chartRows : []))) : "{}");
}).listen(54321, "127.0.0.1");
