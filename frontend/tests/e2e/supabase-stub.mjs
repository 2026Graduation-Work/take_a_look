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
  "051910": { name: "LG화학", market: "KOSPI", risk_grade: 3, risk_flags: [] },
};

// 계산 근거 E2E 전용 종목. 데모 종목(빌드 때 미리 렌더)이 아니라 요청 때 렌더되므로 운영 빌드에서도 이 합성 데이터가 보인다.
const BASIS_CODE = "000660";
// 모델 신호는 있지만 수급·위험도 합성 데이터가 없는 종목(이유 문장을 만들지 않는지 확인)
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
  const basisFixture = url.searchParams.get("stock_code") === `eq.${BASIS_CODE}` || url.searchParams.get("code") === `eq.${BASIS_CODE}`;
  // 상세 화면 차트 조회(stock_code=in.(...))에는 삼성전자 공개 표본을 두 종목 코드로 바꿔 돌려준다.
  const signalCode = chart && [BASIS_CODE, NO_BASIS_CODE].find(code => url.searchParams.get("stock_code") === `in.(${code})`);
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
  const basisMaster = basisFixture && url.pathname === "/rest/v1/stocks" ? [{
    code: BASIS_CODE, name: "SK하이닉스", market: "KOSPI", risk_grade: 3, risk_flags: [],
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
  response.end(rest && request.method === "GET" ? JSON.stringify(basisChart ?? basisSignals ?? basisSupply ?? basisMaster ?? sentiment ?? (stock ? [stock] : strong || master || (chart ? chartRows : []))) : "{}");
}).listen(54321, "127.0.0.1");
