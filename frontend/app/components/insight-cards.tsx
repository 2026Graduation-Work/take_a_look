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
  FEW_ARTICLES,
  TERM_INFO,
  compareLine,
  psychologyReason,
  checkpointReason,
  typeRule,
  AXIS_STAGE_RULE,
  PSYCHOLOGY_NOTE,
  STYLE_TYPE_SOURCE,
  STYLE_TYPE_BASIS,
  TERM,
  CONTEXTUAL_LIVE_NEWS_CODES,
  LIVE_NEWS_SCOPE,
  PRICE_CONTEXT_CAPTION,
  DISCLOSURE_KIND,
  SIGNAL_WORD,
} from "@/lib/copy-glossary";
import { STYLE_AXIS_IDS } from "@/lib/profiling-rules";
import {
  BIT_LABEL,
  BIT_TYPES,
  classifyBit,
  presetStyleAxes,
  type BitType,
  type CardId,
} from "@/lib/profiling/bit";
import { checkpointItems, selectNudges } from "@/lib/profiling/nudges";
import { PSYCHOLOGY_SCALE, STYLE_AXIS_SCALE } from "@/lib/profiling/axis-scale";
import StageBar from "./stage-bar";
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
import ChangeText from "./change-text";
import { changeMeta, contributionWord, formatShares, kstDay, signedPercent } from "@/lib/display";
import type { ChartSnapshot } from "@/lib/chart-public";
import type { DataProvenance, PredictionReason, StockDetail, StyleAxes } from "@/lib/types";
import { SourceTable } from "./source-line";
import MoreList from "./more-list";
import DotLegend from "./dot-legend";
import { staleLabel } from "@/lib/market-status";
import TermLabel from "./term-tip";
import FINANCIAL_MEDIANS from "@/lib/financial-medians.json";

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
    why: "짧은 기간 가격은 분위기에 크게 흔들려서, 내 판단이 분위기에 휩쓸린 건 아닌지 볼 수 있어요.",
  },
  supply: {
    label: TERM.supply,
    question: "최근 누가 이 종목을 사고팔았나요?",
    why: "누가 사고팔았는지를 하루 거래량과 견줘 보면 움직임이 큰지 작은지 알 수 있어요.",
  },
  financial: {
    label: TERM.financial,
    question: "이 회사는 돈을 잘 벌고 있나요?",
    why: "가격과 별개로 회사의 기초 체력을 코스피 다른 회사들과 견줘 볼 수 있어요.",
  },
  contribution: {
    label: TERM.contribution,
    question: "모델은 무엇을 보고 이 신호를 냈나요?",
    why: "신호가 한 가지 근거에 쏠렸는지 보고, 그 근거가 내 판단과 맞는지 견줘 볼 수 있어요.",
  },
};

const SUPPLY_SERIES = [
  { key: "retail", label: "개인" },
  { key: "foreign", label: "외국인" },
  { key: "institution", label: "기관" },
] as const;

const TOOLTIP_STYLE = { border: `1px solid ${CHART.line}`, borderRadius: 8, fontSize: 12 };

const signed = (value: number, digits = 2) => `${value > 0 ? "+" : ""}${value.toFixed(digits)}`;
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
  const bitFor = (type: BitType | null) => {
    const axes = original && type ? presetStyleAxes(original, type) : original;
    return axes ? classifyBit(axes) : null;
  };
  return {
    styleAxes,
    bit: bitFor(viewAs),
    viewAs,
    setViewAs,
    bitFor,
  };
}

// 판단 근거 탭 순서(유형별 카드 순서 → 탭). 탭과 "다른 유형이라면?" 안내가 같이 쓴다.
function evidenceTabOrder(bit: ReturnType<typeof classifyBit> | null): TabId[] {
  const order = bit?.cardOrder ?? DEFAULT_CARD_ORDER;
  return [...new Set(order.map((id) => CARD_TO_TAB[id]).filter((id): id is TabId => Boolean(id)))];
}

function Why({ children }: { children: ReactNode }) {
  return (
    <p className="m-0 text-xs text-muted">
      <span>왜 봐야 하나요? </span>
      {children}
    </p>
  );
}

