import { TERM } from "./copy-glossary.ts";

export const READING_START_EVENT = "takealook:reading-start";
export const READING_REPLAY_HASH = "#read-together";

export const READING_INVITATION = "이 종목을 보면서, 각 정보를 언제 보고 어떻게 비교하면 좋을지 알아봐요.";
export const READING_HINT = "다른 종목에서도 숫자가 어느 기간의 값인지, 무엇과 비교했는지 살펴봐요.";
export const READING_ERROR = "안내를 열지 못했어요. 읽는 법을 다시 눌러 주세요.";

export const READING_TAB_LABELS = {
  overview: "한눈에 보기",
  model: TERM.contribution,
  trading: TERM.supply,
  news: TERM.market,
  company: "회사 상태",
};

type ReadingPhase = "features" | "order" | "focus";

export type ReadingTab = keyof typeof READING_TAB_LABELS;
export type ReadingTarget =
  | "tab-button" | "tab-list"
  | "overview-summary" | "overview-cohort" | "overview-range"
  | "model-heading" | "model-summary" | "model-bars"
  | "trading-heading" | "trading-total" | "trading-latest"
  | "news-heading" | "news-summary" | "news-periods"
  | "company-heading" | "company-metric" | "company-basis";

type ReadingStep = {
  id: string;
  phase: ReadingPhase;
  tab: ReadingTab;
  target: ReadingTarget;
  fallback: { target: ReadingTarget; text: string };
  title: string;
  text: string;
};

type ReadingFacts = {
  readerTypeLabel: string | null;
  overview: {
    signal: string | null;
    periodLabel: string;
    history: {
      low: string;
      high: string;
      ciPercent: number;
      cohort: { cases: number; stocks: number; tradingDays: 5 | 20; signalDates: string | null } | null;
    } | null;
  };
  model: { target: string; feature: string } | { reason: string } | null;
  trading: { days: number; hasVolume: boolean } | null;
  news: { period: string; mood: string; count: number; hasTimeline: boolean } | null;
  company: { metricKey: string; metric: string; value: string; period: string; comparison: string | null } | null;
};

function readingStep(
  id: string,
  tab: ReadingTab,
  target: ReadingTarget,
  title: string,
  text: string,
  fallbackTarget: ReadingTarget,
  fallbackText: string,
): ReadingStep {
  return { id, phase: "focus", tab, target, title, text, fallback: { target: fallbackTarget, text: fallbackText } };
}

const TAB_FEATURES: Record<ReadingTab, string> = {
  overview: "종목을 처음 살펴볼 때 여기서 시작해요. 최근 주가와 각 탭의 요약을 훑고, 더 알아보고 싶은 정보를 골라요.",
  model: "모델 신호가 왜 나왔는지 궁금할 때 봐요. 항목별 자료가 있으면 어떤 항목의 영향이 컸는지 비교하고, 다른 탭의 정보와도 함께 살펴봐요.",
  trading: "최근 어떤 투자자들이 더 샀고 더 팔았는지 궁금할 때 봐요. 주가만으로는 알기 어려운 거래 흐름을 개인, 외국인, 기관으로 나눠 살펴봐요.",
  news: "최근 이 회사에 무슨 일이 있었는지 궁금할 때 봐요. 뉴스 분위기와 기사 수를 함께 보고, 대표 기사가 있으면 내용을 살펴봐요.",
  company: "주가와 함께 회사의 사업 상태를 알아보고 싶을 때 봐요. 매출과 이익, 빚 부담을 함께 살펴봐요.",
};

