"use client";

// 종목 상세의 성향 기반 영역: 나에게 맞춘 체크포인트 · 판단 근거 4탭 · 계산 근거.
// 성향은 소프트 틸트다. 탭 순서와 체크포인트에만 쓰고 종목을 거르지 않는다.
// 연구 질문 ② "성향 기반 표시"는 탭 순서(data-card-order)로 보존한다.

import { useEffect, useRef, useState, type KeyboardEvent, type ReactNode } from "react";
import {
  Line,
  LineChart,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import {
  BIAS_MODE_WORD,
  CHECKPOINT_RULE,
  FEW_ARTICLES,
  FEW_ARTICLES_RULE,
  FINANCIAL_TERM,
  PSYCHOLOGY_RULE,
  STYLE_TYPE_RULE,
  STYLE_TYPE_SOURCE,
  TERM,
  DISCLOSURE_KIND,
} from "@/lib/copy-glossary";
import { STYLE_AXIS_IDS } from "@/lib/profiling-rules";
import {
  BIT_LABEL,
  BIT_TYPES,
  classifyBit,
  presetStyleAxes,
  type BitResult,
  type BitType,
  type CardId,
} from "@/lib/profiling/bit";
import { SCREEN_GUIDE_NOTICE, selectNudges } from "@/lib/profiling/nudges";
import {
  combinedProvenance,
  aggregateSentimentPeriods,
  sentimentDaysIncludingLive,
  marketSentimentView,
  todayLiveSentimentView,
  periodsOverlap,
  pricePeriod,
  riskSnapshot,
  sentimentPeriod,
  toNudgeMarket,
  type FinancialSnapshot,
  type HoldingWeight,
  type SentimentDay,
  type SentimentPeriod,
  type StockInsights,
  type SupplyDemandDay,
} from "@/lib/providers";
import { CHART } from "@/lib/chart-colors";
import { formatKstDateTime } from "@/lib/display";
import type { ChartSnapshot } from "@/lib/chart-public";
import type { DataProvenance, PredictionReason, StockDetail, StyleAxes, StyleAxisId } from "@/lib/types";
import SourceChip from "./source-chip";

// 극성은 lib/profiling/style-questions.json axes와 같다.
const AXIS_META: Record<StyleAxisId, { name: string; negative: string; positive: string }> = {
  market_participation: { name: "시장과 내 목표", negative: "시장 수익률 참여", positive: "내 목표 우선" },
  loss_tolerance: { name: "손실 감내", negative: "원금 보전", positive: "수익 기회" },
  turnover: { name: "보유 기간", negative: "장기 보유", positive: "단기 매매" },
  concentration: { name: "집중과 분산", negative: "폭넓은 분산", positive: "소수 집중" },
  rule_adherence: { name: "계획 운용", negative: "사전 규칙 준수", positive: "상황별 재량" },
  information_reliance: { name: "판단의 근거", negative: "본인 판단", positive: "시장·타인 추종" },
  urgency: { name: "기회를 대하는 태도", negative: "여유", positive: "조급함" },
  drawdown_reaction: { name: "하락에 대한 반응", negative: "하락 시 유지", positive: "하락 시 이탈" },
};

// 8축 진단 결과가 없을 때의 순서
const DEFAULT_CARD_ORDER: readonly CardId[] = [
  "nudge",
  "contribution",
  "supply",
  "sentiment",
  "risk",
  "financial",
];

type TabId = "market" | "supply" | "financial" | "contribution";

// 유형별 카드 순서(bit.ts CARD_ORDER) → 판단 근거 탭. 넛지는 체크포인트로, 변동성은 시장 분위기 탭으로 간다.
const CARD_TO_TAB: Partial<Record<CardId, TabId>> = {
  sentiment: "market",
  risk: "market",
  supply: "supply",
  financial: "financial",
  contribution: "contribution",
};

const TAB_META: Record<TabId, { label: string; question: string; why: string }> = {
  market: {
    label: TERM.market,
    question: "요즘 이 종목을 둘러싼 분위기는 어떤가요?",
    why: "뉴스 분위기와 가격 흔들림은 짧은 기간 가격을 크게 움직이곤 해요. 분위기에 휩쓸린 판단인지 한 번 더 보게 해 줘요.",
  },
  supply: {
    label: TERM.supply,
    question: "최근 누가 이 종목을 사고팔았나요?",
    why: "개인·외국인·기관이 실제로 거래한 기록이에요. 누가 어느 쪽으로 움직였는지는 알 수 있지만 이유는 담겨 있지 않아요.",
  },
  financial: {
    label: TERM.financial,
    question: "이 회사는 돈을 잘 벌고 있나요?",
    why: "가격 움직임과 별개로 회사의 기초 체력을 보는 지표예요. 오래 들고 갈 종목이라면 특히 중요해요.",
  },
  contribution: {
    label: TERM.contribution,
    question: "모델은 무엇을 보고 이 신호를 냈나요?",
    why: "모델 신호가 한 가지 근거에 쏠려 있는지 확인할 수 있어요. 그 근거가 내 판단과 맞는지 비교해 보세요.",
  },
};

const SUPPLY_SERIES = [
  { key: "retail", label: "개인" },
  { key: "foreign", label: "외국인" },
  { key: "institution", label: "기관" },
] as const;

const TOOLTIP_STYLE = { border: `1px solid ${CHART.line}`, borderRadius: 8, fontSize: 12 };

const signed = (value: number, digits = 2) => `${value > 0 ? "+" : ""}${value.toFixed(digits)}`;
const signedPercent = (ratio: number) => `${ratio > 0 ? "+" : ""}${(ratio * 100).toFixed(1)}%`;
// 순매수 수량(주). 만 주 단위로 줄여 읽기 쉽게: +5,276,406 → +527.6만 주
const shares = (value: number) =>
  `${value > 0 ? "+" : value < 0 ? "-" : ""}${(Math.abs(value) / 10_000).toLocaleString("ko-KR", { maximumFractionDigits: 1 })}만 주`;
const sentimentDateLabel = (date: string) => date.replaceAll("-", ".");
const SENTIMENT_DAY_LIMIT = 365;
const SENTIMENT_POINT_PX = 28; // 점 하나의 가로 폭. 날짜 글자는 겹치지 않게 Recharts가 건너뛴다
// 감성 점수(-1~+1) → 구간 말. 경계는 점수 분포가 아니라 읽기 쉬운 고정 구간이다.
// 강조 1단(판정 단어): 굵게 + 의미 색. 긍정 = 적, 부정 = 청, 그 사이 = 본문색(DESIGN.md 2-1).
function moodColor(score: number): string {
  return score >= 0.1 ? "var(--color-up)" : score <= -0.1 ? "var(--color-down)" : "var(--color-ink)";
}

function moodWord(score: number): string {
  if (score >= 0.3) return "긍정적인 편";
  if (score >= 0.1) return "조금 긍정적";
  if (score > -0.1) return "중립에 가까운 편";
  if (score > -0.3) return "조금 부정적";
  return "부정적인 편";
}

export type DemoStyleAxes = ReturnType<typeof useDemoStyleAxes>;

// "다른 유형이라면?": BIT 4유형 프리셋으로 이 화면만 바꿔 본다. DB·localStorage에 쓰지 않는다.
export function useDemoStyleAxes(original: StyleAxes | null) {
  const [viewAs, setViewAs] = useState<BitType | null>(null);
  const styleAxes: StyleAxes | null =
    original && viewAs ? presetStyleAxes(original, viewAs) : original;
  return {
    styleAxes,
    bit: styleAxes ? classifyBit(styleAxes) : null,
    viewAs,
    setViewAs,
  };
}

function Why({ children }: { children: ReactNode }) {
  return (
    <p className="m-0 max-w-2xl text-xs text-muted">
      <span className="font-medium text-body">왜 봐야 하나요? </span>
      {children}
    </p>
  );
}

function Unavailable({ children }: { children: ReactNode }) {
  return <p className="m-0 rounded-md bg-field px-4 py-5 text-center text-sm text-muted">{children}</p>;
}

// ── 나에게 맞춘 체크포인트 ───────────────────────────────────

export function Checkpoints({
  demo,
  detail,
  insights,
  holdings,
  extra,
}: {
  demo: DemoStyleAxes;
  detail: StockDetail;
  insights: StockInsights;
  holdings: HoldingWeight[];
  extra: string | null; // 성향 대비 위험도 안내(넛지 외). 있으면 체크포인트 뒤에 붙는다
}) {
  const { bit } = demo;
  const market = toNudgeMarket(detail, insights, holdings);
  const nudges = bit && market ? selectNudges(bit, market) : [];
  const items = [
    ...nudges.map(({ id, text }) => ({ key: id, text })),
    ...(extra ? [{ key: "risk", text: extra }] : []),
  ].slice(0, 2);

  return (
    <section aria-labelledby="checkpoint-title" className="surface flex flex-col gap-4 p-6">
      <div className="flex flex-col gap-1">
        <h2
          id="checkpoint-title"
          data-bit-type={bit ? (bit.lowConfidence ? "low_confidence" : bit.type) : undefined}
          className="text-xl font-semibold"
        >
          {!bit
            ? "성향을 진단하면 나에게 맞춘 확인 거리가 보여요"
            : bit.lowConfidence
              ? "아직 성향을 판단하기엔 응답이 부족해요"
              : `${BIT_LABEL[bit.type]}이라면 이것부터 확인해 보세요`}
        </h2>
        {demo.viewAs && (
          <p className="m-0 flex items-center gap-2 text-xs text-body">
            <span className="size-1.5 rounded-full bg-caution-mark" aria-hidden />
            {BIT_LABEL[demo.viewAs]}의 시선으로 보는 중이에요 · 내 결과가 아니에요
          </p>
        )}
      </div>

      {bit && !market && items.length === 0 ? (
        <p className="m-0 text-sm text-muted">이 종목은 확인 거리를 고르는 데 필요한 데이터가 아직 없어요.</p>
      ) : bit && items.length === 0 ? (
        <p className="m-0 text-sm text-muted">지금 이 종목에서 따로 확인할 점은 없어요.</p>
      ) : (
        <ol className="m-0 flex list-none flex-col gap-3 p-0">
          {items.map((item, index) => (
            <li key={item.key} data-nudge={item.key} className="flex gap-3">
              <span className="flex-none text-sm text-muted tabular-nums">{index + 1}</span>
              <p className="m-0 max-w-2xl text-base leading-relaxed text-ink">{item.text}</p>
            </li>
          ))}
        </ol>
      )}

      {demo.styleAxes && (
        <details className="disclosure border-t border-line-soft pt-3">
          <summary>다른 유형이라면?</summary>
          <p className="mb-2.5 mt-2 text-xs text-muted">
            다른 유형은 같은 종목을 어떤 순서와 확인 거리로 보는지 바꿔 볼 수 있어요. 이 화면에서만 바뀌어요.
          </p>
          <div role="group" aria-label="다른 유형이라면?" className="flex flex-wrap gap-2">
            {[null, ...BIT_TYPES].map((type) => {
              const active = demo.viewAs === type;
              return (
                <button
                  key={type ?? "mine"}
                  type="button"
                  aria-pressed={active}
                  onClick={() => demo.setViewAs(type)}
                  className={`min-h-11 rounded-sm px-3.5 text-xs font-medium ${
                    active ? "bg-brand-soft text-brand" : "bg-track text-body hover:bg-line"
                  }`}
                >
                  {type ? BIT_LABEL[type] : "내 성향"}
                </button>
              );
            })}
          </div>
        </details>
      )}
    </section>
  );
}

// ── 판단 근거 4탭 ────────────────────────────────────────────

export default function EvidenceTabs({
  detail,
  insights,
  demo,
  modelFeatures,
  contributionTotal,
  contributionSpace,
}: {
  detail: StockDetail;
  insights: StockInsights;
  demo: DemoStyleAxes;
  modelFeatures?: ChartSnapshot["inference"]["features"];
  contributionTotal?: number;
  contributionSpace?: ChartSnapshot["inference"]["contribution_space"];
}) {
  const order = demo.bit?.cardOrder ?? DEFAULT_CARD_ORDER;
  const tabs = [...new Set(order.map((id) => CARD_TO_TAB[id]).filter((id): id is TabId => Boolean(id)))];
  const [selected, setSelected] = useState<TabId | null>(null);
  const active = selected ?? tabs[0];
  const tabRefs = useRef<Record<string, HTMLButtonElement | null>>({});

  function onKeyDown(event: KeyboardEvent<HTMLDivElement>) {
    const step = event.key === "ArrowRight" ? 1 : event.key === "ArrowLeft" ? -1 : 0;
    if (!step) return;
    event.preventDefault();
    const next = tabs[(tabs.indexOf(active) + step + tabs.length) % tabs.length];
    setSelected(next);
    tabRefs.current[next]?.focus();
  }

  return (
    <section aria-labelledby="evidence-title" className="flex flex-col gap-4">
      <div className="flex flex-col gap-0.5 px-1">
        <span className="eyebrow">판단 근거 4가지 · 내 성향에 맞춘 순서</span>
        <h2 id="evidence-title" className="text-xl font-semibold">
          무엇을 근거로 판단할까요?
        </h2>
      </div>
      <div className="overflow-x-auto [scrollbar-width:none]">
        <div
          role="tablist"
          aria-label="판단 근거"
          data-card-order={order.join(",")}
          onKeyDown={onKeyDown}
          className="segmented"
        >
          {tabs.map((id) => (
            <button
              key={id}
              ref={(node) => {
                tabRefs.current[id] = node;
              }}
              type="button"
              role="tab"
              id={`tab-${id}`}
              aria-selected={active === id}
              aria-controls={`panel-${id}`}
              tabIndex={active === id ? 0 : -1}
              onClick={() => setSelected(id)}
            >
              {TAB_META[id].label}
            </button>
          ))}
        </div>
      </div>
      <div
        role="tabpanel"
        id={`panel-${active}`}
        aria-labelledby={`tab-${active}`}
        data-card={active}
        className="surface flex flex-col gap-4 p-6"
      >
        <h3 className="text-lg font-semibold">{TAB_META[active].question}</h3>
        {active === "market" && <MarketPanel detail={detail} insights={insights} />}
        {active === "supply" && <SupplyPanel supply={insights.supply} provenance={insights.provenance.supply} />}
        {active === "financial" && (
          <FinancialPanel financial={insights.financial} provenance={insights.provenance.financial} />
        )}
        {active === "contribution" && (
          <ContributionPanel
            space={contributionSpace}
            total={contributionTotal}
            features={modelFeatures}
            reasons={detail.reasons.filter(reason => reason.source === "chart")}
            provenance={detail.provenance}
          />
        )}
        <Why>{TAB_META[active].why}</Why>
      </div>
    </section>
  );
}

function Conclusion({ children }: { children: ReactNode }) {
  return <p className="m-0 text-base text-ink">{children}</p>;
}

export function NewsSentimentPanel({ insights }: { insights: StockInsights }) {
  return <MarketPanel detail={null} insights={insights} />;
}

function MarketPanel({ detail, insights }: { detail: StockDetail | null; insights: StockInsights }) {
  const { sentiment, psychology } = insights;
  const [selectedSentimentPeriod, setSelectedSentimentPeriod] = useState<SentimentPeriod>("day");
  const sentimentTimelineRef = useRef<HTMLDivElement | null>(null);
  const sentimentTabRefs = useRef<Record<SentimentPeriod, HTMLButtonElement | null>>({
    day: null,
    month: null,
    year: null,
  });
  const sentimentView = marketSentimentView(insights);
  const todayLive = todayLiveSentimentView(insights);
  const chartLive = selectedSentimentPeriod === "day" ? todayLive : null;
  const risk = detail ? riskSnapshot(detail) : null;
  const prices = detail ? pricePeriod(detail) : null;
  const sentimentDates = sentiment ? sentimentPeriod(sentiment) : null;
  const periodMismatch = Boolean(prices && sentimentDates && !periodsOverlap(prices, sentimentDates));
  const sentimentTabs: SentimentPeriod[] = ["day", "month", "year"];
  const periodInput = selectedSentimentPeriod === "day"
    ? sentiment?.days ?? [] : sentimentDaysIncludingLive(insights);
  const periodDays = aggregateSentimentPeriods(periodInput, selectedSentimentPeriod);
  const chartDates = periodInput.length ? {start: periodInput[0].date, end: periodInput.at(-1)!.date} : null;
  const includesLive = selectedSentimentPeriod !== "day" && Boolean(todayLive) && Boolean(insights.liveSentiment?.periodDays?.length);
  // 일별은 최근 1년만 한 줄 스크롤로 그린다. 더 긴 기간은 월별·연별에서 본다.
  // ponytail: 점 하나당 SENTIMENT_POINT_PX 폭이라 일별 전체(10년, 약 3,700점)는 너무 넓다. 필요하면 가상 스크롤로.
  const chartDays = selectedSentimentPeriod === "day" ? periodDays.slice(-SENTIMENT_DAY_LIMIT) : periodDays;
  const chartPoints = chartDays.length + (chartLive ? 1 : 0);

  useEffect(() => {
    // 처음 위치는 오른쪽 끝(가장 최근)
    const timeline = sentimentTimelineRef.current;
    if (timeline) timeline.scrollLeft = timeline.scrollWidth;
  }, [selectedSentimentPeriod, chartPoints]);

  function onSentimentTabKeyDown(event: KeyboardEvent<HTMLDivElement>) {
    const step = event.key === "ArrowRight" ? 1 : event.key === "ArrowLeft" ? -1 : 0;
    if (!step) return;
    event.preventDefault();
    const next = sentimentTabs[
      (sentimentTabs.indexOf(selectedSentimentPeriod) + step + sentimentTabs.length) % sentimentTabs.length
    ];
    setSelectedSentimentPeriod(next);
    sentimentTabRefs.current[next]?.focus();
  }

  return (
    <>
      {sentimentView ? (
        <Conclusion>
          {sentimentView.basis === "live" ? "최근 24시간" : "과거"} {TERM.sentiment}는{" "}
          <strong className="font-semibold" style={{ color: moodColor(sentimentView.score) }}>{moodWord(sentimentView.score)}</strong>이에요.
        </Conclusion>
      ) : risk ? (
        <Conclusion>
          최근 3개월 {TERM.volatility}은 시장 전체에서 상위 {Math.max(1, Math.round((1 - risk.volatilityPercentile) * 100))}% 수준이에요.
        </Conclusion>
      ) : !psychology ? (
        <Unavailable>이 종목은 아직 뉴스를 모으지 않아요. 보유·관심 종목에 넣으면 평일 오전 수집 대상에 들어가요.</Unavailable>
      ) : null}
      {sentimentView?.basis === "live" && (
        <p className="m-0 text-xs text-muted tabular-nums">
          기준시각 {formatKstDateTime(sentimentView.asOf)} · 직전 24시간 · 관련 기사{" "}
          {sentimentView.articleCount}건 · 언론사 {sentimentView.publisherCount}곳 · NewsAPI.ai · KR-FinBERT
        </p>
      )}
      {sentimentView?.status === "partial" && (
        <p data-coverage-notice className="m-0 text-xs text-body">
          수집 범위 일부 · 공급자 결과가 100건을 넘어 확인된 기사 범위로 계산했어요.
        </p>
      )}
      {psychology && (
        <p className="m-0 text-sm text-body">
          가격 흐름으로 본 분위기: {psychology.word}
          <span className="text-muted"> — {psychology.explain}</span>
        </p>
      )}
      {(sentiment?.days.length || Boolean(todayLive)) ? (
        <>
          <div
            className="segmented self-start"
            role="tablist"
            aria-label="뉴스 분위기 기간"
            onKeyDown={onSentimentTabKeyDown}
          >
            {sentimentTabs.map((period) => {
              const label: Record<SentimentPeriod, string> = { day: "일별", month: "월별", year: "연별" };
              return (
                <button
                  key={period}
                  ref={(node) => {
                    sentimentTabRefs.current[period] = node;
                  }}
                  role="tab"
                  id={`sentiment-tab-${period}`}
                  aria-selected={selectedSentimentPeriod === period}
                  aria-controls="sentiment-panel"
                  tabIndex={selectedSentimentPeriod === period ? 0 : -1}
                  onClick={() => setSelectedSentimentPeriod(period)}
                >
                  {label[period]}
                </button>
              );
            })}
          </div>
          <p className="m-0 text-2xs text-muted tabular-nums">
            -1 부정 ~ +1 긍정 · {selectedSentimentPeriod === "day" ? "일별 관련 기사 평균" : `${selectedSentimentPeriod === "month" ? "월별" : "연별"} 뉴스 감성 · 기사 수 가중평균`}
            {chartDates && ` · ${sentimentDateLabel(chartDates.start)} ~ ${sentimentDateLabel(chartDates.end)}`}
            {sentiment && ` · ${insights.provenance.sentiment.source}`}
            {includesLive && " + NewsAPI.ai · 오늘 Live 반영"}
          </p>
          <div
            role="tabpanel"
            id="sentiment-panel"
            aria-labelledby={`sentiment-tab-${selectedSentimentPeriod}`}
          >
            {/* 그래프 전체가 하나의 가로 스크롤. 스와이프하면 선과 날짜가 함께 움직이고, 누르면 그 날 값이 보인다. */}
            <div
              ref={sentimentTimelineRef}
              className="overflow-x-auto pb-2 [scrollbar-width:thin]"
              aria-label="감성 시점 탐색"
              tabIndex={0}
            >
              <div style={{ width: `max(100%, ${chartPoints * SENTIMENT_POINT_PX}px)` }}>
                <SentimentChart
                  days={chartDays}
                  connectLive={selectedSentimentPeriod === "day"}
                  live={chartLive}
                />
              </div>
            </div>
            {selectedSentimentPeriod !== "day" && (
              <p className="mt-2 mb-0 text-2xs text-muted">
                월·연 평균은 과거 뉴스와 오늘 Live 기사를 기사 수에 따라 함께 반영합니다.
              </p>
            )}
          </div>
        </>
      ) : null}
      {periodMismatch && (
        <p data-period-mismatch className="m-0 flex items-center gap-2 text-xs text-body">
          <span className="size-1.5 rounded-full bg-caution-mark" aria-hidden />
          뉴스 기간({sentimentDates!.start} ~ {sentimentDates!.end})이 주가 기간과 달라요.
        </p>
      )}
      {risk && (
        <dl className="m-0 grid grid-cols-1 gap-3 sm:grid-cols-3">
          <Stat label={`${TERM.volatility}(1년 기준)`} value={`${(risk.volatilityAnnual * 100).toFixed(1)}%`} />
          <Stat label="3개월 최고가 대비" value={signedPercent(risk.drawdownFrom3mHigh)} />
          <Stat label="최근 3거래일" value={signedPercent(risk.return3d)} />
        </dl>
      )}
      {sentimentView?.headlines.length ? (
        <details className="disclosure text-sm">
          <summary>
            대표 기사 <span className="count">{sentimentView.headlines.length}건</span>
          </summary>
          <ul className="m-0 mt-2 flex list-none flex-col gap-1.5 p-0">
            {sentimentView.headlines.map((headline) => (
              <li key={`${headline.date}:${headline.title}`} className="text-sm text-ink">
                {headline.url ? (
                  <a className="text-brand hover:underline" href={headline.url} target="_blank" rel="noreferrer">
                    {headline.title}
                  </a>
                ) : headline.title}
                {/* 근거·출처 항상 표시(AGENTS.md HITL) — 날짜는 빼도 언론사는 남긴다 */}
                <span className="ml-2 text-xs text-muted">{headline.press}</span>
              </li>
            ))}
          </ul>
        </details>
      ) : null}
      <DisclosureList disclosures={insights.disclosures} />
    </>
  );
}

// DART 공시 목록. 유형마다 쉬운 풀이를 펼쳐 볼 수 있다(copy-glossary DISCLOSURE_KIND).
function DisclosureList({ disclosures }: { disclosures: StockInsights["disclosures"] }) {
  return (
    <section aria-labelledby="disclosure-title" className="flex flex-col gap-2">
      <h4 id="disclosure-title" className="m-0 text-sm font-medium text-ink">최근 공시</h4>
      {disclosures.length ? (
        <ul className="m-0 flex list-none flex-col p-0">
          {disclosures.map((item) => {
            const kind = DISCLOSURE_KIND[item.kind] ?? DISCLOSURE_KIND.other;
            return (
              <li key={item.rceptNo} className="border-b border-line-soft py-1 last:border-b-0">
                <a
                  href={`https://dart.fss.or.kr/dsaf001/main.do?rcpNo=${item.rceptNo}`}
                  target="_blank"
                  rel="noreferrer"
                  className="flex min-h-11 items-center text-sm text-ink hover:underline"
                >
                  {item.title}
                </a>
                <details className="text-xs text-muted">
                  <summary className="flex min-h-11 cursor-pointer list-none items-center gap-1 tabular-nums">
                    {item.filedOn.replaceAll("-", ".")} · {kind.label} <span aria-hidden>ⓘ</span>
                  </summary>
                  <p className="m-0 pb-2 text-body">{kind.explain}</p>
                </details>
              </li>
            );
          })}
        </ul>
      ) : (
        <p className="m-0 text-sm text-muted">최근 90일 안에 올라온 공시가 없어요.</p>
      )}
    </section>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex flex-col gap-0.5 rounded-md bg-field px-4 py-3">
      <dt className="text-xs text-muted">{label}</dt>
      <dd className="m-0 text-lg font-semibold tabular-nums">{value}</dd>
    </div>
  );
}

function SentimentChart({ days, live, connectLive, dateLabel = sentimentDateLabel }: {
  days: SentimentDay[];
  live: ReturnType<typeof marketSentimentView>;
  connectLive: boolean;
  dateLabel?: (date: string) => string;
}) {
  const data = [
    ...days.map((day) => ({ ...day, label: dateLabel(day.date), liveScore: null as number | null })),
    ...(live ? [{ date: live.asOf, label: "오늘 Live", score: connectLive ? live.score : null, liveScore: live.score, articleCount: live.articleCount }] : []),
  ];
  return (
    <div className="h-[204px] min-w-0">
      <ResponsiveContainer width="100%" height="100%" minWidth={1} minHeight={1} initialDimension={{ width: 860, height: 180 }}>
        <LineChart
          data={data}
          margin={{ top: 8, right: 8, left: 0, bottom: 0 }}
        >
          <XAxis
            dataKey="label"
            tick={{ fill: CHART.muted, fontSize: 12 }}
            axisLine={false}
            tickLine={false}
            height={24}
            interval="preserveStartEnd"
            minTickGap={24}
          />
          <YAxis
            domain={[-1, 1]}
            ticks={[-1, 0, 1]}
            tickFormatter={(value) => (value > 0 ? "긍정" : value < 0 ? "부정" : "0")}
            tick={{ fill: CHART.muted, fontSize: 12 }}
            axisLine={false}
            tickLine={false}
            width={36}
            orientation="right"
          />
          <ReferenceLine y={0} stroke={CHART.line} />
          <Tooltip
            contentStyle={TOOLTIP_STYLE}
            formatter={(value, _name, item) => {
              const count = (item.payload as SentimentDay).articleCount;
              return count < FEW_ARTICLES ? (
                <>
                  {signed(Number(value))}
                  <br />
                  기사 {count}건이라 참고만
                </>
              ) : (
                signed(Number(value))
              );
            }}
          />
          <Line
            dataKey="score"
            name={TERM.sentiment}
            stroke={CHART.priceLine}
            strokeWidth={2}
            dot={false}
            activeDot={false}
            isAnimationActive={false}
          />
          {live && (
            <Line
              dataKey="liveScore"
              name="오늘 Live"
              tooltipType={connectLive ? "none" : undefined}
              stroke="transparent"
              dot={({ cx, cy, payload }) =>
                typeof payload.liveScore === "number" ? (
                  <circle data-sentiment-live="today" cx={cx} cy={cy} r={5} fill={CHART.priceLine} stroke={CHART.priceLine} strokeWidth={2} />
                ) : <g />
              }
              activeDot={false}
              isAnimationActive={false}
            />
          )}
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}

// 투자자별 20일 순매수 합계를 가운데 0 기준 막대로. 순매수 = 적, 순매도 = 청.
function SupplyPanel({ supply, provenance }: { supply: SupplyDemandDay[] | null; provenance: DataProvenance }) {
  if (!supply?.length) return <Unavailable>이 종목은 사고판 기록이 아직 없어요. 코스피 종목은 평일 저녁 수집 뒤 보여요.</Unavailable>;
  const totals = SUPPLY_SERIES.map((series) => ({
    ...series,
    total: supply.reduce((sum, day) => sum + day[series.key], 0),
    latest: supply[supply.length - 1][series.key],
  }));
  const max = Math.max(...totals.map(({ total }) => Math.abs(total)), 1);
  const buyer = totals.reduce((top, item) => (item.total > top.total ? item : top));
  const seller = totals.reduce((low, item) => (item.total < low.total ? item : low));
  return (
    <>
      <Conclusion>
        최근 20영업일 동안 <strong className="font-semibold text-up">{buyer.label}</strong>이 가장 많이 샀고,{" "}
        {seller.label}이 가장 많이 팔았어요.
      </Conclusion>
      <ul className="m-0 flex list-none flex-col gap-3.5 p-0">
        {totals.map(({ key, label, total, latest }) => {
          const buy = total >= 0;
          const color = buy ? "var(--color-up)" : "var(--color-down)";
          return (
            <li key={key} className="grid grid-cols-[4rem_minmax(0,1fr)_auto] items-center gap-3">
              <span className="text-sm text-body">{label}</span>
              <div className="relative h-2 rounded-full bg-track" aria-hidden>
                <span className="absolute inset-y-[-4px] left-1/2 w-px bg-line" />
                <span
                  className="absolute inset-y-0 rounded-full"
                  style={{
                    [buy ? "left" : "right"]: "50%",
                    width: `${(Math.abs(total) / max) * 50}%`,
                    backgroundColor: color,
                  }}
                />
              </div>
              <span className="text-right text-sm font-semibold tabular-nums text-ink">
                {shares(total)}
                <span className="block whitespace-nowrap text-2xs font-normal text-muted">
                  {buy ? "순매수" : "순매도"} · 최근일 {shares(latest)}
                </span>
              </span>
            </li>
          );
        })}
      </ul>
      <p className="m-0 flex flex-wrap items-center gap-x-3 text-2xs text-muted">
        <span>
          {supply[0].date} ~ {supply[supply.length - 1].date} · 순매수 수량(주) · 기타법인 제외
        </span>
        <SourceChip provenance={provenance} />
      </p>
    </>
  );
}

const oneDecimal = (value: number) => value.toLocaleString("ko-KR", { maximumFractionDigits: 1 });

function FinancialPanel({ financial, provenance }: { financial: FinancialSnapshot | null; provenance: DataProvenance }) {
  if (!financial) return <Unavailable>이 종목은 아직 재무를 모으지 않아요. 보유·관심 종목에 넣으면 매주 월요일 오전에 최신 정기보고서로 채워요.</Unavailable>;
  const value = (key: string) => financial.metrics.find((metric) => metric.key === key)?.value;
  const roe = value("roe");
  const debt = value("debt_ratio");
  return (
    <>
      {roe != null && debt != null && (
        <Conclusion>
          자기 돈 대비 1년에 <strong className="font-semibold">{oneDecimal(Math.abs(roe))}%</strong>를 {roe < 0 ? "잃었고" : "벌었고"}, 빚은
          자기 돈의{" "}
          <strong className="font-semibold">{oneDecimal(debt)}%</strong> 수준이에요.
        </Conclusion>
      )}
      <dl className="m-0 grid grid-cols-1 gap-3 sm:grid-cols-2">
        {financial.metrics.map((metric) => (
          <div key={metric.key} className="flex items-baseline justify-between gap-3 rounded-md bg-field px-4 py-3">
            <dt className="text-sm text-body">{FINANCIAL_TERM[metric.key] ?? metric.label}</dt>
            <dd className="m-0 flex-none text-right text-base font-semibold tabular-nums">
              {metric.value === null ? (
                <>
                  확인 불가
                  {metric.note && <span className="block text-2xs font-normal text-muted">{metric.note}</span>}
                </>
              ) : (
                <>
                  {oneDecimal(metric.value)}
                  {metric.unit}
                </>
              )}
            </dd>
          </div>
        ))}
      </dl>
      <details className="disclosure">
        <summary>계산 근거</summary>
        <ul className="m-0 mt-3 flex list-none flex-col gap-2 p-0 text-xs text-body">
          {financial.metrics.map((metric) => (
            <li key={metric.key}>
              <span className="font-medium text-ink">{metric.label}</span> = {metric.basis}
            </li>
          ))}
        </ul>
      </details>
      <p className="m-0 flex flex-wrap items-center gap-x-3 text-2xs text-muted">
        <span>{financial.period}</span>
        <SourceChip provenance={provenance} />
      </p>
    </>
  );
}

// 부호 막대: 선택한 분류 점수의 강화는 오른쪽, 완화는 왼쪽. 방향과 부호는 별개다.
function ContributionPanel({
  space,
  features,
  total,
  reasons,
  provenance,
}: {
  features?: ChartSnapshot["inference"]["features"];
  space?: ChartSnapshot["inference"]["contribution_space"];
  total?: number;
  reasons: PredictionReason[];
  provenance: DataProvenance;
}) {
  if (!features?.length) {
    if (!reasons.length) return <Unavailable>이 예측에 연결된 근거 데이터가 없어요.</Unavailable>;
    return (
      <>
        <Conclusion>
          모델이 가장 크게 본 근거는 &lsquo;{reasons[0].title}&rsquo;예요.
        </Conclusion>
        <ol className="m-0 flex list-none flex-col gap-3 p-0">
          {reasons.map((reason, index) => (
            <li key={`${reason.title}:${index}`} className="flex gap-3">
              <span className="flex-none text-sm text-muted tabular-nums">{index + 1}</span>
              <span className="flex flex-col gap-0.5">
                <span className="text-sm text-ink">{reason.title}</span>
                <span className="text-xs text-muted">
                  {reason.detail} · {reason.sourceLabel}
                </span>
              </span>
            </li>
          ))}
        </ol>
        <SourceChip provenance={provenance} />
      </>
    );
  }
  const target = space === "class_0_raw_margin" ? "하방" : space === "class_1_raw_margin" ? "중립" : "상방";
  const max = Math.max(...features.map(f => Math.abs(f.contribution))) || 1;
  const top = features[0];
  const share = (value: number) => total === undefined ? null : total === 0 ? 0 : Math.abs(value) / total * 100;
  return (
    <>
      <Conclusion>
        LGBM의{" "}
        <strong className="font-semibold" style={{ color: target === "하방" ? "var(--color-down)" : target === "상방" ? "var(--color-up)" : "var(--color-ink)" }}>
          {target}
        </strong>{" "}
        점수에 가장 크게 영향을 준 항목은 &lsquo;{top.label_ko}&rsquo;예요.
      </Conclusion>
      <ul className="m-0 flex list-none flex-col gap-4 p-0">
        {features.map((feature) => {
          const up = feature.contribution > 0;
          const color = !up || target === "중립" ? "var(--color-muted)" : target === "하방" ? "var(--color-down)" : "var(--color-up)";
          return (
            <li key={feature.name} className="flex flex-col gap-1.5" data-model-feature={feature.name}>
              <div className="flex items-baseline gap-2">
                <span className="text-sm font-medium text-ink">{feature.label_ko}</span>
                <span className="text-xs text-muted">LGBM 피처</span>
                <span className="ml-auto flex-none text-xs text-muted tabular-nums">
                  {target} {feature.contribution === 0 ? "영향 없음" : up ? "강화" : "완화"} · 기여도 {share(feature.contribution) === null ? "미제공" : `${share(feature.contribution)!.toFixed(1)}%`}
                </span>
              </div>
              <div className="relative h-1.5 rounded-full bg-track" aria-hidden>
                <span className="absolute inset-y-[-3px] left-1/2 w-px bg-line" />
                <span
                  className="absolute inset-y-0 rounded-full"
                  style={{
                    [up ? "left" : "right"]: "50%",
                    width: `${(Math.abs(feature.contribution) / max) * 50}%`,
                    backgroundColor: color,
                  }}
                />
              </div>
              <span className="text-xs text-muted">{target} 점수를 {feature.contribution === 0 ? "바꾸지 않음" : up ? "높이는 방향" : "낮추는 방향"}</span>
              <span className="text-xs text-muted">{feature.meaning_ko} · 관측값 {feature.value === null ? "미제공" : feature.value.toLocaleString("ko-KR", { maximumFractionDigits: 4 })}</span>
            </li>
          );
        })}
      </ul>
      <details className="disclosure">
        <summary className="text-xs text-body">계산값 보기</summary>
        <dl className="mt-3 grid grid-cols-[minmax(0,1fr)_auto] gap-x-3 gap-y-2 text-xs">
          {features.map(feature => (
            <div key={feature.name} className="contents">
              <dt>{feature.label_ko}</dt>
              <dd className="m-0 tabular-nums">{signed(feature.contribution, 4)}</dd>
            </div>
          ))}
        </dl>
        <p className="text-xs text-muted">기여도 = {target} 점수에 대한 피처 기여값의 절댓값 ÷ 전체 피처 기여값의 절댓값 합 × 100. 모델 기준값은 제외해요.{total !== undefined && ` 이번 절댓값 합 ${total.toFixed(4)}.`} 막대 길이는 표시된 5개 중 가장 큰 기여를 기준으로 비교해요.</p>
      </details>
      <p className="m-0 flex flex-wrap items-center gap-x-3 text-2xs text-muted">
        <span>{total === undefined ? "전체 피처 기준값이 없어 %는 미제공해요." : "전체 피처 기준 기여도 · 상위 5개만 표시 · 5개 합은 100%가 아닐 수 있어요."} {target} 강화 = 점수를 높임 · 완화 = 낮춤 · 예측 확률·수익률 아님</span>
        <SourceChip provenance={provenance} />
      </p>
    </>
  );
}

// ── 계산 근거 (더 알아보기 안) ────────────────────────────────
// 한 줄에 무엇을 · 어떤 자료로 · 어떻게 계산했나 · 이번 값을 쉬운 말로 쓴다(copy-glossary.ts).

export function CalculationBasis({
  demo,
  detail,
  insights,
  holdings,
}: {
  demo: DemoStyleAxes;
  detail: StockDetail;
  insights: StockInsights;
  holdings: HoldingWeight[];
}) {
  const { bit, styleAxes } = demo;
  const market = toNudgeMarket(detail, insights, holdings);
  const nudges = bit && market ? selectNudges(bit, market) : [];
  if (!bit || !styleAxes) {
    return <p className="m-0 text-sm text-muted">성향 진단 결과가 없어 기본 순서로 보여 줘요.</p>;
  }
  const tabs = [...new Set(bit.cardOrder.map((id) => CARD_TO_TAB[id]).filter((id): id is TabId => Boolean(id)))];
  return (
    <div className="flex flex-col gap-3">
      <div className="grid gap-3 md:grid-cols-2">
        <BasisTile title="내 투자 유형" value={BIT_LABEL[bit.type]} sub={`${signed(bit.composite)} · 답끼리 맞는 정도 ${Math.round(bit.confidence * 100)}%`}
          rule={`${STYLE_TYPE_RULE} ${BIAS_MODE_WORD[bit.biasMode]}이에요.`}>
          <Scale value={bit.composite} zones={BIT_TYPES.map((type) => BIT_LABEL[type])} current={BIT_TYPES.indexOf(bit.type)} />
        </BasisTile>
        <div className="flex flex-col gap-3 rounded-md bg-field px-4 py-3">
          <span className="text-xs text-muted">설문 8가지 답 · 가운데가 0(어느 쪽도 아님)</span>
          {STYLE_AXIS_IDS.map((axisId) => (
            <Scale key={axisId} value={styleAxes.axes.find(({ axis_id }) => axis_id === axisId)?.ratio ?? 0}
              left={AXIS_META[axisId].negative} right={AXIS_META[axisId].positive} />
          ))}
        </div>
        {insights.psychology && (
          <BasisTile title="가격 흐름 분위기" value={insights.psychology.word} sub={signed(insights.psychology.axis)} rule={PSYCHOLOGY_RULE}>
            <Scale value={insights.psychology.axis} left="움츠러듦" right="들뜸" />
          </BasisTile>
        )}
        {nudges.map((nudge) => (
          <BasisTile key={nudge.id} title="체크포인트가 뜬 이유" value={`설문 '${AXIS_META[nudge.axis].name}'`} sub={signed(nudge.ratio)}>
            <Scale value={nudge.ratio} left={AXIS_META[nudge.axis].negative} right={AXIS_META[nudge.axis].positive} />
          </BasisTile>
        ))}
        <div className="flex flex-col gap-2 rounded-md bg-field px-4 py-3 md:col-span-2">
          <span className="text-xs text-muted">판단 근거 탭 순서 · {BIT_LABEL[bit.type]}이 먼저 보면 좋은 것부터</span>
          <ol className="m-0 flex list-none flex-wrap items-center gap-x-2 gap-y-1 p-0 text-sm text-ink">
            {tabs.map((id, index) => (
              <li key={id} className="flex items-center gap-2">
                {index > 0 && <span aria-hidden className="text-ghost">›</span>}
                <span className="tabular-nums text-muted">{index + 1}</span>
                <span className="font-medium">{TAB_META[id].label}</span>
              </li>
            ))}
          </ol>
        </div>
      </div>
      {insights.sentiment?.days.length ? <p className="m-0 text-xs text-muted">기사 수가 적은 날: {FEW_ARTICLES_RULE}</p> : null}
      {nudges.length > 0 && <p className="m-0 text-xs text-muted">체크포인트: {CHECKPOINT_RULE}</p>}
      <p className="m-0 text-xs text-muted">{STYLE_TYPE_SOURCE}</p>
    </div>
  );
}

// 계산 근거 한 칸: 결론(값) → -1~+1 위치 → 계산식 한 줄. 줄글 대신 위치로 먼저 읽힌다.
function BasisTile({ title, value, sub, rule, children }: { title: string; value: string; sub: string; rule?: string; children: ReactNode }) {
  return (
    <div className="flex flex-col gap-3 rounded-md bg-field px-4 py-3">
      <div className="flex flex-col gap-0.5">
        <span className="text-xs text-muted">{title}</span>
        <span className="text-base font-semibold text-ink">
          {value} <span className="text-sm font-normal tabular-nums text-muted">{sub}</span>
        </span>
      </div>
      {children}
      {rule && <p className="m-0 text-2xs text-muted">{rule}</p>}
    </div>
  );
}

// -1~+1 위치 막대. 색 없이 점 하나로 위치만 보인다(신호가 아니라 사실). zones가 있으면 같은 폭 구간으로 나눈다.
function Scale({ value, left, right, zones, current }: { value: number; left?: string; right?: string; zones?: string[]; current?: number }) {
  const position = `${((Math.max(-1, Math.min(1, value)) + 1) / 2) * 100}%`;
  return (
    <div role="img" aria-label={`-1부터 +1 사이에서 ${signed(value)} 위치`} className="flex flex-col gap-1.5">
      <div className="relative h-2 rounded-full bg-track">
        {!zones && <span className="absolute inset-y-0 left-1/2 w-0.5 bg-field" />}
        {zones?.slice(1).map((_, index) => (
          <span key={index} className="absolute inset-y-0 w-0.5 bg-field" style={{ left: `${((index + 1) / zones.length) * 100}%` }} />
        ))}
        <span className="absolute top-1/2 size-3.5 -translate-x-1/2 -translate-y-1/2 rounded-full border-2 border-field bg-ink" style={{ left: position }} />
      </div>
      {zones ? (
        <div className="grid text-center text-2xs" style={{ gridTemplateColumns: `repeat(${zones.length}, minmax(0, 1fr))` }}>
          {zones.map((zone, index) => (
            <span key={zone} className={index === current ? "font-semibold text-ink" : "text-muted"}>{zone}</span>
          ))}
        </div>
      ) : (
        <div className="flex justify-between text-2xs text-muted">
          <span>-1 {left}</span>
          <span>+1 {right}</span>
        </div>
      )}
    </div>
  );
}

// 데이터 출처 전체 — 섹션마다 한 줄로 둔 출처를 한곳에 모은다.
export function SourceList({ detail, insights }: { detail: StockDetail; insights: StockInsights }) {
  const rows: [string, DataProvenance][] = [
    ["주가", detail.priceProvenance ?? detail.provenance],
    ["모델 신호·범위·근거", detail.provenance],
    [TERM.sentiment, insights.provenance.sentiment],
    ["최근 24시간 뉴스", insights.provenance.liveSentiment],
    [TERM.supply, insights.provenance.supply],
    [TERM.financial, insights.provenance.financial],
    [TERM.contribution, insights.provenance.contributions],
    ...(insights.psychology
      ? ([["가격 흐름으로 본 분위기", insights.psychology.provenance]] as [string, DataProvenance][])
      : []),
    ["체크포인트", combinedProvenance(detail.provenance, insights.provenance.supply, insights.provenance.sentiment)],
  ];
  return (
    <dl className="m-0 grid grid-cols-[auto_minmax(0,1fr)] gap-x-4 gap-y-1.5 text-sm">
      {rows.map(([label, provenance]) => (
        <div key={label} className="contents">
          <dt className="text-body">{label}</dt>
          <dd className="m-0 min-w-0 [overflow-wrap:anywhere] [&>span]:max-w-full [&>span]:whitespace-normal">
            <SourceChip provenance={provenance} />
          </dd>
        </div>
      ))}
      {detail.priceProvenance?.source.includes("수정주가") && (
        <p className="col-span-2 m-0 mt-1 text-xs text-muted">
          주가는 수정주가예요. 그 뒤에 있었던 배당·주식 나눔을 반영해 과거 가격을 다시 계산한 값이라, 그날 실제로 거래된
          가격과 조금 다를 수 있어요. 가격 흐름과 등락률을 비교하기에는 이 방식이 정확해요.
        </p>
      )}
    </dl>
  );
}

export function ScreenGuideBanner({ bit }: { bit: BitResult | null }) {
  if (!bit || !SCREEN_GUIDE_NOTICE.appliesTo.includes(bit.type)) return null;
  return (
    <aside role="note" className="px-1 text-xs text-muted">
      {SCREEN_GUIDE_NOTICE.text}
    </aside>
  );
}