function Unavailable({ children }: { children: ReactNode }) {
  return <p className="m-0 text-sm text-muted">{children}</p>;
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
  // 유형을 바꿔도 화면이 같아 보이면 바뀐 건지 헷갈린다(사전 참가자 P0 10/13) → 근거 순서가 바뀌었는지 한 줄로
  const [orderNote, setOrderNote] = useState("");
  const market = toNudgeMarket(detail, insights, holdings);
  const nudges = bit && market ? selectNudges(bit, market) : [];
  const items = checkpointItems(nudges, extra);

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
            {BIT_LABEL[demo.viewAs]}의 시선으로 보는 중이에요. 내 결과가 아니에요.
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
              <p className="m-0 max-w-2xl text-base text-ink">{item.text}</p>
            </li>
          ))}
        </ol>
      )}

      {demo.styleAxes && (
        <details className="disclosure">
          <summary>다른 유형이라면?</summary>
          <p className="mb-3 mt-2 text-xs text-muted">
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
                  onClick={() => {
                    if (active) return;
                    const changed = evidenceTabOrder(bit).join() !== evidenceTabOrder(demo.bitFor(type)).join();
                    setOrderNote(changed ? "근거 순서가 바뀌었어요." : "이 종목은 유형과 관계없이 같은 순서예요.");
                    demo.setViewAs(type);
                  }}
                  className={`min-h-11 rounded-sm px-4 text-xs font-medium ${
                    active ? "bg-brand-soft text-brand" : "bg-track text-body hover:bg-line"
                  }`}
                >
                  {type ? BIT_LABEL[type] : "내 성향"}
                </button>
              );
            })}
          </div>
          <p aria-live="polite" className="m-0 mt-2 min-h-4 text-xs text-muted">{orderNote}</p>
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
  const tabs = evidenceTabOrder(demo.bit);
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
      <div className="flex flex-col gap-1 px-1">
        <h2 id="evidence-title" className="text-xl font-semibold">
          무엇을 근거로 판단할까요?
        </h2>
        <span className="text-2xs text-muted">판단 근거 4가지, 내 성향에 맞춘 순서</span>
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
        {/* 네 탭 모두 같은 순서: 결론 → 숫자와 비교 기준 → 왜 봐야 하나요? → 계산 근거(접기) */}
        {active === "market" && <MarketPanel detail={detail} insights={insights} why={TAB_META.market.why} />}
        {active === "supply" && <SupplyPanel supply={insights.supply} volume={insights.supplyVolume} why={TAB_META.supply.why} />}
        {active === "financial" && (
          <FinancialPanel financial={insights.financial} why={TAB_META.financial.why} />
        )}
        {active === "contribution" && (
          <ContributionPanel
            space={contributionSpace}
            total={contributionTotal}
            features={modelFeatures}
            reasons={detail.reasons.filter(reason => reason.source === "chart")}
            why={TAB_META.contribution.why}
          />
        )}
      </div>
    </section>
  );
}

function Conclusion({ children }: { children: ReactNode }) {
  return <p className="m-0 text-base text-ink">{children}</p>;
}

export function NewsSentimentPanel({ insights, code }: { insights: StockInsights; code: string }) {
  return <MarketPanel detail={null} insights={insights} code={code} />;
}

