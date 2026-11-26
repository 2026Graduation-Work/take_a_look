import assert from "node:assert/strict";
import { test } from "node:test";
import { loadEventDisclosures, loadEventMarket, parseEventDisclosures, parseEventMarket } from "./price-event-context.ts";

const stock = "005930";
const window = { from: "2026-11-20", through: "2026-11-23", endReason: "next_session_included" } as const;
const timestamp = "2026-11-25T18:00:00Z";
const disclosure = (id: string, filedOn = "2026-11-21") => ({
  stock_code: stock, rcept_no: id, filed_on: filedOn, kind: "earnings", title: "가상의 제출 자료",
});

test("공시는 주말 포함, 접수번호 중복 제거, 서로 다른 정정 접수번호 유지, 공급 링크 검증", () => {
  const first = disclosure("20261121000001");
  const second = disclosure("20261121000002");
  const result = parseEventDisclosures([first, second, first, disclosure("javascript:alert(1)")], stock, window, timestamp);
  assert.equal(result.status, "available");
  assert.equal(result.coverage, "unverified");
  assert.equal(result.items.length, 3);
  assert.equal(result.items[0].url, null);
  assert.equal(result.items[1].kind, "earnings");
  assert.equal(result.items[1].rceptNo, second.rcept_no);
  assert.equal(result.items[1].url, "https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20261121000002");
});

test("성공 0건, 일부 제외, 모두 불량, 상한에 도달한 결과를 구분한다", () => {
  const empty = parseEventDisclosures([], stock, window, timestamp);
  assert.equal(empty.status, "available");
  assert.deepEqual(empty.items, []);
  assert.equal(empty.coverage, "unverified");
  const bad = { ...disclosure("20261121000001"), stock_code: "005380" };
  assert.deepEqual(parseEventDisclosures([bad], stock, window, timestamp), { status: "unavailable", reason: "invalid_response" });
  const items = Array.from({ length: 50 }, (_, index) => disclosure(`20261121${String(index).padStart(6, "0")}`));
  const result = parseEventDisclosures([bad, ...items], stock, window, timestamp);
  assert.equal(result.status, "available");
  assert.equal(result.items.length, 49);
  assert.equal(result.coverage, "known_partial");
  assert.equal(result.truncated, true);
});

test("코스피 0%는 유지하고 요청 밖 행 때문에 응답을 믿을 수 없는 날짜만 제외한다", () => {
  const [a, b, c] = ["2026-11-19", "2026-11-20", "2026-11-23"];
  const result = parseEventMarket([
    { status_date: a, index_quotes: [{ symbol: "KOSPI", changePercent: 0 }] },
    { status_date: b, index_quotes: [{ symbol: "KOSPI", changePercent: "0.4" }] },
    { status_date: "2026-11-24", index_quotes: [{ symbol: "KOSPI", changePercent: 1 }] },
  ], [a, b, c], timestamp);
  assert.deepEqual(result.get(a), { status: "available", items: [{ date: a, changePercent: 0 }], fetchedAt: timestamp, coverage: "unverified", truncated: false, refresh: { status: "idle" } });
  assert.deepEqual(result.get(b), { status: "unavailable", reason: "invalid_response" });
  assert.deepEqual(result.get(c), { status: "unavailable", reason: "invalid_response" });
});

test("빈 코스피 응답과 정상 응답의 빠진 날짜는 0건이고 날짜를 읽을 수 없는 응답은 실패다", () => {
  const dates = ["2026-11-20", "2026-11-23"];
  const empty = { status: "available", items: [], fetchedAt: timestamp, coverage: "unverified", truncated: false, refresh: { status: "idle" }, emptyReason: "no_rows" };
  const exact = { status_date: dates[0], index_quotes: [{ symbol: "KOSPI", changePercent: 1 }] };
  assert.deepEqual([...parseEventMarket([], dates, timestamp).values()], [empty, empty]);
  assert.deepEqual(parseEventMarket([exact], dates, timestamp).get(dates[1]), empty);
  const mixed = parseEventMarket([exact, { status_date: "2026-02-30", index_quotes: [] }], dates, timestamp);
  assert.equal(mixed.get(dates[0])?.status, "available");
  assert.deepEqual(mixed.get(dates[1]), { status: "unavailable", reason: "invalid_response" });
});

test("검증할 수 있는 코스피 값의 미제공과 식별할 수 없는 코스피 응답을 구분한다", () => {
  const date = "2026-11-20";
  const market = (quotes: unknown) => parseEventMarket([{ status_date: date, index_quotes: quotes }], [date], timestamp).get(date);
  for (const quotes of [[], [{ symbol: "KOSDAQ" }], [{ symbol: "KOSPI" }], [{ symbol: "KOSPI", changePercent: null }]]) {
    const result = market(quotes);
    assert.equal(result?.status, "available");
    assert.deepEqual(result.items, []);
    assert.equal(result.emptyReason, "missing_value");
  }
  const value = { symbol: "KOSPI", changePercent: 0 };
  for (const quotes of [null, {}, [value, value], [{}], [{ symbol: 0 }], [{ symbol: " KOSPI" }],
    ...["0", NaN, Infinity].map(changePercent => [{ symbol: "KOSPI", changePercent }])]) {
    assert.deepEqual(market(quotes), { status: "unavailable", reason: "invalid_response" });
  }
  const duplicate = { status_date: date, index_quotes: [value] };
  assert.deepEqual(parseEventMarket([duplicate, duplicate], [date], timestamp).get(date),
    { status: "unavailable", reason: "invalid_response" });
  const unidentified = { changePercent: 1 };
  for (const missing of [{ symbol: "KOSPI" }, { symbol: "KOSPI", changePercent: null }]) {
    assert.deepEqual(market([missing, unidentified]), { status: "unavailable", reason: "invalid_response" });
  }
  const known = market([unidentified, value]);
  assert.equal(known?.status, "available");
  assert.equal(known.items[0].changePercent, 0);
});

test("종목이나 날짜가 범위에 맞지 않는 공시는 해당 행만 제외한다", () => {
  const bad = [
    { ...disclosure("20261121000001"), stock_code: "005380" },
    disclosure("20261119000001", "2026-11-19"),
    disclosure("20261124000001", "2026-11-24"),
    disclosure("20261123000001", "2026-11-31"),
  ];
  assert.deepEqual(parseEventDisclosures(bad, stock, window, timestamp),
    { status: "unavailable", reason: "invalid_response" });
  const within = [disclosure("20261120000001", window.from), disclosure("20261123000002", window.through)];
  const result = parseEventDisclosures([...bad, ...within], stock, window, timestamp);
  assert.equal(result.status, "available");
  assert.equal(result.coverage, "known_partial");
  assert.deepEqual(result.items.map((item) => item.rceptNo), within.map((item) => item.rcept_no).reverse());
});

test("공개 연결이 설정되지 않은 상태는 조회 실패와 구분한다", async (t) => {
  const url = process.env.NEXT_PUBLIC_SUPABASE_URL;
  t.after(() => {
    if (url === undefined) delete process.env.NEXT_PUBLIC_SUPABASE_URL;
    else process.env.NEXT_PUBLIC_SUPABASE_URL = url;
  });
  delete process.env.NEXT_PUBLIC_SUPABASE_URL;
  const signal = new AbortController().signal;
  const unavailable = { status: "unavailable", reason: "not_configured" };
  assert.deepEqual(await loadEventDisclosures(stock, window, signal), unavailable);
  assert.deepEqual((await loadEventMarket([window.from], signal)).get(window.from), unavailable);
});
