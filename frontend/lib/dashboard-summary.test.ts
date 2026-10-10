import assert from "node:assert/strict";
import { test } from "node:test";
import { dashboardSummary } from "./dashboard-summary.ts";

test("대시보드 요약: 보유 종목·신호에 따라 정해진 문장이 나온다", () => {
  assert.equal(
    dashboardSummary({ holdingSignals: ["positive", "negative", "neutral", "strong_positive"], holdingCount: 4, strongCount: 2 }),
    "보유 4종목 중 1종목에 하방 신호가 있어요.",
  );
  assert.equal(
    dashboardSummary({ holdingSignals: ["positive"], holdingCount: 2, strongCount: 2 }),
    "보유 2종목 모두 하방 신호는 없어요.",
  );
  assert.equal(
    dashboardSummary({ holdingSignals: [], holdingCount: 0, strongCount: 3 }),
    "오늘 모델 신호가 강한 종목은 3개예요.",
  );
});