function MarketPanel({ detail, insights, code = detail?.code, why }: { detail: StockDetail | null; insights: StockInsights; code?: string; why?: string }) {
  const { sentiment, psychology } = insights;
  const [selectedSentimentPeriod, setSelectedSentimentPeriod] = useState<SentimentPeriod>("day");
  const sentimentTimelineRef = useRef<HTMLDivElement | null>(null);
  const sentimentTabRefs = useRef<Record<SentimentPeriod, HTMLButtonElement | null>>({
    day: null,
    month: null,
    year: null,
  });
  const sentimentView = marketSentimentView(insights);
  const contextualLive = sentimentView?.basis === "live" && Boolean(code && CONTEXTUAL_LIVE_NEWS_CODES.has(code));
  const todayLive = todayLiveSentimentView(insights);
  const chartLive = selectedSentimentPeriod === "day" ? todayLive : null;
  const risk = detail ? riskSnapshot(detail) : null;
  const prices = detail ? pricePeriod(detail) : null;
  const sentimentDates = sentiment ? sentimentPeriod(sentiment) : null;
  const periodMismatch = Boolean(prices && sentimentDates && !periodsOverlap(prices, sentimentDates));
  const sentimentTabs: SentimentPeriod[] = ["day", "month", "year"];
  // 일별에서 오늘은 '오늘 Live' 점(직전 24시간)이 맡는다.
  const periodInput = sentimentDaysIncludingLive(insights)
    .filter(({ date }) => !chartLive || date !== kstDay(Date.parse(chartLive.asOf)));
  const periodDays = aggregateSentimentPeriods(periodInput, selectedSentimentPeriod);
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
          {sentimentView.basis === "live" ? "최근 24시간" : "과거"} {contextualLive ? TERM.relatedNewsSentiment : TERM.sentiment}는{" "}
          <strong className="font-semibold" style={{ color: moodColor(sentimentView.score) }}>{moodWord(sentimentView.score)}</strong>이에요.
        </Conclusion>
      ) : risk ? (
        <Conclusion>
          최근 1년 {TERM_INFO.volatility.label}은 코스피 전 종목 중 상위 {Math.max(1, Math.round((1 - risk.volatilityPercentile) * 100))}% 수준이에요.
          {risk.asOf && staleLabel(risk.asOf) && <span className="text-xs text-muted tabular-nums"> ({risk.asOf.replaceAll("-", ".")} 기준)</span>}
        </Conclusion>
      ) : !psychology ? (
        <Unavailable>이 종목은 아직 뉴스를 모으지 않아요. 보유 종목이나 관심 종목에 넣으면 평일 오전 수집 대상에 들어가요.</Unavailable>
      ) : null}
      {contextualLive && <p className="m-0 text-xs text-muted">{LIVE_NEWS_SCOPE}</p>}
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
          <p className="m-0 flex flex-wrap items-center gap-x-3 text-2xs text-muted tabular-nums">
            <DotLegend items={[["var(--color-up)", "긍정"], ["var(--color-muted)", "중립"], ["var(--color-down)", "부정"]]} />
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
                월 평균과 연 평균은 과거 뉴스와 오늘 Live 기사를 기사 수에 따라 함께 반영해요.
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
        <>
          <p className="m-0 text-xs font-semibold text-muted">{PRICE_CONTEXT_CAPTION}</p>
          <dl className="m-0 grid grid-cols-1 gap-3 sm:grid-cols-3">
            <Stat
              label={<TermLabel term="volatility" />}
              value={`${(risk.volatilityAnnual * 100).toFixed(1)}%`}
              compare={`1년 기준, 코스피 상위 ${Math.max(1, Math.round((1 - risk.volatilityPercentile) * 100))}%예요.`}
            />
            <Stat label="3개월 최고가 대비" value={signedPercent(risk.drawdownFrom3mHigh)} change={risk.drawdownFrom3mHigh * 100} />
            <Stat label="최근 3거래일" value={signedPercent(risk.return3d)} change={risk.return3d * 100} />
          </dl>
          {risk.asOf && staleLabel(risk.asOf) && <p className="m-0 text-2xs text-muted tabular-nums">{risk.asOf.replaceAll("-", ".")} 종가 기준</p>}
        </>
      )}
      {sentimentView?.headlines.length ? (
        <section aria-labelledby="headline-title" className="flex flex-col gap-2">
          <h4 id="headline-title" className="m-0 text-sm font-medium text-ink">대표 기사</h4>
          <MoreList items={sentimentView.headlines} label="대표 기사" render={(headline) => (
              <li key={`${headline.date}:${headline.title}`} className="text-sm text-ink">
                {headline.url ? (
                  <a className="text-brand hover:underline" href={headline.url} target="_blank" rel="noreferrer">
                    {headline.title}
                  </a>
                ) : headline.title}
                {/* 근거·출처 항상 표시(AGENTS.md HITL) — 날짜는 빼도 언론사는 남긴다 */}
                <span className="ml-2 text-2xs text-muted">{headline.press}</span>
              </li>
          )} />
        </section>
      ) : null}
      <DisclosureList disclosures={insights.disclosures} />
      {why && <Why>{why}</Why>}
      {risk && (
        <details className="disclosure">
          <summary>계산 근거</summary>
          <ul className="m-0 mt-3 flex list-none flex-col gap-2 p-0 text-xs font-normal text-muted">
            <li>{TERM_INFO.volatility.label} = 최근 250거래일 하루 수익률(로그)의 표준편차 × √252, 코스피 전 종목 중 순위</li>
            <li>3개월 최고가 대비 = 지금 종가 ÷ 최근 60거래일 최고 종가 − 1</li>
            <li>최근 3거래일 = 지금 종가 ÷ 3거래일 전 종가 − 1</li>
          </ul>
        </details>
      )}
    </>
  );
}

