import assert from "node:assert/strict";
import test from "node:test";
import { readingProgress, readingSteps } from "./evidence-reading.ts";

const facts: Parameters<typeof readingSteps>[1] = {
  readerTypeLabel: null,
  overview: { signal: null, periodLabel: "2주 뒤", history: null },
  model: { target: "하락", feature: "가상 항목" },
  trading: null,
  news: { period: "2026.09.21 09:13", count: 3, mood: "중립", hasTimeline: true },
  company: { metricKey: "operating_margin", metric: "영업이익률", value: "0%", period: "2026년 반기", comparison: "코스피 중간값 4.5%보다 낮아요." },
};

test("화면에 제공된 기사 수, 모델 대상, 0% 재무 값을 안내에 써요", () => {
  const steps = readingSteps(["overview", "news", "model", "company"], facts).filter(({ phase }) => phase === "focus");
  assert.deepEqual(steps.map(({ target }) => target), [
    "overview-summary", "news-summary", "news-periods", "model-summary", "model-bars", "company-metric", "company-basis",
  ]);
  assert.match(steps[1].text, /2026\.09\.21 09:13.*3건.*중립/);
  assert.match(steps[4].text, /오른쪽 막대는 하락 점수를 높이고/);
  assert.match(steps[5].text, /본업의 이익.*영업이익률.*0%.*코스피 중간값 4.5%보다 낮아요/);
  assert.match(steps[6].text, /2026년 반기.*매출과 본업 이익 중 무엇이 바뀌었는지/);
});

test("근거가 없으면 패널 제목에 안내를 붙이고 모르는 수치는 표시하지 않아요", () => {
  const steps = readingSteps(["news", "trading", "model", "company"], {
    ...facts, news: null, model: null, company: null,
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
  assert.match(order.text, /각 탭을 언제 열고, 무엇과 비교.*기본 순서/);
  assert.match(order.text, /투자 유형에 따라 순서가 달라질 수 있어요/);
  assert.match(order.text, /한눈에 보기 → 회사 상태 → 누가 사고팔았나 → 모델이 본 이유 → 시장 분위기/);
  const [personalized] = readingSteps(tabs, { ...facts, readerTypeLabel: "추종형" });
  assert.match(personalized.text, /성향 진단.*추종형/);
  assert.doesNotMatch(personalized.text, /기본 순서/);

  assert.deepEqual(chapters.map(({ phase, tab }) => [phase, tab]), [
    ["features", "overview"], ["focus", "overview"],
    ["features", "company"], ["focus", "company"], ["focus", "company"],
    ["features", "trading"], ["focus", "trading"],
    ["features", "model"], ["focus", "model"], ["focus", "model"],
    ["features", "news"], ["focus", "news"], ["focus", "news"],
  ]);
  assert.deepEqual(steps.slice(0, 5).map((_, index) => readingProgress(steps, index)),
    ["읽는 순서", "한눈에 보기 1/2", "한눈에 보기 2/2", "회사 상태 1/3", "회사 상태 2/3"]);
});

test("알 수 없는 재무 지표에는 있는 값만 쓰고 비교 기준을 지어내지 않아요", () => {
  const steps = readingSteps(["overview", "company"], {
    ...facts,
    company: { metricKey: "unknown", metric: "기타 지표", value: "0배", period: "2026년 반기", comparison: null },
  }).filter(({ phase, tab }) => phase === "focus" && tab === "company");
  assert.match(steps[0].text, /기타 지표.*0배.*표시할 비교 기준은 없어요/);
  assert.doesNotMatch(steps[0].text, /코스피|업종/);
  assert.match(steps[1].text, /기간 길이를 맞춘 이전 보고서의 같은 지표/);
});

test("실제 범위와 근거가 있는 경우에만 한눈에 보기 세 단계로 안내해요", () => {
  const steps = readingSteps(["overview", "trading"], {
    ...facts,
    overview: {
      signal: "상승",
      periodLabel: "4주 뒤",
      history: {
        low: "−3.2%", high: "+4.7%", ciPercent: 68,
        cohort: { cases: 83, stocks: 6, tradingDays: 20, signalDates: "2024.01.01~2025.03.01" },
      },
    },
  });
  const overview = steps.filter(({ phase, tab }) => phase === "focus" && tab === "overview");
  assert.deepEqual(overview.map(({ target }) => target), ["overview-summary", "overview-cohort", "overview-range"]);
  const overviewChapter = steps.filter(({ phase, tab }) => phase !== "order" && tab === "overview");
  assert.deepEqual(overviewChapter.map((step) => readingProgress(steps, steps.indexOf(step))),
    ["한눈에 보기 1/4", "한눈에 보기 2/4", "한눈에 보기 3/4", "한눈에 보기 4/4"]);
  assert.match(overview[0].text, /4주 뒤 기준 신호는 상승/);
  assert.match(overview[1].text, /6개 종목.*상승 점수.*평소 가격 흔들림.*83건/);
  assert.match(overview[1].text, /2024\.01\.01~2025\.03\.01.*신호 당일과 20거래일 뒤의 종가/);
  assert.match(overview[2].text, /−3.2%에서 \+4.7%.*가운데 68%/);

  const legacy = readingSteps(["overview"], {
    ...facts,
    overview: { ...facts.overview, signal: "상승", history: { low: "0%", high: "+5%", ciPercent: 68, cohort: null } },
  }).filter(({ phase }) => phase === "focus");
  assert.match(legacy[0].text, /2주 뒤 기준 신호는 상승/);
  assert.match(legacy[1].text, /과거 신호.*2주 뒤의 실제 수익률/);
  assert.doesNotMatch(legacy[1].text, /상승 점수|가격 흔들림/);
});

test("마지막 날과 기간 전체가 같은 때를 구분해 설명해요", () => {
  const oneDay = readingSteps(["trading"], { ...facts, trading: { days: 1, hasVolume: true } })
    .filter(({ phase }) => phase === "focus");
  assert.match(oneDay[0].text, /1영업일의 합계.*개인, 외국인, 기관/);
  assert.match(oneDay[1].text, /1영업일뿐이라 기간 합계와 같아요.*같은 기간 하루 평균 거래량/);
  const fiveDays = readingSteps(["trading"], { ...facts, trading: { days: 5, hasVolume: false } })
    .filter(({ phase }) => phase === "focus");
  assert.match(fiveDays[0].text, /5영업일의 합계/);
  assert.match(fiveDays[1].text, /기간 전체와 마지막 하루의 거래 방향이 같은지.*거래량 자료가 없어/);
  assert.doesNotMatch(fiveDays[1].text, /합계와 같아요/);
});
