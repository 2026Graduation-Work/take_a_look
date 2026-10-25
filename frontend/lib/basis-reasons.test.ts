import assert from "node:assert/strict";
import { test } from "node:test";
import { checkpointReason, psychologyReason } from "./copy-glossary.ts";
import type { FiredNudge, NudgeMarket } from "./profiling/nudges.ts";

const market: NudgeMarket = {
  retailNetBuyStreakDays: 6, retailNetLatest: 10, foreignNetLatest: -5,
  institutionNetBuyDaysOf5: 4, volatilityPercentile: 0.95,
  drawdownFrom3mHigh: -0.2, return3d: 0.12, sentimentChange: -0.4,
  sentimentDayLabel: "10.20에", isTopHolding: true, isHolding: false,
  holdingGain: null, riskGrade: 2,
};
const nudge = (id: FiredNudge["id"]): FiredNudge => ({ id, text: "", axis: "turnover", ratio: 0.5 });

test("가격 흐름 점수는 계산 근거 문장에서만 범위와 함께 쓰고 개별 지표 방향을 추측하지 않는다", () => {
  const text = psychologyReason(-0.23456);
  assert.match(text, /−0\.23/);
  assert.match(text, /범위 −1/);
  assert.match(text, /20거래일/);
  assert.match(text, /60거래일/);
  assert.doesNotMatch(text, /수익이 낮|현재가가 낮|주가가 하락/);
  assert.match(psychologyReason(0.73), /\+0\.73/);
});

test("설문만으로 뜨는 항목은 종목 조건을 지어내지 않는다", () => {
  assert.match(checkpointReason(nudge("N09"), market), /보유 기간이 짧/);
  assert.match(checkpointReason(nudge("N10"), market), /매매 기준/);
  assert.doesNotMatch(checkpointReason(nudge("N09"), market), /이 종목|시장 조건/);
});

test("종목 조건이 필요한 항목은 설문 답과 관측한 사실을 함께 설명한다", () => {
  for (const id of ["N01", "N02", "N03", "N04", "N06", "N07", "N08", "N11"] as const) {
    const reason = checkpointReason(nudge(id), market);
    assert.match(reason, /답했고/);
    assert.ok(reason.endsWith("표시했어요."));
  }
  assert.match(checkpointReason(nudge("N01"), market), /6거래일/);
  assert.match(checkpointReason(nudge("N04"), market), /상위 10%/);
  assert.match(checkpointReason(nudge("N06"), market), /12.0%/);
  assert.match(checkpointReason(nudge("N07"), market), /10.20/);
});

test("손익 체크포인트는 실제 발화 조건에 따라 평단 또는 고점을 근거로 쓴다", () => {
  assert.match(checkpointReason(nudge("N05"), market), /3개월 최고가보다 20.0% 낮/);
  assert.match(checkpointReason(nudge("N05"), { ...market, holdingGain: -0.12 }), /평균 매입가보다 12.0% 낮/);
  assert.match(checkpointReason(nudge("N05"), { ...market, holdingGain: 0.15 }), /평균 매입가보다 15.0% 높/);
  assert.match(checkpointReason(nudge("N05"), { ...market, holdingGain: 0.02 }), /3개월 최고가/);
});