// DART 공시 목록. 뉴스와 같은 '더 보기' 방식, 분류는 이름만으로 이해되게(copy-glossary DISCLOSURE_KIND).
function DisclosureList({ disclosures }: { disclosures: StockInsights["disclosures"] }) {
  return (
    <section aria-labelledby="disclosure-title" className="flex flex-col gap-2">
      <h4 id="disclosure-title" className="m-0 text-sm font-medium text-ink">최근 공시</h4>
      {disclosures.length ? (
        <MoreList items={disclosures} label="최근 공시" render={(item) => (
          <li key={item.rceptNo} className="flex flex-col">
            <a
              href={`https://dart.fss.or.kr/dsaf001/main.do?rcpNo=${item.rceptNo}`}
              target="_blank"
              rel="noreferrer"
              className="flex min-h-11 items-center text-sm text-ink hover:underline"
            >
              {item.title}
            </a>
            <span className="text-2xs text-muted tabular-nums">
              {item.filedOn.replaceAll("-", ".")}<span className="ml-3">{(DISCLOSURE_KIND[item.kind] ?? DISCLOSURE_KIND.other).label}</span>
            </span>
          </li>
        )} />
      ) : (
        <p className="m-0 text-sm text-muted">최근 90일 안에 올라온 공시가 없어요.</p>
      )}
    </section>
  );
}