const FINANCIAL_READING = new Map([
  ["debt_ratio", {
    purpose: "빚 부담을 비교할 때는 빚이 자본에 비해 얼마나 큰지 봐요. 빚의 액수만 보면 회사 규모에 따른 차이를 놓칠 수 있어요.",
    change: "부채비율이 높아졌다면 빚이 늘었는지, 자본이 줄었는지 봐요.",
  }],
  ["roe", {
    purpose: "회사가 이익을 내는 힘을 살펴볼 때 봐요. 이익의 액수뿐 아니라 자본에 비해 얼마나 남겼는지 비교해요.",
    change: "ROE가 높아졌다면 순이익이 늘었는지, 자본이 줄었는지 봐요.",
  }],
  ["operating_margin", {
    purpose: "매출이 늘었을 때 본업의 이익도 함께 남는지 살펴봐요. 매출만 늘고 이익은 줄었을 수도 있어요.",
    change: "영업이익률이 달라졌다면 매출과 본업 이익 중 무엇이 바뀌었는지 봐요.",
  }],
  ["revenue_growth", {
    purpose: "회사가 제품이나 서비스를 판 금액이 늘었는지 살펴볼 때 봐요. 보고서에 적힌 매출을 1년 전 같은 기간과 비교해요.",
    change: "증가율이 달라졌다면 비교한 두 기간의 매출을 봐요. 증가율이 낮아져도 0%보다 높으면 매출은 1년 전보다 늘었어요.",
  }],
  ["per", {
    purpose: "주가를 회사가 낸 이익과 함께 살펴볼 때 봐요. 값이 낮다는 이유만으로 좋은 투자라고 판단하지는 않아요.",
    change: "PER이 낮아졌다면 한 주 가격이 내렸는지, 한 주당 이익이 늘었는지 봐요.",
  }],
  ["pbr", {
    purpose: "주가를 회사에 남은 순자산과 함께 살펴볼 때 봐요. 값이 낮다는 이유만으로 좋은 투자라고 판단하지는 않아요.",
    change: "PBR이 낮아졌다면 한 주 가격이 내렸는지, 한 주당 순자산이 늘었는지 봐요.",
  }],
]);

