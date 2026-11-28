import type { BitType } from "./profiling/bit.ts";
import { TERM } from "./copy-glossary.ts";

export const READING_START_EVENT = "takealook:reading-start";
export const READING_REPLAY_HASH = "#read-together";

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
  | "model-heading" | "model-histogram" | "model-bars" | "model-price-mood"
  | "trading-heading" | "trading-total" | "trading-latest"
  | "news-heading" | "news-summary" | "news-chart" | "news-periods"
  | "company-heading" | "company-metric" | CompanyReadingGroup;

export type CompanyReadingGroup = "company-earnings" | "company-debt" | "company-valuation";

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
  readerType: { type: BitType; label: string } | null;
  overview: { hasSignal: boolean; history: "similar" | "legacy" | null };
  model: { hasHistogram: boolean; hasBars: boolean; hasReason: boolean; hasPriceMood: boolean };
  trading: { days: number } | null;
  news: { hasSummary: boolean; hasTimeline: boolean };
  company: { hasRepresentative: boolean; groups: readonly CompanyReadingGroup[] };
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
  overview: "처음 보는 종목이라면 최근 주가부터 보고, 더 궁금한 내용은 다른 탭에서 찾아봐요.",
  model: "모델 점수에 영향을 준 신호를 확인할 수 있어요. 거래나 뉴스에서도 비슷한 흐름이 보이는지 살펴볼 때 참고해요.",
  trading: "주가가 움직인 배경을 살필 때, 어느 투자자가 주로 사고팔았는지도 단서가 돼요.",
  news: "뉴스와 공시는 투자자의 기대와 주가에 영향을 줄 수 있어요. 회사 소식이 어떻게 다뤄졌는지 살펴봐요.",
  company: "꾸준히 이익을 내고 빚을 감당하는지는 회사의 장기적인 가치에 영향을 줘요. 재무 지표에서 그 단서를 살펴봐요.",
};

const ORDER_REASONS: Record<BitType, string> = {
  PRESERVER: "주가를 훑은 뒤 시장 분위기와 회사 상태를 먼저 봐요. 기사 분위기와 회사의 이익, 빚을 나눠 살펴볼 수 있어요.",
  FOLLOWER: "주가를 훑은 뒤 수급과 뉴스를 먼저 봐요. 실제 거래와 기사 분위기를 구분해 볼 수 있어요.",
  INDEPENDENT: "주가를 훑은 뒤 모델 근거와 재무를 먼저 봐요. 서로 다른 자료로 한쪽 판단에 치우치지 않게 살펴봐요.",
  ACCUMULATOR: "주가를 훑은 뒤 모델 근거와 뉴스를 먼저 봐요. 신호와 관련 소식을 함께 보면 판단할 근거가 늘어요.",
};

const FINANCIAL_GUIDANCE: Record<CompanyReadingGroup, { title: string; text: string }> = {
  "company-earnings": {
    title: "매출과 이익",
    text: "매출이 늘었다면 본업에서 남긴 이익도 함께 봐요. 비용이 더 늘면 매출이 늘어도 이익은 줄 수 있어요.",
  },
  "company-debt": {
    title: "자산과 빚",
    text: "빚의 크기는 회사 규모와 함께 봐요. 부채비율은 회사 자본에 비해 빚 부담이 얼마나 큰지 가늠하는 데 도움이 돼요.",
  },
  "company-valuation": {
    title: "주가와 비교",
    text: "주가를 이익이나 순자산과 견줘 얼마나 높게 평가받는지 봐요. 비슷한 업종의 회사끼리 비교하면 해석하기 쉬워요.",
  },
};

