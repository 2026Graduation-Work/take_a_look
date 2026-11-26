import assert from "node:assert/strict";
import { test } from "node:test";
import { priceEventSourceMessages, priceMoveMessages } from "./price-event-messages.ts";
import type { SourceResult, SourceUnavailableReason } from "./providers/price-event-context.ts";

const checkedAt = "2026-11-25T18:00:00Z";
const empty: Extract<SourceResult<unknown>, { status: "available" }> = {
  status: "available", items: [], fetchedAt: checkedAt, coverage: "unverified",
  truncated: false, refresh: { status: "idle" },
};

test("가격 판정이 불가능한 사유, 비교 거래일 없음과 기준 초과 후보 0개를 구분한다", () => {
  for (const [reason, copy] of [
    ["missing_basis", "기준이 없어요"],
    ["invalid_basis", "기준을 확인할 수 없어요"],
    ["incomplete_sessions", "가격 기록의 개수나 날짜가 맞지 않아"],
    ["mismatched_periods", "기간마다 가격 기록이나 계산 기준이 달라"],
    ["no_evaluable_returns", "비교할 수 있는 거래일이 없어요"],
  ] as const) {
    assert.ok(priceMoveMessages({ status: "unavailable", reason }).message?.includes(copy));
  }
  assert.deepEqual(priceMoveMessages({ status: "ready", moves: [], evaluatedDays: 59, excludedDays: 1 }), {
    message: "확인한 날 중 기준을 넘은 날이 없어요.",
    coverageNote: "일부 거래일은 비교하지 못했어요.",
  });
});

test("관측된 출처 오류는 고정된 안내를 사용하며 미제공이나 접근 거절에는 재시도를 권하지 않는다", () => {
  const cases: [SourceUnavailableReason, RegExp, boolean][] = [
    ["query_failed", /자료를 불러오지 못했어요/, true],
    ["no_response", /연결 상태를 확인해 주세요/, true],
    ["server_error", /서버에서 오류가 났어요/, true],
    ["access_denied", /이 자료에 접근할 수 없어요/, false],
    ["rate_limited", /조회 요청이 제한돼/, true],
    ["timeout", /시간이 오래 걸려 중단했어요/, true],
    ["invalid_response", /자료의 형식이 맞지 않아/, true],
    ["not_configured", /지금 제공하지 않아요/, false],
    ["usage_not_approved", /지금 제공하지 않아요/, false],
  ];
  for (const [reason, copy, canRetry] of cases) {
    const messages = priceEventSourceMessages("disclosures", { status: "unavailable", reason });
    assert.match(messages.message ?? "", copy);
    assert.equal(messages.canRetry, canRetry);
  }
});

test("갱신 중과 실패에서 이전 0건을 과거형과 확인 시각으로 안내한다", () => {
  const loading = priceEventSourceMessages("disclosures", { ...empty, refresh: { status: "loading" } });
  assert.equal(loading.message, "지난번에 조회된 공시가 없었어요.");
  assert.match(loading.refreshNote ?? "", /새로 확인하는 중/);
  assert.equal(loading.lastCheckedAt, checkedAt);
  assert.equal(loading.canRetry, false);

  const failed = priceEventSourceMessages("market", {
    ...empty, emptyReason: "no_rows", refresh: { status: "failed", reason: "timeout" },
  });
  assert.equal(failed.message, "지난번에 조회된 이날 코스피 자료가 없었어요.");
  assert.match(failed.refreshNote ?? "", /오래 걸려 중단했어요/);
  assert.equal(failed.lastCheckedAt, checkedAt);
  assert.equal(failed.canRetry, true);
});

test("부분 자료와 상한 안내를 함께 보존하고 성공 0건에는 새 결과만 안내한다", () => {
  const previous = priceEventSourceMessages("disclosures", {
    ...empty, items: [{}], coverage: "known_partial", truncated: true,
    refresh: { status: "failed", reason: "access_denied" },
  });
  assert.equal(previous.coverageNote, "형식이 맞지 않는 공시는 뺐어요. 조회 한도에 도달해 공시가 더 있는지 확인하지 못했어요.");
  assert.match(previous.refreshNote ?? "", /접근할 수 없어요. 이전 조회 자료를 표시해요/);
  assert.equal(previous.lastCheckedAt, checkedAt);
  assert.equal(previous.canRetry, false);

  const current = priceEventSourceMessages("disclosures", empty);
  assert.equal(current.message, "조회된 공시가 없어요.");
  assert.equal(current.coverageNote, "수집 범위를 확인하지 못했어요.");
  assert.equal(current.refreshNote, undefined);
  assert.equal(current.lastCheckedAt, undefined);
  assert.equal(current.canRetry, false);
});