function Stat({ label, value, change, compare }: { label: ReactNode; value: string; change?: number; compare?: string }) {
  return (
    <div className="flex flex-col gap-1">
      <dt className="text-2xs text-muted">{label}</dt>
      <dd className="m-0 text-sm font-semibold tabular-nums text-ink">{change === undefined ? value : <ChangeText value={change} precision={1}>{value}</ChangeText>}</dd>
      {compare && <dd className="m-0 text-2xs text-muted tabular-nums">{compare}</dd>}
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
  // 점을 누르면 그 날 값, 바깥을 누르거나 Esc로 닫는다(올리기만으로는 열지 않음)
  const [tip, setTip] = useState(false);
  const chartRoot = useRef<HTMLDivElement | null>(null);
  useEffect(() => {
    if (!tip) return;
    const outside = (event: PointerEvent) => !chartRoot.current?.contains(event.target as Node) && setTip(false);
    const escape = (event: globalThis.KeyboardEvent) => event.key === "Escape" && setTip(false);
    document.addEventListener("pointerdown", outside);
    document.addEventListener("keydown", escape);
    return () => {
      document.removeEventListener("pointerdown", outside);
      document.removeEventListener("keydown", escape);
    };
  }, [tip]);
  return (
    <div ref={chartRoot} className="h-[204px] min-w-0">
      <ResponsiveContainer width="100%" height="100%" minWidth={1} minHeight={1} initialDimension={{ width: 860, height: 180 }}>
        <LineChart
          onClick={() => setTip(true)}
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
            trigger="click"
            active={tip ? undefined : false}
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
            // 기사 적은 날은 속 빈 점으로 구분(풀이는 툴팁)
            dot={({ cx, cy, payload }) =>
              payload.articleCount < FEW_ARTICLES && typeof payload.score === "number" ? (
                <circle data-sentiment-few="true" cx={cx} cy={cy} r={3} fill="var(--color-surface)" stroke={CHART.priceLine} strokeWidth={1.5} />
              ) : <g />
            }
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
function SupplyPanel({ supply, volume, why }: { supply: SupplyDemandDay[] | null; volume: number | null; why: string }) {
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
        {buyer.total > 0 && seller.total < 0 ? <>
          최근 20영업일 동안 <strong className="font-semibold text-up">{buyer.label}</strong>이 가장 많이 샀고,{" "}
          {seller.label}이 가장 많이 팔았어요.
        </> : buyer.total > 0 ? <>
          최근 20영업일 동안 {buyer.label}의 순매수 수량이 가장 많았어요.
        </> : seller.total < 0 ? <>
          최근 20영업일 동안 {seller.label}의 순매도 수량이 가장 많았어요.
        </> : "최근 20영업일 동안 투자자별 순매수 수량의 합계가 모두 0이에요."}
      </Conclusion>
      <ul className="m-0 flex list-none flex-col gap-4 p-0">
        {totals.map(({ key, label, total, latest }) => {
          const buy = total > 0;
          const { color } = changeMeta(total);
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
                <ChangeText value={total}>{formatShares(total)}</ChangeText>
                {volume ? (
                  <span className="block whitespace-nowrap text-2xs font-normal text-muted">
                    하루 평균 거래량의 {Math.round((Math.abs(total) / volume) * 100).toLocaleString("ko-KR")}%
                  </span>
                ) : null}
                <span className="block whitespace-nowrap text-2xs font-normal text-muted">
                  마지막 날 <ChangeText value={latest}>{formatShares(latest)}</ChangeText>
                </span>
              </span>
            </li>
          );
        })}
      </ul>
      <div className="text-2xs text-muted">
        <TermLabel term="net_buy" /> 수량(주), {supply[0].date.replaceAll("-", ".")} ~ {supply[supply.length - 1].date.replaceAll("-", ".")}
      </div>
      <Why>{why}</Why>
      <details className="disclosure">
        <summary>계산 근거</summary>
        <ul className="m-0 mt-3 flex list-none flex-col gap-2 p-0 text-xs font-normal text-muted">
          <li>순매수 합계 = 최근 {supply.length}영업일 동안 투자자별로 산 주식 수 − 판 주식 수, 기타법인 제외</li>
          <li>{volume
            ? `하루 평균 거래량 대비 = |순매수 합계| ÷ 같은 기간 하루 평균 거래량(${formatShares(Math.round(volume)).replace(/^\+/, "")})`
            : "같은 기간 거래량 기록이 없어 거래량 대비 비율은 빼고 보여 줘요."}</li>
        </ul>
      </details>
    </>
  );
}

// '시점'이에요 / '폭'이에요 / '비율'이에요 / '추세'예요. 끝이 한글이 아니면 '예요'.
function copula(word: string): string {
  const code = word.charCodeAt(word.length - 1) - 0xac00;
  return code >= 0 && code < 11172 && code % 28 ? "이에요" : "예요";
}

const oneDecimal = (value: number) => value.toLocaleString("ko-KR", { maximumFractionDigits: 1 });

// 비교 기준: DB에 업종 분류가 없어 코스피 중간값(backend value_pipeline/kospi_medians.py가 미리 계산한 JSON).
// 업종 분류가 생기면 같은 업종 10개사 이상일 때 업종 중간값으로 바꾼다(#372).
const MEDIANS: Partial<Record<string, { median: number; count: number }>> = FINANCIAL_MEDIANS.metrics;

function FinancialPanel({ financial, why }: { financial: FinancialSnapshot | null; why: string }) {
  if (!financial) return <Unavailable>이 종목은 아직 재무를 모으지 않아요. 로그인한 계정의 보유 종목이나 관심 종목에 넣으면 매주 월요일 오전에 최신 정기보고서로 채워요.</Unavailable>;
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
      <dl className="m-0 grid grid-cols-1 gap-x-6 gap-y-4 sm:grid-cols-2">
        {financial.metrics.map((metric) => {
          const median = MEDIANS[metric.key]?.median;
          return (
            <div key={metric.key} className="grid grid-cols-[minmax(0,1fr)_auto] items-baseline gap-x-3 gap-y-1">
              <dt className="text-sm text-body">{metric.key in TERM_INFO ? <TermLabel term={metric.key as keyof typeof TERM_INFO} /> : metric.label}</dt>
              <dd className="m-0 text-right text-sm font-semibold tabular-nums text-ink">
                {metric.value === null ? "확인 불가" : <>{oneDecimal(metric.value)}{metric.unit}</>}
              </dd>
              <dd className="col-span-2 m-0 text-2xs text-muted tabular-nums">
                {metric.value === null
                  ? metric.note === "negative_earnings" ? "적자라 계산하지 않아요." : "계산할 자료가 모자라요."
                  : median !== undefined && compareLine(metric.value, median, FINANCIAL_MEDIANS.basis, metric.unit)}
              </dd>
            </div>
          );
        })}
      </dl>
      <Why>{why}</Why>
      <details className="disclosure">
        <summary>계산 근거</summary>
        <ul className="m-0 mt-3 flex list-none flex-col gap-2 p-0 text-xs font-normal text-muted">
          {financial.metrics.map((metric) => (
            <li key={metric.key}>
              <span>{metric.label}</span> = {metric.basis}
            </li>
          ))}
        </ul>
        <p className="m-0 mt-3 text-2xs text-muted">
          재무 {financial.period}{financial.valuationPriceAsOf && `, PER/PBR 주가 ${financial.valuationPriceAsOf.replaceAll("-", ".")} 종가 기준`}
        </p>
        <p className="m-0 mt-2 text-2xs text-muted tabular-nums">
          비교 기준은 {FINANCIAL_MEDIANS.basis} {FINANCIAL_MEDIANS.companies}개사의 {FINANCIAL_MEDIANS.fiscal_year}년 사업보고서로 계산한 중간값이에요({FINANCIAL_MEDIANS.as_of.replaceAll("-", ".")} 시가총액 기준). 업종 분류가 없어 업종 대신 코스피 전체와 견줘요.
        </p>
      </details>
    </>
  );
}

