import { TERM } from "./copy-glossary.ts";

export const READING_START_EVENT = "takealook:reading-start";
export const READING_REPLAY_HASH = "#read-together";

export const READING_INVITATION = "이 종목을 보며 근거 읽는 순서를 익혀요.";
export const READING_HINT = "다른 종목에서도 숫자의 기간과 비교 기준부터 확인해 보세요.";
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
  overview: "어디부터 살펴볼지 막막할 때 열어 보세요. 최근 주가와 모델 신호, 다른 탭의 요약을 보고 더 확인할 근거를 골라요.",
  model: "모델 신호가 어떤 근거에서 나왔는지 궁금할 때 봐요. 어떤 항목이 모델 점수를 높이거나 낮췄는지 확인해요.",
  trading: "최근 누가 더 많이 사고팔았는지 궁금할 때 봐요. 개인, 외국인, 기관의 순매수 수량을 같은 기간으로 비교해요.",
  news: "이 종목을 둘러싼 뉴스 분위기가 달라졌는지 궁금할 때 봐요. 분위기 변화와 함께 기사 수와 새로운 소식을 확인해요.",
  company: "주가와 별개로 회사가 돈을 얼마나 벌고 빚을 얼마나 지고 있는지 알고 싶을 때 봐요. 재무 지표와 최근 공시를 함께 확인해요.",
};

const FINANCIAL_READING = new Map([
  ["debt_ratio", {
    purpose: "회사가 자기 돈에 비해 빚을 얼마나 지고 있는지 보려고 읽어요.",
    change: "부채비율이 높아졌다면 빚이 늘었는지, 자기 돈이 줄었는지 나눠 봐요.",
  }],
  ["roe", {
    purpose: "회사가 자기 돈으로 이익을 얼마나 냈는지 보려고 읽어요.",
    change: "ROE가 높아졌다면 이익이 늘었는지, 자기 돈이 줄었는지 나눠 봐요.",
  }],
  ["operating_margin", {
    purpose: "매출 가운데 본업의 이익으로 얼마나 남았는지 보려고 읽어요.",
    change: "이익률이 달라졌다면 매출과 본업 이익 중 무엇이 바뀌었는지 살펴봐요.",
  }],
  ["revenue_growth", {
    purpose: "회사의 매출이 1년 전보다 얼마나 늘었는지 보려고 읽어요.",
    change: "증가율이 낮아져도 매출은 늘었을 수 있어요. 증가율의 부호와 크기를 구분해요.",
  }],
  ["per", {
    purpose: "한 주 가격이 한 주당 이익의 몇 배인지 보려고 읽어요.",
    change: "PER이 낮아졌다면 주가가 내렸는지, 한 주당 이익이 늘었는지 나눠 봐요.",
  }],
  ["pbr", {
    purpose: "한 주 가격이 한 주당 순자산의 몇 배인지 보려고 읽어요.",
    change: "PBR이 낮아졌다면 주가가 내렸는지, 한 주당 순자산이 늘었는지 나눠 봐요.",
  }],
]);

