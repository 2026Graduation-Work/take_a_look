import assert from "node:assert/strict";
import test from "node:test";
import { rankSignals, type SnapshotRow } from "./strong-signals.ts";

const row = (code: string, down: number, neutral: number, up: number, status = "available"): SnapshotRow =>
  ({ stock_code: code, name: code, as_of: "2026-10-08", status, scores: { down, neutral, up }, why: "20일 종가 변동 폭" });

test("확신도(1위 − 2위 점수) 내림차순, 중립 1위·추론 불가는 뺀다", () => {
  const ranked = rankSignals([
    row("A", 0.2, 0.3, 0.5),   // 상방 0.2
    row("B", 0.7, 0.2, 0.1),   // 하방 0.5
    row("C", 0.2, 0.6, 0.2),   // 중립 → 제외
    row("D", 0.1, 0.1, 0.8, "unavailable"),
    row("E", 0.45, 0.1, 0.45), // 동점 1위 → 확신도 0
  ]);
  assert.deepEqual(ranked.map(({ code, direction }) => [code, direction]), [["B", "down"], ["A", "up"], ["E", "down"]]);
  assert.ok(Math.abs(ranked[0].confidence - 0.5) < 1e-12);
  assert.equal(ranked[0].why, "20일 종가 변동 폭");
});