// 부호 막대: 선택한 분류 점수의 강화는 오른쪽, 완화는 왼쪽. 방향과 부호는 별개다.
function ContributionPanel({
  space,
  features,
  total,
  reasons,
  why,
}: {
  features?: ChartSnapshot["inference"]["features"];
  space?: ChartSnapshot["inference"]["contribution_space"];
  total?: number;
  reasons: PredictionReason[];
  why: string;
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
              <span className="flex flex-col gap-1">
                <span className="text-sm text-ink">{reason.title}</span>
                <span className="text-xs text-muted">
                  {reason.detail}, {reason.sourceLabel}
                </span>
              </span>
            </li>
          ))}
        </ol>
        <Why>{why}</Why>
      </>
    );
  }
  const target = SIGNAL_WORD[space === "class_0_raw_margin" ? "down" : space === "class_1_raw_margin" ? "flat" : "up"];
  const top = features[0];
  // 쉽게 보이기: 상위 3개만 막대로, 나머지는 "그 밖의 N개" 한 줄. 크기는 말로(contributionWord), 숫자는 계산값 보기에만
  const shown = features.slice(0, 3);
  const hiddenCount = features.length - shown.length;
  const max = Math.max(...shown.map(f => Math.abs(f.contribution))) || 1;
  return (
    <>
      <Conclusion>
        모델의{" "}
        <strong className="font-semibold" style={{ color: target === SIGNAL_WORD.down ? "var(--color-down)" : target === SIGNAL_WORD.up ? "var(--color-up)" : "var(--color-ink)" }}>
          {target}
        </strong>{" "}
        점수에 가장 크게 영향을 준 항목은 &lsquo;{top.label_ko}&rsquo;{copula(top.label_ko)}.
      </Conclusion>
      <ul className="m-0 flex list-none flex-col gap-4 p-0">
        {shown.map((feature) => {
          const up = feature.contribution > 0;
          const color = !up || target === SIGNAL_WORD.flat ? "var(--color-muted)" : target === SIGNAL_WORD.down ? "var(--color-down)" : "var(--color-up)";
          return (
            <li key={feature.name} className="flex flex-col gap-2" data-model-feature={feature.name}>
              <div className="flex items-baseline gap-2">
                <span className="text-sm font-medium text-ink">{feature.label_ko}</span>
                <span className="ml-auto flex-none text-xs text-body">{contributionWord(feature.contribution, target, total)}</span>
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
              <span className="text-xs text-muted">{feature.meaning_ko}, 관측값 {feature.value === null ? "미제공" : feature.value.toLocaleString("ko-KR", { maximumFractionDigits: 4 })}</span>
            </li>
          );
        })}
      </ul>
      {hiddenCount > 0 && (
        <p className="m-0 text-xs text-muted">그 밖의 {hiddenCount}개 항목은 영향이 더 작아 줄였어요. 계산 근거에서 모두 볼 수 있어요.</p>
      )}
      <p className="m-0 text-2xs text-muted">{total === undefined && "전체 항목 기준값이 없어 크기 말은 빼고 방향만 보여요. "}{target} 점수를 높이고 낮춘 정도예요. 예측 확률이나 수익률이 아니에요.</p>
      <Why>{why}</Why>
      <details className="disclosure">
        <summary>계산 근거</summary>
        <div className="flex flex-col gap-2">
        <dl className="m-0 grid grid-cols-[minmax(0,1fr)_auto] gap-x-3 gap-y-2 text-sm">
          {features.map(feature => (
            <div key={feature.name} className="contents">
              <dt>{feature.label_ko}</dt>
              <dd className="m-0 tabular-nums">{signed(feature.contribution, 4)}</dd>
            </div>
          ))}
        </dl>
        <p className="m-0 text-2xs text-muted">계산값은 {target} 점수를 올리고(+) 내린(−) 정도예요. 결과의 몇 분의 몇이라는 뜻이 아니에요. 계산값의 절댓값이 전체 항목 절댓값 합{total !== undefined && `(이번 ${total.toFixed(4)})`}의 10분의 1 이상이면 &lsquo;크게&rsquo;, 그보다 작으면 &lsquo;조금&rsquo;이라고 써요. 모델 기준값은 제외해요. 막대 길이는 막대로 보인 항목 중 가장 큰 값을 기준으로 비교해요.</p>
        </div>
      </details>
    </>
  );
}

