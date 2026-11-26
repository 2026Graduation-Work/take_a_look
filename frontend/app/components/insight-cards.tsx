"use client";

import { featureDescription } from "@/lib/featureLabels";
import MarketDetail from "./market-detail";

import { useEffect, useRef, useState, type KeyboardEvent, type ReactNode } from "react";
import {
  Line,
  LineChart,
  ReferenceArea,
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
  PSYCHOLOGY_NOTE,
  TERM,
  CONTEXTUAL_LIVE_NEWS_CODES,
  LIVE_NEWS_SCOPE,
  DISCLOSURE_KIND,
  SIGNAL_WORD,
} from "@/lib/copy-glossary";
import type { classifyBit } from "@/lib/profiling/bit";
import { checkpointItems, selectNudges } from "@/lib/profiling/nudges";
import { PSYCHOLOGY_SCALE } from "@/lib/profiling/axis-scale";
import StageBar from "./stage-bar";
import {
  aggregateSentimentPeriods,
  combinedProvenance,
  sentimentDaysIncludingLive,
  marketSentimentView,
  type MarketSentimentView,
  todayLiveSentimentView,
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
import { changeMeta, contributionPercent, contributionWord, formatShares, kstDay } from "@/lib/display";
import type { ChartSnapshot } from "@/lib/chart-public";
import type { DataProvenance, PredictionReason, StockDetail } from "@/lib/types";
import { SourceTable } from "./source-line";
import MoreList from "./more-list";
import DotLegend from "./dot-legend";
import TermLabel from "./term-tip";
import FINANCIAL_MEDIANS from "@/lib/financial-medians.json";

const SUPPLY_SERIES = [
  { key: "retail", label: "개인" },
  { key: "foreign", label: "외국인" },
  { key: "institution", label: "기관" },
] as const;

const TOOLTIP_STYLE = { border: `1px solid ${CHART.line}`, borderRadius: 8, fontSize: 12 };

const signed = (value: number, digits = 2) => `${value > 0 ? "+" : ""}${value.toFixed(digits)}`;
const sentimentDateLabel = (date: string) => date.replaceAll("-", ".");
const SENTIMENT_DAY_LIMIT = 365;
const SENTIMENT_POINT_PX = 28; // 날짜 글자는 겹치지 않게 Recharts가 건너뛴다
// 경계는 점수 분포가 아니라 읽기 쉬운 고정 구간이다.
function moodColor(score: number): string {
  return score >= 0.1 ? "var(--color-up)" : score <= -0.1 ? "var(--color-down)" : "var(--color-ink)";
}

const moodChartColor = (score: number) => (score >= 0.1 ? CHART.up : score <= -0.1 ? CHART.down : CHART.muted);

export function moodWord(score: number): string {
  if (score >= 0.3) return "긍정적인 편";
  if (score >= 0.1) return "조금 긍정적";
  if (score > -0.1) return "중립에 가까운 편";
  if (score > -0.3) return "조금 부정적";
  return "부정적인 편";
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

export function Checkpoints({
  bit,
  detail,
  insights,
  holdings,
  extra,
}: {
  bit: ReturnType<typeof classifyBit> | null;
  detail: StockDetail;
  insights: StockInsights;
  holdings: HoldingWeight[];
  extra: string | null;
}) {
  const market = toNudgeMarket(detail, insights, holdings);
  const nudges = bit && market ? selectNudges(bit, market) : [];
  const items = checkpointItems(nudges, extra);

  return (
    <section aria-labelledby="checkpoint-title" className="surface flex min-w-0 flex-col gap-4 p-4 sm:p-6">
      <h2
        id="checkpoint-title"
        data-bit-type={bit ? (bit.lowConfidence ? "low_confidence" : bit.type) : undefined}
        className="text-xl font-semibold"
      >
        나에게 해당하는 확인 사항
      </h2>
      {!bit && <Unavailable>성향을 진단하면 나에게 맞춘 확인 사항을 볼 수 있어요.</Unavailable>}
      {bit?.lowConfidence && <Unavailable>설문 응답이 서로 엇갈려 참고로만 봐 주세요.</Unavailable>}
      {items.length > 0 ? (
        <ul className="m-0 flex list-none flex-col gap-4 p-0">
          {items.map((item) => {
            const nudge = nudges.find(({ id }) => id === item.key);
            return (
              <li key={item.key} data-nudge={item.key}>
                <p className="m-0 text-base text-ink">{item.text}</p>
                {nudge && market && <p className="m-0 mt-1 text-xs text-muted">{checkpointReason(nudge, market)}</p>}
                {item.key === "N05" && <p className="m-0 mt-1 text-xs text-muted">매도 지시가 아님</p>}
              </li>
            );
          })}
        </ul>
      ) : bit && (
        <Unavailable>{market
          ? "지금 이 종목에서 따로 확인할 점은 없어요."
          : "이 종목은 확인 사항을 고르는 데 필요한 데이터가 아직 없어요."}</Unavailable>
      )}
    </section>
  );
}

function Conclusion({ children }: { children: ReactNode }) {
  return <p className="m-0 text-base text-ink">{children}</p>;
}

export function NewsSentimentPanel({
  insights,
  code,
  sentimentView = marketSentimentView(insights),
}: {
  insights: StockInsights;
  code: string;
  sentimentView?: MarketSentimentView | null;
}) {
  const { sentiment } = insights;
  const [selectedSentimentPeriod, setSelectedSentimentPeriod] = useState<SentimentPeriod>("day");
  const sentimentTimelineRef = useRef<HTMLDivElement | null>(null);
  const [tooltipHost, setTooltipHost] = useState<HTMLDivElement | null>(null);
  const sentimentTabRefs = useRef<Record<SentimentPeriod, HTMLButtonElement | null>>({
    day: null,
    month: null,
    year: null,
  });
  const contextualLive = sentimentView?.basis === "live" && Boolean(code && CONTEXTUAL_LIVE_NEWS_CODES.has(code));
  const todayLive = todayLiveSentimentView(insights);
  const chartLive = selectedSentimentPeriod === "day" ? todayLive : null;
  const sentimentTabs: SentimentPeriod[] = ["day", "month", "year"];
  const periodInput = sentimentDaysIncludingLive(insights)
    .filter(({ date }) => !chartLive || date !== kstDay(Date.parse(chartLive.asOf)));
  const periodDays = aggregateSentimentPeriods(periodInput, selectedSentimentPeriod);
  // ponytail: 점 하나당 SENTIMENT_POINT_PX 폭이라 일별 전체(10년, 약 3,700점)는 너무 넓다. 필요하면 가상 스크롤로.
  const chartDays = selectedSentimentPeriod === "day" ? periodDays.slice(-SENTIMENT_DAY_LIMIT) : periodDays;
  const chartPoints = chartDays.length + (chartLive ? 1 : 0);

  useEffect(() => {
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
      ) : (
        <Unavailable>이 종목은 아직 뉴스를 모으지 않아요. 보유 종목이나 관심 종목에 넣으면 평일 오전 수집 대상에 들어가요.</Unavailable>
      )}
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
            ref={setTooltipHost}
            className="relative min-w-0"
            aria-labelledby={`sentiment-tab-${selectedSentimentPeriod}`}
          >
            <div
              ref={sentimentTimelineRef}
              className="overflow-x-auto pb-2 [scrollbar-width:thin]"
              aria-label="감성 시점 탐색"
              tabIndex={0}
            >
              <div style={{ width: `max(100%, ${chartPoints * SENTIMENT_POINT_PX}px)` }}>
                <SentimentChart
                  key={selectedSentimentPeriod}
                  days={chartDays}
                  connectLive={selectedSentimentPeriod === "day"}
                  live={chartLive}
                  tooltipHost={tooltipHost}
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
      {sentimentView?.headlines.length ? (
        <section aria-labelledby="headline-title" className="flex flex-col gap-2">
          <h3 id="headline-title" className="m-0 text-lg font-semibold text-ink">대표 기사</h3>
          <MoreList items={sentimentView.headlines} label="대표 기사" render={(headline) => (
              <li key={`${headline.date}:${headline.title}`} className="text-sm text-ink">
                {headline.url ? (
                  <a className="text-brand hover:underline" href={headline.url} target="_blank" rel="noreferrer">
                    {headline.title}
                  </a>
                ) : headline.title}
                <span className="ml-2 text-2xs text-muted">{headline.press}</span>
              </li>
          )} />
        </section>
      ) : null}
    </>
  );
}

export function DisclosureList({ disclosures }: { disclosures: StockInsights["disclosures"] }) {
  return (
    <section aria-labelledby="disclosure-title" className="flex flex-col gap-2">
      <h2 id="disclosure-title" className="m-0 text-sm font-medium text-ink">최근 공시</h2>
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

function SentimentChart({ days, live, connectLive, dateLabel = sentimentDateLabel, tooltipHost }: {
  tooltipHost: HTMLDivElement | null;
  days: SentimentDay[];
  live: ReturnType<typeof marketSentimentView>;
  connectLive: boolean;
  dateLabel?: (date: string) => string;
}) {
  const data = [
    ...days.map((day) => ({ ...day, label: dateLabel(day.date), liveScore: null as number | null })),
    ...(live ? [{ date: live.asOf, label: "오늘 Live", score: connectLive ? live.score : null, liveScore: live.score, articleCount: live.articleCount }] : []),
  ];
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
            ticks={[-0.55, 0, 0.55]}
            tickFormatter={(value) => (value > 0 ? "긍정" : value < 0 ? "부정" : "중립")}
            tick={{ fill: CHART.muted, fontSize: 12 }}
            axisLine={false}
            tickLine={false}
            width={36}
            orientation="right"
          />
          <ReferenceArea y1={-0.1} y2={0.1} fill={CHART.track} fillOpacity={1} />
          <Tooltip
            trigger="click"
            active={tip ? undefined : false}
            portal={tooltipHost ?? undefined}
            wrapperStyle={{ position: "absolute", top: 8, left: 0, maxWidth: "100%", pointerEvents: "none", zIndex: 10 }}
            contentStyle={{ ...TOOLTIP_STYLE, whiteSpace: "normal", overflowWrap: "anywhere" }}
            formatter={(value, _name, item) => {
              const count = (item.payload as SentimentDay).articleCount;
              const text = `${moodWord(Number(value))} (점수 ${signed(Number(value))}, 범위 −1~+1)`;
              return count < FEW_ARTICLES ? (
                <>
                  {text}
                  <br />
                  기사 {count}건이라 참고만
                </>
              ) : text;
            }}
          />
          <Line
            dataKey="score"
            name={TERM.sentiment}
            stroke={CHART.priceLine}
            strokeWidth={2}
            dot={({ cx, cy, payload }) =>
              typeof payload.score !== "number" ? <g key={payload.label} /> : payload.articleCount < FEW_ARTICLES ? (
                <circle key={payload.label} data-sentiment-few="true" cx={cx} cy={cy} r={3} fill={CHART.page} stroke={moodChartColor(payload.score)} strokeWidth={1.5} />
              ) : (
                <circle key={payload.label} data-sentiment-mood={moodWord(payload.score)} cx={cx} cy={cy} r={3} fill={moodChartColor(payload.score)} stroke="none" />
              )
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

export function supplyTotals(supply: SupplyDemandDay[]) {
  const latest = supply.at(-1);
  return SUPPLY_SERIES.map((series) => ({
    ...series,
    total: supply.reduce((sum, day) => sum + day[series.key], 0),
    latest: latest?.[series.key] ?? 0,
  }));
}

export function SupplyPanel({ supply, volume }: { supply: SupplyDemandDay[] | null; volume: number | null }) {
  if (!supply?.length) return <Unavailable>이 종목은 사고판 기록이 아직 없어요. 코스피 종목은 평일 저녁 수집 뒤 보여요.</Unavailable>;
  const totals = supplyTotals(supply);
  const max = Math.max(...totals.map(({ total }) => Math.abs(total)), 1);
  const buyer = totals.reduce((top, item) => (item.total > top.total ? item : top));
  const seller = totals.reduce((low, item) => (item.total < low.total ? item : low));
  return (
    <>
      <Conclusion>
        {buyer.total > 0 && seller.total < 0 ? <>
          최근 {supply.length}영업일 동안 <strong className="font-semibold text-up">{buyer.label}</strong>이 가장 많이 샀고,{" "}
          {seller.label}이 가장 많이 팔았어요.
        </> : buyer.total > 0 ? <>
          최근 {supply.length}영업일 동안 {buyer.label}의 순매수 수량이 가장 많았어요.
        </> : seller.total < 0 ? <>
          최근 {supply.length}영업일 동안 {seller.label}의 순매도 수량이 가장 많았어요.
        </> : `최근 ${supply.length}영업일 동안 투자자별 순매수 수량의 합계가 모두 0이에요.`}
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
      <Why>누가 사고팔았는지를 하루 거래량과 견줘 보면 움직임이 큰지 작은지 알 수 있어요.</Why>
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

function copula(word: string): string {
  const code = word.charCodeAt(word.length - 1) - 0xac00;
  return code >= 0 && code < 11172 && code % 28 ? "이에요" : "예요";
}

export const oneDecimal = (value: number) => value.toLocaleString("ko-KR", { maximumFractionDigits: 1 });

// DB에 업종 분류가 없어 코스피 중간값과 비교한다(backend value_pipeline/kospi_medians.py가 미리 계산한 JSON).
const MEDIANS: Partial<Record<string, { median: number; count: number }>> = FINANCIAL_MEDIANS.metrics;

const FINANCIAL_GROUPS = [
  { title: "매출과 이익", keys: ["revenue_growth", "operating_margin", "roe"] },
  { title: "자산과 빚", keys: ["debt_ratio"] },
  { title: "주가와 비교", keys: ["per", "pbr"] },
];

export function FinancialPanel({ financial }: { financial: FinancialSnapshot | null }) {
  if (!financial) return <Unavailable>이 종목은 아직 재무를 모으지 않아요. 로그인한 계정의 보유 종목이나 관심 종목에 넣으면 매주 월요일 오전에 최신 정기보고서로 채워요.</Unavailable>;
  const value = (key: string) => financial.metrics.find((metric) => metric.key === key)?.value;
  const roe = value("roe");
  const debt = value("debt_ratio");
  const groups = FINANCIAL_GROUPS.map(({ title, keys }) => ({
    title,
    metrics: financial.metrics.filter(({ key }) => keys.includes(key)),
  }));
  const otherMetrics = financial.metrics.filter(({ key }) => !FINANCIAL_GROUPS.some(({ keys }) => keys.includes(key)));
  if (otherMetrics.length) groups.push({ title: "기타 재무 지표", metrics: otherMetrics });
  return (
    <>
      {roe != null && debt != null && (
        <Conclusion>
          자기 돈 대비 1년에 <strong className="font-semibold">{oneDecimal(Math.abs(roe))}%</strong>를 {roe < 0 ? "잃었고" : "벌었고"}, 빚은
          자기 돈의{" "}
          <strong className="font-semibold">{oneDecimal(debt)}%</strong> 수준이에요.
        </Conclusion>
      )}
      {groups.filter(({ metrics }) => metrics.length > 0).map(({ title, metrics }, index) => (
        <section key={title} aria-labelledby={`financial-group-${index}`} className="flex flex-col gap-3">
          <h3 id={`financial-group-${index}`} className="text-lg font-semibold">{title}</h3>
          <dl className="m-0 grid grid-cols-1 gap-x-6 gap-y-4 sm:grid-cols-2">
            {metrics.map((metric) => {
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
        </section>
      ))}
      <Why>가격과 별개로 회사의 기초 체력을 코스피 다른 회사들과 견줘 볼 수 있어요.</Why>
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

export function ContributionPanel({
  space,
  features,
  total,
  reasons,
}: {
  features?: ChartSnapshot["inference"]["features"];
  space?: ChartSnapshot["inference"]["contribution_space"];
  total?: number;
  reasons: PredictionReason[];
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
        <Why>신호가 한 가지 근거에 쏠렸는지 보고, 그 근거가 내 판단과 맞는지 견줘 볼 수 있어요.</Why>
      </>
    );
  }
  const target = SIGNAL_WORD[space === "class_0_raw_margin" ? "down" : space === "class_1_raw_margin" ? "flat" : "up"];
  const top = features[0];
  const shown = features.slice(0, 3);
  const hiddenCount = features.length - shown.length;
  const max = Math.max(...shown.map(feature => Math.abs(feature.contribution))) || 1;

  return (
    <>
      <Conclusion>
        모델의{" "}
        <strong className="font-semibold" style={{ color: target === SIGNAL_WORD.down ? "var(--color-down)" : target === SIGNAL_WORD.up ? "var(--color-up)" : "var(--color-ink)" }}>
          {target}
        </strong>{" "}
        점수에 영향을 준 주요 항목은 &lsquo;{top.label_ko}&rsquo;{copula(top.label_ko)}.
      </Conclusion>
      <p className="m-0 text-xs text-muted">영향이 큰 항목 중 {shown.length}개를 보여줘요.</p>
      <ul className="m-0 flex list-none flex-col gap-4 p-0">
        {shown.map((feature) => {
          const up = feature.contribution > 0;
          const color = !up || target === SIGNAL_WORD.flat ? "var(--color-muted)" : target === SIGNAL_WORD.down ? "var(--color-down)" : "var(--color-up)";
          return (
            <li key={feature.name} className="flex flex-col gap-2" data-model-feature={feature.name}>
              <div className="flex flex-wrap items-baseline gap-x-2 gap-y-1">
                <MarketDetail
                  hover
                  title={`${feature.label_ko} 설명`}
                  className="-my-3 inline-flex flex-none"
                  label={<><span className="whitespace-nowrap text-left text-sm font-medium text-ink">{feature.label_ko}</span><span aria-hidden className="px-1 text-muted">ⓘ</span><span className="sr-only"> 설명 보기</span></>}
                >
                  <p className="m-0">{featureDescription(feature.name)}</p>
                </MarketDetail>
                <span className="ml-auto max-w-[55%] text-right text-xs text-body">{contributionWord(feature.contribution, target, total)}</span>
              </div>
              <div className="relative h-1.5 rounded-full bg-track" aria-hidden>
                <span className="absolute inset-y-[-3px] left-1/2 w-px bg-line" />
                <span
                  className="absolute inset-y-0 rounded-full"
                  style={{
                    [up ? "left" : "right"]: "50%",
                    width: `${Math.abs(feature.contribution) / max * 50}%`,
                    backgroundColor: color,
                  }}
                />
              </div>
            </li>
          );
        })}
      </ul>
      {hiddenCount > 0 && (
        <p className="m-0 text-xs text-muted">제공된 다른 {hiddenCount}개 항목은 계산 근거에서 볼 수 있어요.</p>
      )}
      <p className="m-0 text-xs text-muted">{target} 점수를 높이고 낮춘 정도예요. 예측 확률이나 수익률이 아니에요.</p>
      <Why>신호가 한 가지 근거에 쏠렸는지 보고, 그 근거가 내 판단과 맞는지 견줘 볼 수 있어요.</Why>
      <details className="disclosure">
        <summary>계산 근거</summary>
        <div className="flex flex-col gap-2">
        <p className="m-0 text-xs text-muted">이번 {target} 점수에 대한 영향 비중이에요.{!total && " 전체 항목의 영향 크기 합이 없거나 0이라 비중은 미제공이에요."}</p>
        <dl className="m-0 grid grid-cols-[minmax(0,1fr)_auto] gap-x-3 gap-y-2 text-sm">
          {features.map(feature => (
            <div key={feature.name} className="contents">
              <dt>{feature.label_ko}</dt>
              <dd className="m-0 text-right tabular-nums">{contributionPercent(feature.contribution, total)}</dd>
            </div>
          ))}
        </dl>
        <p className="m-0 whitespace-pre-line text-xs text-muted">{`숫자는 전체 항목에서 해당 항목이 차지하는 영향 비중이며, 확률이나 점수의 증감률은 아니에요.
전체 항목의 절댓값을 더하면 100%예요. 여기서는 일부만 보여 합이 100%가 아닐 수 있어요.
점수를 바꾼 항목은 비중의 크기가 10% 이상이면 ‘크게’, 그보다 작으면 ‘조금’이라고 써요. 막대 길이는 보이는 항목 중 가장 큰 값을 기준으로 비교해요.`}</p>
        </div>
      </details>
    </>
  );
}

export function PricePsychology({ psychology }: { psychology: NonNullable<StockInsights["psychology"]> }) {
  return (
    <section aria-labelledby="price-psychology" className="flex flex-col gap-3">
      <h2 id="price-psychology" className="text-xl font-semibold">{PSYCHOLOGY_SCALE.name}</h2>
      <div className="max-w-sm">
        <StageBar axis={PSYCHOLOGY_SCALE} value={psychology.axis} title="최근 가격 흐름" />
      </div>
      <p className="m-0 text-xs text-muted">{PSYCHOLOGY_NOTE}</p>
      <details className="disclosure">
        <summary>계산 근거</summary>
        <p className="m-0 mt-3 text-xs text-muted">{psychologyReason(psychology.axis)}</p>
      </details>
    </section>
  );
}

export function SourceList({ detail, insights }: { detail: StockDetail; insights: StockInsights }) {
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
