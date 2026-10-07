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
  "035420": { name: "NAVER", market: "KOSPI", risk_grade: 2, risk_flags: [] },
  "247540": { name: "에코프로비엠", market: "KOSDAQ", risk_grade: 1, risk_flags: [] },
};

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
  // 상세 화면 서버 렌더가 종목 마스터에서 찾는 종목(데모 예시 밖)
  const stock = url.pathname === "/rest/v1/stocks" && STOCKS[url.searchParams.get("code")?.replace("eq.", "") ?? ""];
  response.end(rest && request.method === "GET" ? JSON.stringify(sentiment ?? (stock ? [stock] : chart ? chartRows : [])) : "{}");
}).listen(54321, "127.0.0.1");
