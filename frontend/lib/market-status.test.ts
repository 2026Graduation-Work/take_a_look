import assert from "node:assert/strict";
import test from "node:test";
import { staleLabel } from "./market-status.ts";

const at = (iso: string) => Date.parse(iso);

test("staleLabel stays quiet until data is two weekdays behind", () => {
  assert.equal(staleLabel("2026-10-05", at("2026-10-06T03:00:00Z")), null); // 화 낮: 월 종가가 최신
  assert.equal(staleLabel("2026-10-02", at("2026-10-05T03:00:00Z")), null); // 월 낮: 금 종가가 최신
  assert.equal(staleLabel("2026-10-02", at("2026-10-06T03:00:00Z")), "4일 전 데이터예요");
  assert.equal(staleLabel("2025-12-30", at("2026-10-06T03:00:00Z")), "280일 전 데이터예요");
});