const CHAPTERS: Record<ReadingTab, (facts: ReadingFacts) => ReadingStep[]> = {
  overview: ({ overview }) => {
    const missing = "지금은 표시할 모델 신호가 없어요. 최근 주가나 다른 탭의 요약부터 살펴봐요.";
    const signalText = overview.signal
      ? `${overview.periodLabel} 기준 신호는 ${overview.signal}이에요. 신호를 다른 정보와 함께 볼 때는 먼저 기간을 맞춰요. 기간이 다르면 서로 다른 흐름을 보고 있을 수 있어요.`
      : missing;
    const signal = readingStep("overview", "overview", "overview-summary", "모델 신호의 기간을 확인해요",
      signalText, "overview-summary", missing);
    const { history, periodLabel } = overview;
    if (!history) return [signal];
    const { cohort } = history;
    const stocks = cohort && cohort.stocks > 0 ? `${cohort.stocks.toLocaleString("ko-KR")}개 종목에서 ` : "";
    const dates = cohort?.signalDates ? `${cohort.signalDates}에 나온 신호예요. ` : "";
    const source = cohort
      ? `${stocks}모델의 상승 점수와 평소 가격 흔들림이 지금과 비슷했던 과거 사례 ${cohort.cases.toLocaleString("ko-KR")}건을 모았어요. ${dates}수익률은 신호 당일과 ${cohort.tradingDays}거래일 뒤의 종가를 비교해 구했어요.`
      : `과거 신호가 나온 날을 기준으로 ${periodLabel}의 실제 수익률을 모은 범위예요.`;
    return [
      signal,
      readingStep("overview-cohort", "overview", "overview-cohort", "비교에 쓰인 과거 사례를 확인해요",
        `과거 사례를 참고할 때는 어느 기간의 실제 수익률인지 먼저 확인해요. ${source}`, "overview-summary", signalText),
      readingStep("overview-range", "overview", "overview-range", "과거 수익률이 얼마나 달랐는지 봐요",
        `과거 사례들의 결과가 얼마나 달랐는지 보려면 범위의 폭을 살펴봐요. ${history.low}에서 ${history.high} 사이는 과거 수익률의 가운데 ${history.ciPercent}%에 해당해요. 넓을수록 과거 수익률 차이가 컸어요.`,
        "overview-summary", signalText),
    ];
  },
  model: ({ model }) => {
    const fallback = "지금은 어떤 항목이 모델 점수를 높이거나 낮췄는지 보여 줄 자료가 없어요. 거래 기록이나 뉴스는 다른 탭에서 살펴봐요.";
    const heading = readingStep("model-target", "model", model ? "model-summary" : "model-heading", "모델이 본 항목을 확인해요",
      model && "target" in model
        ? `어떤 항목의 영향이 컸는지 보려면 설명 대상부터 확인해요. 여기서는 ${model.target} 점수를 설명하고, 첫 항목은 ‘${model.feature}’이에요. 현재 신호와 여기서 설명하는 점수의 방향은 다를 수 있어요.`
        : model ? `화면에 표시된 이유는 ‘${model.reason}’이에요. 다른 탭에서 거래 기록과 기사 내용도 살펴봐요.`
          : fallback,
      "model-heading", fallback);
    if (!model || !("target" in model)) return [heading];
    return [heading, readingStep("model-bars", "model", "model-bars", "같은 화면 안에서 막대를 비교해요",
      `오른쪽 막대는 ${model.target} 점수를 높인 정도, 왼쪽은 낮춘 정도예요. 영향이 큰 항목을 찾으려면 가장 긴 막대를 기준으로 이 화면 안에서만 길이를 비교해요. 날짜나 기간이 다른 막대는 길이를 비교할 수 없어요. 막대로 예측 확률이나 수익률은 알 수 없어요.`,
      "model-heading", fallback)];
  },
  trading: ({ trading }) => {
    const fallback = "지금은 표시할 거래 기록이 없어요. 최근 주가나 뉴스는 다른 탭에서 살펴봐요.";
    const heading = readingStep("trading-total", "trading", trading ? "trading-total" : "trading-heading",
      "투자자별로 더 샀는지, 더 팔았는지 봐요",
      trading ? `최근 ${trading.days}영업일 동안 개인, 외국인, 기관이 더 샀는지, 더 팔았는지 큰 숫자를 나란히 봐요. 같은 기간의 순매수 합계라 서로 비교할 수 있어요. +는 판 것보다 더 샀다는 뜻이고, −는 산 것보다 더 팔았다는 뜻이에요.` : fallback,
      "trading-heading", fallback);
    if (!trading) return [heading];
    return [heading, readingStep("trading-latest", "trading", "trading-latest", "기간 전체와 마지막 하루를 비교해요",
      `‘마지막 날’은 합계에 포함된 가장 최근 하루의 순매수예요. ${trading.days === 1
        ? "자료가 1영업일뿐이라 기간 합계와 같아요."
        : "최근 하루도 같은 흐름인지 보려면 기간 전체와 마지막 날에 더 샀는지, 더 팔았는지 비교해요."} ${trading.hasVolume
        ? "거래 규모에 비해 어느 정도인지 보려면 비율도 봐요. 합계의 크기를 같은 기간 하루 평균 거래량과 비교한 값이에요."
        : "거래량 자료가 없어 이 비율은 표시하지 않아요."}`,
      "trading-heading", fallback)];
  },
  news: ({ news }) => {
    const fallback = "지금은 표시할 뉴스 분위기 자료가 없어요. 다른 탭에서 회사 정보나 거래 기록을 살펴볼 수 있어요.";
    const heading = readingStep("news-summary", "news", news ? "news-summary" : "news-heading", "기사 수와 집계 기준을 확인해요",
      news ? `${news.period} 기준 기사 ${news.count.toLocaleString("ko-KR")}건의 분위기는 ‘${news.mood}’이에요. 분위기가 달라졌다면 기간과 기사 수를 함께 비교해요. 기사가 적으면 한 기사가 전체 분위기에 미치는 영향이 커요.` : fallback,
      "news-heading", fallback);
    if (!news?.hasTimeline) return [heading];
    return [heading, readingStep("news-periods", "news", "news-periods", "기간을 맞춰 뉴스 분위기를 비교해요",
      "며칠 사이 변화는 일별로, 더 긴 변화는 월별이나 연별로 봐요. 안내가 끝나면 그래프의 점을 눌러 그때의 분위기를 확인해요. 기사가 적다는 표시가 있으면 참고로만 봐요. 대표 기사가 있으면 내용도 살펴봐요.",
      "news-heading", fallback)];
  },
  company: ({ company }) => {
    const fallback = "지금은 표시할 재무 지표가 없어요. 회사가 공개한 자료가 있는지 ‘최근 공시’에서 살펴봐요.";
    const guidance = company && FINANCIAL_READING.get(company.metricKey);
    const purpose = guidance?.purpose ?? "이 지표에서 회사의 재무 상태를 확인해요.";
    const comparison = company?.comparison
      ? `${company.comparison} 이 비교로 대략적인 위치를 살펴봐요. 여러 업종의 코스피 회사 자료를 모은 기준이라 높고 낮음만으로 회사 상태를 판단하지는 않아요.`
      : "지금은 표시할 비교 기준이 없어요.";
    const heading = readingStep("company-metric", "company", company ? "company-metric" : "company-heading", "재무 지표와 비교 기준을 함께 봐요",
      company ? `${purpose} 현재 ${company.metric} 값은 ${company.value}예요. ${comparison}` : fallback,
      "company-heading", fallback);
    if (!company) return [heading];
    const change = guidance ? ` ${guidance.change}` : "";
    return [heading, readingStep("company-basis", "company", "company-basis", "보고서가 다루는 기간을 확인해요",
      `${company.period} 자료예요. ‘계산 근거’에서 회사와 비교 기준의 보고서 기간을 볼 수 있어요. 변화는 기간 길이가 같은 이전 보고서의 같은 지표와 비교해요.${change}`,
      "company-heading", fallback)];
  },
};