// ── 더 알아보기: 내 투자 유형, 가격 흐름 분위기, 계산 근거 ─────────────────
// 설문 축과 가격 흐름은 5칸 단계 막대(stage-bar.tsx)로 보이고, 점수 숫자는 '계산 근거' 묶음에만 범위와 함께 쓴다.

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
  const tabs = bit ? evidenceTabOrder(bit) : null;
  return (
    <>
      <section aria-labelledby="more-type" className="flex flex-col gap-6">
        <h3 id="more-type" className="m-0 text-lg font-semibold">내 투자 유형</h3>
        {!bit || !styleAxes || !tabs ? (
          <p className="m-0 text-sm text-muted">성향 진단 결과가 없어 기본 순서로 보여 줘요.</p>
        ) : (
          <>
            <div className="grid items-start gap-6 md:grid-cols-2 md:gap-x-12">
              <div className="flex min-w-0 flex-col gap-2 rounded-md bg-track p-5" aria-label="내 투자 유형">
                <p className="m-0 text-base font-semibold text-ink">{BIT_LABEL[bit.type]}</p>
                <TypeZones current={BIT_TYPES.indexOf(bit.type)} />
                <p className="m-0 text-2xs text-body">{STYLE_TYPE_BASIS} {BIT_LABEL[bit.type]}에 가까워요.</p>
                {bit.lowConfidence && <p className="m-0 text-2xs text-muted">답이 서로 엇갈려 유형을 참고로만 봐 주세요.</p>}
                <p className="m-0 text-2xs text-muted">{STYLE_TYPE_SOURCE}</p>
              </div>
              <div className="flex min-w-0 flex-col gap-4 md:py-5">
                <h4 className="m-0 text-base font-semibold">내 성향에 맞춘 읽는 순서</h4>
                <ol aria-label="내 성향에 맞춘 읽는 순서" className="m-0 flex list-none flex-col gap-2 p-0 text-sm text-body">
                  {tabs.map((id, index) => (
                    <li key={id} className="flex items-baseline gap-3">
                      <span className="tabular-nums text-muted">{index + 1}</span>
                      <span>{TAB_META[id].label}</span>
                    </li>
                  ))}
                </ol>
              </div>
            </div>
            <section aria-label="설문 8가지 답" className="flex flex-col gap-4">
              <h4 className="m-0 text-base font-semibold">설문 8가지 답</h4>
              <div className="grid gap-6 md:grid-cols-2 md:gap-x-12">
                {[STYLE_AXIS_IDS.slice(0, 4), STYLE_AXIS_IDS.slice(4)].map((axes, column) => (
                  <div key={column} className="flex min-w-0 flex-col gap-6">
                    {axes.map((axisId) => (
                      <StageBar key={axisId} axis={STYLE_AXIS_SCALE[axisId]}
                        value={styleAxes.axes.find(({ axis_id }) => axis_id === axisId)?.ratio ?? 0} />
                    ))}
                  </div>
                ))}
              </div>
            </section>
            {market && nudges.length > 0 && (
              <section aria-label="확인할 것이 뜬 이유" className="flex flex-col gap-4">
                <h4 className="m-0 text-base font-semibold">확인할 것이 뜬 이유</h4>
                <div className="grid gap-6 md:grid-cols-2 md:gap-x-12">
                  {nudges.map((nudge) => (
                    <div key={nudge.id} className="flex flex-col gap-2">
                      <StageBar axis={STYLE_AXIS_SCALE[nudge.axis]} value={nudge.ratio} />
                      <p className="m-0 text-2xs text-muted">{checkpointReason(nudge, market)}</p>
                    </div>
                  ))}
                </div>
              </section>
            )}
          </>
        )}
      </section>
      {insights.psychology && (
        <section aria-labelledby="more-mood" className="flex flex-col gap-4">
          <h3 id="more-mood" className="m-0 text-lg font-semibold">{PSYCHOLOGY_SCALE.name}</h3>
          <div className="md:w-1/2 md:pr-6">
            <StageBar axis={PSYCHOLOGY_SCALE} value={insights.psychology.axis} title="최근 가격 흐름" />
          </div>
          <p className="m-0 text-2xs text-muted">{PSYCHOLOGY_NOTE}</p>
        </section>
      )}
    </>
  );
}

