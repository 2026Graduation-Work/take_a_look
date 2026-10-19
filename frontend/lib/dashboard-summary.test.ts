import assert from "node:assert/strict";
import { test } from "node:test";
import { dashboardSummary } from "./dashboard-summary.ts";

const h = (name: string, signal: "positive" | "neutral" | "negative" | "strong_negative") => ({ name, signal });

test("대시보드 요약: 하락 신호 0개, 1~2종목은 이름, 3종목 이상은 개수", () => {
  assert.equal(
    dashboardSummary({ holdings: [h("삼성전자", "positive"), h("카카오", "neutral")], holdingCount: 2, strongCount: 2 }),
    "보유 종목 중 하락 신호는 없어요.",
  );
  assert.equal(
    dashboardSummary({ holdings: [h("삼성전자", "negative"), h("현대차", "positive")], holdingCount: 3, strongCount: 2 }),
    "삼성전자에 하락 신호가 있어요.",
  );
  assert.equal(
    dashboardSummary({ holdings: [h("삼성전자", "negative"), h("카카오", "strong_negative"), h("현대차", "positive")], holdingCount: 3, strongCount: 2 }),
    "삼성전자, 카카오에 하락 신호가 있어요.",
  );
  assert.equal(
    dashboardSummary({ holdings: [h("삼성전자", "negative"), h("카카오", "negative"), h("셀트리온", "strong_negative")], holdingCount: 4, strongCount: 2 }),
    "보유 종목 중 3종목에 하락 신호가 있어요.",
  );
});

test("대시보드 요약: 보유 종목이 없으면 기존 빈 상태 문장", () => {
  assert.equal(dashboardSummary({ holdings: [], holdingCount: 0, strongCount: 3 }), "오늘 모델 신호가 강한 종목은 3개예요.");
});
