import assert from "node:assert/strict";
import test from "node:test";
import { readingProgress, readingSteps } from "./evidence-reading.ts";

const facts: Parameters<typeof readingSteps>[1] = {
  readerType: null,
  overview: { hasSignal: false, history: null },
  model: { hasHistogram: true, hasBars: true, hasReason: false, hasPriceMood: true },
  trading: null,
  news: { hasSummary: true, hasTimeline: true },
  company: { hasRepresentative: true, groups: ["company-earnings", "company-debt", "company-valuation"] },
};

test("화면의 수치를 되풀이하지 않고 비교 방법을 안내해요", () => {
  const steps = readingSteps(["overview", "news", "model", "company"], facts).filter(({ phase }) => phase === "focus");
  assert.deepEqual(steps.map(({ target }) => target), [
    "overview-summary", "news-chart", "news-periods", "model-histogram", "model-bars", "model-price-mood",
    "company-metric", "company-earnings", "company-debt", "company-valuation",
  ]);
  assert.match(steps[1].text, /위로 갈수록 기사 표현이 긍정/);
  assert.match(steps[3].text, /과거에 비슷한 신호가 나왔을 때 실제 수익률은 어땠는지.*이익과 손실 중 어느 쪽 사례가 많았는지/);
  assert.match(steps[4].text, /최대 세 개.*계산 근거/);
  assert.match(steps[5].text, /수익률과 흔들림, 평균 거래 가격 대비 위치/);
  assert.match(steps[6].text, /ⓘ.*코스피 중간값/);
  assert.match(steps[9].text, /비슷한 업종/);
  assert.doesNotMatch(steps.map(({ text }) => text).join(" "), /[0-9]/);
});

test("근거가 없으면 패널 제목에 안내를 붙이고 모르는 수치는 표시하지 않아요", () => {
  const steps = readingSteps(["news", "trading", "model", "company"], {
    ...facts,
    news: { hasSummary: false, hasTimeline: false },
    model: { hasHistogram: false, hasBars: false, hasReason: false, hasPriceMood: false },
    company: { hasRepresentative: false, groups: [] },
  }).filter(({ phase }) => phase === "focus");
  assert.deepEqual(steps.map(({ target }) => target), [
    "news-heading", "trading-heading", "model-heading", "company-heading",
  ]);
  assert.doesNotMatch(steps.map(({ text }) => text).join(" "), /\d+(건|%|주)/);
});

test("한 번 읽는 순서를 안내한 뒤 탭 소개와 확인 사항을 이어서 보여요", () => {
  const tabs = ["overview", "company", "trading", "model", "news"] as const;
  const steps = readingSteps(tabs, facts);
  const [order, ...chapters] = steps;
  assert.deepEqual([order.phase, order.tab, order.target], ["order", "overview", "tab-list"]);
  assert.match(order.text, /주가로 최근 흐름.*모델 신호.*성향에 따라 순서가 달라져요/);
  const [personalized] = readingSteps(tabs, { ...facts, readerType: { type: "FOLLOWER", label: "추종형" } });
  assert.match(personalized.text, /추종형.*수급과 뉴스.*실제 거래와 기사 분위기를 구분/);
  assert.doesNotMatch(personalized.text, /기본 순서/);

  assert.deepEqual(chapters.map(({ phase, tab }) => [phase, tab]), [
    ["features", "overview"], ["focus", "overview"],
    ["features", "company"], ["focus", "company"], ["focus", "company"], ["focus", "company"], ["focus", "company"],
    ["features", "trading"], ["focus", "trading"],
    ["features", "model"], ["focus", "model"], ["focus", "model"], ["focus", "model"],
    ["features", "news"], ["focus", "news"], ["focus", "news"],
  ]);
  assert.deepEqual(steps.slice(0, 5).map((_, index) => readingProgress(steps, index)),
    ["읽는 순서", "한눈에 보기 1/2", "한눈에 보기 2/2", "회사 상태 1/5", "회사 상태 2/5"]);
});

test("재무 안내는 화면에 있는 주제만 짚어요", () => {
  const steps = readingSteps(["company"], {
    ...facts,
    company: { hasRepresentative: false, groups: ["company-debt"] },
  }).filter(({ phase }) => phase === "focus");
  assert.deepEqual(steps.map(({ target }) => target), ["company-debt"]);
  assert.match(steps[0].text, /자본에 비해 빚 부담/);
});

test("실제 범위와 근거가 있는 경우에만 한눈에 보기 세 단계로 안내해요", () => {
  const steps = readingSteps(["overview", "trading"], {
    ...facts,
    overview: { hasSignal: true, history: "similar" },
  });
  const overview = steps.filter(({ phase, tab }) => phase === "focus" && tab === "overview");
  assert.deepEqual(overview.map(({ target }) => target), ["overview-summary", "overview-cohort", "overview-range"]);
  const overviewChapter = steps.filter(({ phase, tab }) => phase !== "order" && tab === "overview");
  assert.deepEqual(overviewChapter.map((step) => readingProgress(steps, steps.indexOf(step))),
    ["한눈에 보기 1/4", "한눈에 보기 2/4", "한눈에 보기 3/4", "한눈에 보기 4/4"]);
  assert.match(overview[0].text, /같은 기간이 지난 뒤의 수익률/);
  assert.match(overview[1].text, /모델이 상승 쪽으로 본 정도와 평소 주가의 흔들림/);
  assert.match(overview[2].text, /같은 기간이 지난 뒤의 수익률이 과거 사례마다.*달랐다는 뜻/);

  const legacy = readingSteps(["overview"], {
    ...facts,
    overview: { hasSignal: true, history: "legacy" },
  }).filter(({ phase }) => phase === "focus");
  assert.match(legacy[1].text, /신호가 본 기간을 기준으로/);
  assert.doesNotMatch(legacy[1].text, /상승 점수|주가의 흔들림/);
});

test("자료가 하루치라면 마지막 날 비교 단계는 표시하지 않아요", () => {
  const oneDay = readingSteps(["trading"], { ...facts, trading: { days: 1 } })
    .filter(({ phase }) => phase === "focus");
  assert.match(oneDay[0].text, /같은 기간의 순매수.*매수나 매도가 한쪽에 몰렸는지/);
  assert.deepEqual(oneDay.map(({ target }) => target), ["trading-total"]);
  const fiveDays = readingSteps(["trading"], { ...facts, trading: { days: 5 } })
    .filter(({ phase }) => phase === "focus");
  assert.match(fiveDays[1].text, /기간 합계와 방향이 다르다면.*전체 흐름과 다르게/);
  assert.doesNotMatch(fiveDays[1].text, /합계와 같아요/);
});