export function readingSteps(tabs: readonly ReadingTab[], facts: ReadingFacts): ReadingStep[] {
  const order = tabs.map((tab) => READING_TAB_LABELS[tab]).join(" → ");
  const purpose = "각 정보를 언제, 왜 보고 어떻게 비교하면 좋을지 살펴봐요.";
  const orderText = facts.readerTypeLabel
    ? `${purpose} 성향 진단에서 나온 ‘${facts.readerTypeLabel}’에 맞춰 ${order} 순으로 봐요.`
    : `${purpose} 기본 순서는 ${order}예요. 성향 진단 후에는 투자 유형에 따라 순서가 달라질 수 있어요.`;
  return [
    {
      id: "reading-order",
      phase: "order",
      tab: "overview",
      target: "tab-list",
      title: "이 순서로 살펴봐요",
      text: orderText,
      fallback: { target: "tab-button", text: orderText },
    },
    ...tabs.flatMap((tab): ReadingStep[] => [
      {
        id: `features-${tab}`,
        phase: "features",
        tab,
        target: "tab-button",
        title: READING_TAB_LABELS[tab],
        text: TAB_FEATURES[tab],
        fallback: { target: "tab-list", text: TAB_FEATURES[tab] },
      },
      ...CHAPTERS[tab](facts),
    ]),
  ];
}

export function readingProgress(steps: readonly ReadingStep[], index: number): string {
  const current = steps[index];
  if (current.phase === "order") return "읽는 순서";
  const chapter = steps.filter(({ phase, tab }) => phase !== "order" && tab === current.tab);
  return `${READING_TAB_LABELS[current.tab]} ${chapter.indexOf(current) + 1}/${chapter.length}`;
}
