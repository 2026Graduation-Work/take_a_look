import assert from "node:assert/strict";
import test from "node:test";
import { loadLatestCloses } from "./latest-closes.ts";

// 최신 게시 스냅샷 행 → 종가 + 4주 방향 신호. 점수 없는 행은 신호 없이 종가만.
test("loadLatestCloses maps H20 scores to signal light", async () => {
  const rows = [
    { stock_code: "005930", close: 269000, as_of: "2026-10-07", status: "available", scores: { down: 0.5, neutral: 0.3, up: 0.2 } },
    { stock_code: "035420", close: 188100, as_of: "2026-10-07", status: "available", scores: { down: 0.1, neutral: 0.2, up: 0.7 } },
    { stock_code: "000890", close: 1309, as_of: "2026-10-07", status: "unavailable", scores: null },
    { stock_code: "005380", close: null, as_of: "2026-10-07", status: "available", scores: { down: 0, neutral: 1, up: 0 } },
  ];
  const query = { select: () => query, eq: () => query, in: async () => ({ data: rows, error: null }) };
  const closes = await loadLatestCloses({ from: () => query } as never, ["005930", "035420", "000890", "005380"]);
  assert.equal(closes.get("005930")?.signal, "negative");
  assert.equal(closes.get("035420")?.signal, "positive");
  assert.deepEqual(closes.get("000890"), { close: 1309, asOf: "2026-10-07" });
  assert.equal(closes.has("005380"), false);
});
