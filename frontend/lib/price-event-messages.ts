import type { PriceMoveResult } from "./price-events.ts";
import { canRetryEventSource, type SourceResult, type SourceUnavailableReason } from "./providers/price-event-context.ts";

const priceMoveFailure = {
  missing_basis: "이 차트에는 변동일을 고르는 기준이 없어요.",
  invalid_basis: "변동일을 고르는 기준을 확인할 수 없어요.",
  incomplete_sessions: "가격 기록의 개수나 날짜가 맞지 않아 변동일을 확인할 수 없어요.",
  mismatched_periods: "기간마다 가격 기록이나 계산 기준이 달라 변동일을 확인할 수 없어요.",
  no_evaluable_returns: "가격 변화를 비교할 수 있는 거래일이 없어요.",
};

export function priceMoveMessages(result: PriceMoveResult) {
  if (result.status === "unavailable") return { message: priceMoveFailure[result.reason] };
  return {
    message: result.moves.length ? undefined : "확인한 날 중 기준을 넘은 날이 없어요.",
    coverageNote: result.excludedDays ? "일부 거래일은 비교하지 못했어요." : undefined,
  };
}

const readFailure: Record<SourceUnavailableReason, string> = {
  query_failed: "자료를 불러오지 못했어요.",
  no_response: "자료를 받지 못했어요. 연결 상태를 확인해 주세요.",
  server_error: "자료를 보낸 서버에서 오류가 났어요.",
  access_denied: "이 자료에 접근할 수 없어요.",
  rate_limited: "조회 요청이 제한돼 지금은 자료를 확인할 수 없어요.",
  timeout: "자료를 불러오는 데 시간이 오래 걸려 중단했어요.",
  invalid_response: "받은 자료의 형식이 맞지 않아 표시할 수 없어요.",
  not_configured: "이 자료는 지금 제공하지 않아요.",
  usage_not_approved: "이 자료는 지금 제공하지 않아요.",
};

export type EventSource = "market" | "disclosures" | "news";

type SourceMessages = {
  message?: string;
  coverageNote?: string;
  refreshNote?: string;
  lastCheckedAt?: string;
  canRetry: boolean;
};

export function priceEventSourceMessages(name: EventSource, result: SourceResult<unknown>): SourceMessages {
  if (result.status === "loading") return { message: "자료를 불러오는 중이에요.", canRetry: false };
  if (result.status === "unavailable") return { message: readFailure[result.reason], canRetry: canRetryEventSource(result.reason) };
  const { items, emptyReason, coverage, truncated, fetchedAt, refresh } = result;
  const previous = refresh.status !== "idle";
  let message;
  let coverageNote;
  if (name === "market" && !items.length) {
    if (emptyReason === "no_rows") {
      message = previous ? "지난번에 조회된 이날 코스피 자료가 없었어요." : "이날 조회된 코스피 자료가 없어요.";
    } else {
      message = previous ? "지난번 자료에는 코스피 등락률이 없었어요." : "이날 코스피 등락률이 자료에 없어요.";
    }
  }
  if (name === "disclosures") {
    if (!items.length) message = previous ? "지난번에 조회된 공시가 없었어요." : "조회된 공시가 없어요.";
    if (truncated) {
      const limitNote = "조회 한도에 도달해 공시가 더 있는지 확인하지 못했어요.";
      coverageNote = coverage === "known_partial" ? `형식이 맞지 않는 공시는 뺐어요. ${limitNote}` : limitNote;
    } else if (coverage === "known_partial") {
      coverageNote = "형식이 맞지 않는 공시를 빼고 일부만 표시해요.";
    } else {
      coverageNote = "수집 범위를 확인하지 못했어요.";
    }
  }
  let refreshNote;
  if (refresh.status === "loading") refreshNote = "새로 확인하는 중이에요.";
  if (refresh.status === "failed") {
    let failure = readFailure[refresh.reason];
    if (refresh.reason === "timeout") failure = "새로 확인하는 데 시간이 오래 걸려 중단했어요.";
    if (refresh.reason === "invalid_response") failure = "새 자료의 형식이 맞지 않아 갱신하지 못했어요.";
    refreshNote = items.length ? `${failure} 이전 조회 자료를 표시해요.` : failure;
  }
  return {
    message,
    coverageNote,
    refreshNote,
    lastCheckedAt: previous ? fetchedAt : undefined,
    canRetry: refresh.status === "failed" && canRetryEventSource(refresh.reason),
  };
}