const CHAPTERS: Record<ReadingTab, (facts: ReadingFacts) => ReadingStep[]> = {
  overview: ({ overview }) => {
    const missing = "지금은 표시할 모델 신호가 없어요. 최근 주가부터 살펴볼 수 있어요.";
    const signalText = overview.history
      ? "과거 사례도 모델 신호와 같은 기간이 지난 뒤의 수익률로 비교해요."
      : overview.hasSignal ? "신호가 어느 시점의 흐름을 보는지 기간부터 확인해요." : missing;
    const signal = readingStep("overview", "overview", "overview-summary", "모델 신호의 기간",
      signalText, "overview-summary", missing);
    if (!overview.history) return [signal];
    return [
      signal,
      readingStep("overview-cohort", "overview", "overview-cohort", "비교에 쓰인 과거 사례",
        overview.history === "similar"
          ? "모델이 상승 쪽으로 본 정도와 평소 주가의 흔들림이 비슷했던 과거 사례를 모았어요."
          : "과거 신호가 나온 뒤 실제 수익률을 모았어요. 신호가 본 기간을 기준으로 결과를 읽어요.",
        "overview-summary", signalText),
      readingStep("overview-range", "overview", "overview-range", "과거 수익률 범위",
        "폭이 넓으면 같은 기간이 지난 뒤의 수익률이 과거 사례마다 많이 달랐다는 뜻이에요.", "overview-summary", signalText),
    ];
  },
  model: ({ model }) => {
    const fallback = "관련 자료를 확인하기 어려워요. 최근 주가나 뉴스는 다른 탭에서 볼 수 있어요.";
    const steps: ReadingStep[] = [];
    if (model.hasHistogram) steps.push(readingStep("model-histogram", "model", "model-histogram", "과거 수익률이 모인 구간",
      "과거에 비슷한 신호가 나왔을 때 실제 수익률은 어땠는지 살펴봐요. 이익과 손실 중 어느 쪽 사례가 많았는지도 볼 수 있어요.", "model-heading", fallback));
    if (model.hasBars) steps.push(readingStep("model-bars", "model", "model-bars", "모델에 영향을 준 주요 항목",
      "영향이 큰 항목을 최대 세 개 보여줘요. 항목별 영향 비중은 ‘계산 근거’에서 볼 수 있어요.", "model-heading", fallback));
    if (model.hasPriceMood) steps.push(readingStep("model-price-mood", "model", "model-price-mood", "가격 흐름 분위기",
      "최근 주가 움직임의 강도를 가늠할 때 참고해요. 수익률과 흔들림, 평균 거래 가격 대비 위치를 반영해요.", "model-heading", fallback));
    if (steps.length) return steps;
    return [readingStep("model-reason", "model", "model-heading", "모델이 본 근거",
      model.hasReason ? "여기에 나온 이유를 읽고, 관련된 거래나 뉴스가 있는지도 살펴봐요." : fallback, "model-heading", fallback)];
  },
  trading: ({ trading }) => {
    const fallback = "지금은 투자자별 거래 자료가 없어요. 최근 주가나 뉴스는 다른 탭에서 볼 수 있어요.";
    const heading = readingStep("trading-total", "trading", trading ? "trading-total" : "trading-heading",
      "투자자별 순매수", trading ? "같은 기간의 순매수를 나란히 보면, 매수나 매도가 한쪽에 몰렸는지 알 수 있어요." : fallback,
      "trading-heading", fallback);
    if (!trading || trading.days === 1) return [heading];
    return [heading, readingStep("trading-latest", "trading", "trading-latest", "마지막 날의 거래",
      "기간 합계와 방향이 다르다면, 최근 하루는 전체 흐름과 다르게 움직인 거예요.", "trading-heading", fallback)];
  },
  news: ({ news }) => {
    const fallback = "뉴스가 모이면 이곳에서 기사 분위기의 흐름을 볼 수 있어요.";
    const summary = "분위기가 달라졌다면 기사 수도 함께 봐요. 기사가 적으면 한 건의 영향이 커요.";
    const heading = readingStep("news-summary", "news", news.hasSummary ? "news-summary" : "news-heading",
      "뉴스 분위기와 기사 수", news.hasSummary ? summary : fallback, "news-heading", fallback);
    if (!news.hasTimeline) return [heading];
    return [
      readingStep("news-chart", "news", "news-chart", "뉴스 분위기 그래프",
        "점이 위로 갈수록 기사 표현이 긍정적이었어요. 기사가 적은 구간은 한 건의 영향이 커요.", "news-heading", fallback),
      readingStep("news-periods", "news", "news-periods", "기간별 뉴스 분위기",
        "며칠 사이 변화는 일별로, 더 긴 흐름은 월별이나 연별로 살펴봐요.", "news-heading", fallback),
    ];
  },
  company: ({ company }) => {
    const fallback = "지금은 재무 지표를 확인하기 어려워요. 회사가 공개한 자료는 최근 공시에서 찾아볼 수 있어요.";
    const steps: ReadingStep[] = [];
    if (company.hasRepresentative) steps.push(readingStep("company-metric", "company", "company-metric", "재무 지표 읽는 법",
      "지표 이름 옆 ⓘ에서 뜻을 확인할 수 있어요. 화면의 코스피 중간값은 여러 업종을 포함한 기준이에요.", "company-heading", fallback));
    for (const group of company.groups) {
      const { title, text } = FINANCIAL_GUIDANCE[group];
      steps.push(readingStep(group, "company", group, title, text, "company-heading", fallback));
    }
    return steps.length ? steps : [readingStep("company-metric", "company", "company-heading", "재무 지표",
      fallback, "company-heading", fallback)];
  },
};

export function readingSteps(tabs: readonly ReadingTab[], facts: ReadingFacts): ReadingStep[] {
  const orderText = facts.readerType
    ? `‘${facts.readerType.label}’의 읽는 순서예요. ${ORDER_REASONS[facts.readerType.type]}`
    : "주가로 최근 흐름을 살펴본 뒤, 모델 신호를 거래와 뉴스, 회사 상태에 비춰 볼 수 있어요. 성향에 따라 순서가 달라져요.";
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