// 더 알아보기의 '계산 근거' 묶음: 단계 막대 뒤의 점수와 나눈 기준을 범위와 함께 쓴다.
export function BasisNumbers({ demo, insights }: { demo: DemoStyleAxes; insights: StockInsights }) {
  const rows = [
    demo.bit && typeRule(demo.bit.composite),
    demo.styleAxes && AXIS_STAGE_RULE,
    insights.psychology && psychologyReason(insights.psychology.axis),
  ].filter((row): row is string => Boolean(row));
  if (rows.length === 0) return null;
  return (
    <section aria-labelledby="more-basis" className="flex flex-col gap-4">
      <h3 id="more-basis" className="m-0 text-lg font-semibold">계산 근거</h3>
      <ul className="m-0 flex list-none flex-col gap-2 p-0 text-sm text-body tabular-nums">
        {rows.map((row) => <li key={row}>{row}</li>)}
      </ul>
    </section>
  );
}

// 유형 네 구간 중 내 구간만 진하게. 점수 숫자는 계산 근거에만 둔다.
function TypeZones({ current }: { current: number }) {
  return (
    <div role="img" aria-label={`네 유형 중 ${BIT_LABEL[BIT_TYPES[current]]}`} className="flex flex-col gap-2">
      <div aria-hidden="true" className="grid grid-cols-4 gap-1">
        {BIT_TYPES.map((type, index) => <span key={type} className={`h-2 rounded-sm ${index === current ? "bg-brand" : "bg-surface"}`} />)}
      </div>
      <div aria-hidden="true" className="grid grid-cols-4 gap-1 text-center text-2xs">
        {BIT_TYPES.map((type, index) => <span key={type} className={index === current ? "font-semibold text-ink" : "text-muted"}>{BIT_LABEL[type]}</span>)}
      </div>
    </div>
  );
}

// 데이터 출처 전체 — 섹션마다 한 줄로 둔 출처를 한곳에 모은다.
export function SourceList({ detail, insights }: { detail: StockDetail; insights: StockInsights }) {
  // 데이터가 없어 빈 상태로 보이는 항목은 "예시 데이터"가 아니라 "미제공"이다.
  const { provenance: p } = insights;
  const shown = (data: unknown, provenance: DataProvenance) => (data ? provenance : null);
  const rows: [string, DataProvenance | null][] = [
    ["주가", detail.priceProvenance ?? detail.provenance],
    ["모델 신호와 근거", detail.provenance],
    [TERM.sentiment, shown(insights.sentiment, p.sentiment)],
    ["최근 24시간 뉴스", shown(insights.liveSentiment, p.liveSentiment)],
    [TERM.supply, shown(insights.supply, p.supply)],
    [TERM.financial, shown(insights.financial, p.financial && insights.financial?.filing
      ? { ...p.financial, source: `${p.financial.source}, ${insights.financial.filing}` } : p.financial)],
    ["최근 공시", insights.disclosures.length
      ? { kind: "real", source: "DART 전자공시(제목과 날짜만 저장, 유형은 제목 규칙으로 분류)", asOf: insights.disclosures[0].filedOn }
      : null],
    [TERM.contribution, p.contributions],
    ...(insights.psychology
      ? ([["가격 흐름으로 본 분위기", insights.psychology.provenance]] as [string, DataProvenance][])
      : []),
    [
      "확인할 것",
      combinedProvenance(
        detail.provenance,
        ...[shown(insights.supply, p.supply), shown(insights.sentiment, p.sentiment)].filter((item) => item !== null),
      ),
    ],
  ];
  return (
    <SourceTable rows={rows}>
      {detail.priceProvenance?.source.includes("수정주가") && (
        <p className="col-span-2 m-0 mt-1 text-xs text-muted">
          주가는 수정주가예요. 그 뒤에 있었던 배당과 주식 나눔을 반영해 과거 가격을 다시 계산한 값이라, 그날 실제로 거래된
          가격과 조금 다를 수 있어요. 가격 흐름과 등락률을 비교하기에는 이 방식이 정확해요.
        </p>
      )}
    </SourceTable>
  );
}