const CHAPTERS: Record<ReadingTab, (facts: ReadingFacts) => ReadingStep[]> = {
  overview: ({ overview }) => {
    const missing = "현재 제공된 모델 신호가 없어요. 최근 주가와 다른 탭의 근거부터 살펴봐요.";
    const signalText = overview.signal
      ? `현재 ${overview.periodLabel} 기준 신호는 ${overview.signal}이에요. 신호와 근거는 같은 기간으로 맞춰 비교해요.`
      : missing;
    const signal = readingStep("overview", "overview", "overview-summary", "신호의 기간부터 확인해요",
      signalText, "overview-summary", missing);
    const { history, periodLabel } = overview;
    if (!history) return [signal];
    const { cohort } = history;
    const stocks = cohort && cohort.stocks > 0 ? `${cohort.stocks.toLocaleString("ko-KR")}개 종목에서 ` : "";
    const dates = cohort?.signalDates ? `${cohort.signalDates}에 나온 신호예요. ` : "";
    const source = cohort
      ? `${stocks}모델의 상승 점수와 평소 가격 흔들림이 지금과 비슷했던 과거 사례 ${cohort.cases.toLocaleString("ko-KR")}건을 모았어요. ${dates}각 사례에서 신호 당일과 ${cohort.tradingDays}거래일 뒤의 종가를 비교했어요.`
      : `과거 신호가 나온 뒤 ${periodLabel}의 실제 수익률을 모아 만든 범위예요.`;
    return [
      signal,
      readingStep("overview-cohort", "overview", "overview-cohort", "어떤 과거 사례를 모았나요?",
        source, "overview-summary", signalText),
      readingStep("overview-range", "overview", "overview-range", "범위가 얼마나 넓은지 봐요",
        `${history.low}에서 ${history.high} 사이는 과거 사례의 가운데 ${history.ciPercent}%를 나타내는 범위예요. 폭이 넓으면 과거 사례의 수익률 차이가 컸다는 뜻이에요.`,
        "overview-summary", signalText),
    ];
  },
  model: ({ model }) => {
    const fallback = "모델이 무엇을 봤는지 알아야 신호를 함께 읽을 수 있어요. 지금은 연결된 근거가 없어 영향 방향이나 크기를 비교하기 어려워요.";
    const heading = readingStep("model-target", "model", model ? "model-summary" : "model-heading", "모델이 어떤 근거에 반응했는지 봐요",
      model && "target" in model
        ? `신호가 한 가지 근거에 쏠렸는지 확인하려고 읽어요. 이번 설명 대상은 ${model.target} 점수이고, 첫 항목은 ‘${model.feature}’이에요. 화면의 신호와 설명 대상 점수가 다를 수 있어요.`
        : model ? `현재 보여 주는 근거는 ‘${model.reason}’이에요. 다른 탭의 거래나 뉴스 내용과 함께 살펴봐요.`
          : fallback,
      "model-heading", fallback);
    if (!model || !("target" in model)) return [heading];
    return [heading, readingStep("model-bars", "model", "model-bars", "막대는 같은 화면 안에서 비교해요",
      `오른쪽 막대는 ${model.target} 점수를 높이고, 왼쪽은 낮춘 항목이에요. 가장 긴 막대를 기준으로 같은 화면의 길이를 비교해요. 날짜나 기간이 다른 막대 길이로 영향의 증감을 판단할 수 없어요. 막대는 모델 점수에 미친 정도이며, 예측 확률이나 수익률은 아니에요.`,
      "model-heading", fallback)];
  },
  trading: ({ trading }) => {
    const fallback = "어느 투자자가 더 샀는지 보려면 같은 기간의 사고판 기록이 필요해요. 지금은 표시할 자료가 없어 거래 방향을 비교하기 어려워요.";
    const heading = readingStep("trading-total", "trading", trading ? "trading-total" : "trading-heading",
      "어느 투자자의 거래가 두드러졌는지 봐요",
      trading ? `주가만 봐서는 누가 사거나 팔았는지 알 수 없어요. 강조한 큰 숫자는 최근 ${trading.days}영업일의 합계예요. 개인, 외국인, 기관을 나란히 보며 누구의 매수나 매도가 두드러졌는지 확인해요.` : fallback,
      "trading-heading", fallback);
    if (!trading) return [heading];
    return [heading, readingStep("trading-latest", "trading", "trading-latest", "기간 전체와 마지막 하루를 나눠 봐요",
      `‘마지막 날’ 옆의 작은 숫자는 합계에 들어간 가장 최근 하루의 거래예요. ${trading.days === 1
        ? "지금은 자료가 1영업일뿐이라 기간 합계와 같아요."
        : "기간 전체와 마지막 하루의 거래 방향이 같은지 견줘 봐요."} ${trading.hasVolume
        ? "거래량 비율은 합계의 크기를 같은 기간 하루 평균 거래량과 견줘, 수량이 거래 규모에 비해 어느 정도인지 볼 때 써요."
        : "거래량 자료가 없어 대비 비율은 표시되지 않아요."}`,
      "trading-heading", fallback)];
  },
  news: ({ news }) => {
    const fallback = "수집된 기사가 있어야 분위기를 비교할 수 있어요. 지금은 표시할 뉴스 분위기 자료가 없어요.";
    const heading = readingStep("news-summary", "news", news ? "news-summary" : "news-heading", "기사 수와 수집 시점을 봐요",
      news ? `기사의 분위기가 어느 쪽인지 살펴봐요. ${news.period} 기준 기사 ${news.count.toLocaleString("ko-KR")}건의 분위기는 ‘${news.mood}’이에요. 전과 비교할 때는 수집 시점과 기사 수도 봐요. 기사가 적으면 한 기사의 영향이 커요.` : fallback,
      "news-heading", fallback);
    if (!news?.hasTimeline) return [heading];
    return [heading, readingStep("news-periods", "news", "news-periods", "기간을 맞춰 뉴스 분위기를 비교해요",
      "짧은 변화를 보려면 일별, 큰 흐름을 보려면 월별이나 연별로 비교해요. 분위기가 달라졌다면 기사 수와 대표 기사도 함께 봐요.",
      "news-heading", fallback)];
  },
  company: ({ company }) => {
    const fallback = "회사의 이익이나 빚 부담을 비교하려면 재무 자료가 필요해요. 지금은 표시할 지표가 없어요. 최근 공시에 확인할 자료가 있는지 살펴봐요.";
    const guidance = company && FINANCIAL_READING.get(company.metricKey);
    const purpose = guidance?.purpose ?? "가격과 별개로 회사의 상태를 확인하려고 읽어요.";
    const comparison = company?.comparison
      ? `${company.comparison} 중간값은 코스피 회사들의 가운데 수준이에요. 여러 업종이 섞여 있어 대략적인 위치로 봐요.`
      : "현재 표시할 비교 기준은 없어요.";
    const heading = readingStep("company-metric", "company", company ? "company-metric" : "company-heading", "재무 지표를 비교 기준과 함께 봐요",
      company ? `${purpose} 현재 ${company.metric} 값은 ${company.value}예요. ${comparison}` : fallback,
      "company-heading", fallback);
    if (!company) return [heading];
    const change = guidance ? ` ${guidance.change}` : "";
    return [heading, readingStep("company-basis", "company", "company-basis", "같은 기준의 보고서와 비교해요",
      `${company.period} 자료예요. 안내 뒤 계산 근거에서 회사와 비교 기준의 보고서 기간을 확인해요.${change} 증감은 기간 길이를 맞춘 이전 보고서의 같은 지표와 비교해요.`,
      "company-heading", fallback)];
  },
};

export function readingSteps(tabs: readonly ReadingTab[], facts: ReadingFacts): ReadingStep[] {
  const order = tabs.map((tab) => READING_TAB_LABELS[tab]).join(" → ");
  const purpose = "각 탭을 언제 열고, 무엇과 비교하는지 살펴봐요.";
  const orderText = facts.readerTypeLabel
    ? `${purpose} 성향 진단 결과인 ‘${facts.readerTypeLabel}’에 맞춰 ${order} 순으로 봐요.`
    : `${purpose} 기본 순서는 ${order}예요. 성향 진단 후에는 투자 유형에 따라 순서가 달라질 수 있어요.`;
  return [
    {
      id: "reading-order",
      phase: "order",
      tab: "overview",
      target: "tab-list",
      title: "어떤 순서로 보면 되나요?",
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
