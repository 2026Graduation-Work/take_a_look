"use client";

import { useEffect, useRef, useState, useSyncExternalStore, type KeyboardEvent, type ReactNode } from "react";
import Link from "next/link";
import DisclaimerFooter from "./disclaimer-footer";
import {
  Checkpoints,
  ContributionPanel,
  DisclosureList,
  FinancialPanel,
  MEDIANS,
  NewsSentimentPanel,
  PricePsychology,
  SupplyPanel,
  moodWord,
  oneDecimal,
  supplyTotals,
} from "./insight-cards";
import StockMarks from "./stock-marks";
import Segmented from "./segmented";
import MarketDetail from "./market-detail";
import { SUMMARY_SCALE, stageIndex, stageWord } from "@/lib/profiling/axis-scale";
import { classifyBit, type CardId } from "@/lib/profiling/bit";
import GainText from "./gain-text";
import ChangeText from "./change-text";
import { SourceTable } from "./source-line";
import TermLabel from "./term-tip";
import { costBasis, parseSavedHoldings } from "@/lib/holdings-rules";
import { loadLatestCloses, type LatestCloses } from "@/lib/latest-closes";
import { getSupabaseClient } from "@/lib/supabase";
import { getSavedHoldingsSnapshot, getServerHoldingsSnapshot, subscribeToSavedHoldings } from "@/lib/save-holdings";
import PriceHistoryChart from "./price-history-chart";
import ReturnHistogram from "./return-histogram";
import SiteHeader from "./site-header";
import {
  barrierRule,
  compareLine,
  HORIZON_AHEAD,
  HORIZON_LABEL,
  riskLevel,
  similarCasesLine,
  TERM,
  TERM_INFO,
  SIGNAL_WORD,
  topPercentLabel,
} from "@/lib/copy-glossary";
import { bandPrice, changeMeta, formatKstDateTime, formatShares, formatSignedPercent, RISK_FLAG_LABEL, SIGNAL_META, signedPercent } from "@/lib/display";
import { chartDirection } from "@/lib/chart-detail";
import type { ChartHorizon, ChartSnapshot } from "@/lib/chart-public";
import { marketSentimentView, riskSnapshot, type HoldingWeight, type StockInsights } from "@/lib/providers";
import type { InvestorProfileSummary, MarketStatus, StockDetail, StyleAxes } from "@/lib/types";
import FINANCIAL_MEDIANS from "@/lib/financial-medians.json";

const STOCK_TABS = [
  ["overview", "한눈에 보기"],
  ["model", "모델 예측"],
  ["trading", "거래 동향"],
  ["company", "회사 상태"],
  ["news", "뉴스"],
] as const;

type StockTab = (typeof STOCK_TABS)[number][0];
type DetailTab = Exclude<StockTab, "overview">;

const SUMMARY_TABS: Partial<Record<CardId, DetailTab>> = {
  contribution: "model",
  supply: "trading",
  financial: "company",
  sentiment: "news",
};

interface StockDetailViewProps {
  signalHorizon?: 5 | 20;
  onHorizonChange?: (horizon: 5 | 20) => void;
  detail: StockDetail;
  profile: InvestorProfileSummary;
  marketStatus: MarketStatus;
  maxRiskTier: number;
  styleAxes: StyleAxes | null;
  holdings: HoldingWeight[];
  insights: StockInsights;
  source: "mock" | "supabase";
  loading?: boolean;
  dataError?: string;
  onRetry?: () => void;
  chartSnapshots?: Map<ChartHorizon, ChartSnapshot> | null;
}

export default function StockDetailView({
  detail,
  profile,
  marketStatus,
  maxRiskTier,
  styleAxes,
  holdings,
  insights,
  loading = false,
  dataError = "",
  onRetry,
  chartSnapshots,
  signalHorizon = 20,
  onHorizonChange,
}: StockDetailViewProps) {
  const bit = styleAxes ? classifyBit(styleAxes) : null;
  const [activeTab, setActiveTab] = useState<StockTab>("overview");
  const tabRefs = useRef<Partial<Record<StockTab, HTMLButtonElement | null>>>({});
  const [query, setQuery] = useState("");
  const savedList = parseSavedHoldings(
    useSyncExternalStore(subscribeToSavedHoldings, getSavedHoldingsSnapshot, getServerHoldingsSnapshot),
  );
  const saved = savedList?.find(({ code }) => code === detail.code);
  const savedCodes = savedList?.map(({ code }) => code).join(",") ?? "";
  const [closes, setCloses] = useState<LatestCloses>(() => new Map());
  useEffect(() => {
    if (!savedCodes) return;
    let live = true;
    loadLatestCloses(getSupabaseClient(), savedCodes.split(",")).then((next) => live && setCloses(next));
    return () => { live = false; };
  }, [savedCodes]);
  const held = holdings.find(({ code }) => code === detail.code);
  const own = savedList !== null
    ? saved && { quantity: saved.quantity, rawAvgBuyPrice: saved.avgBuyPrice }
    : held && { quantity: held.quantity, rawAvgBuyPrice: held.rawAvgBuyPrice ?? null };
  const nudgeHoldings: HoldingWeight[] = savedList
    ? savedList.map(({ code, quantity, avgBuyPrice }) => ({
        code, quantity, rawAvgBuyPrice: avgBuyPrice, avgBuyPrice: costBasis(avgBuyPrice, closes.get(code)?.close).price,
      }))
    : holdings;

  const preview = chartSnapshots !== undefined;
  const chart = chartSnapshots?.get(signalHorizon);
  const direction = chartDirection(chart);
  const { close, sigma, barriers } = chart?.inference ?? {};
  const modelBasis = chart?.inference.status === "available" && close && sigma && barriers && [close, sigma, barriers.up, barriers.down].every((value) => Number.isFinite(value) && value > 0)
    ? barrierRule(close, barriers.up, barriers.down, sigma, chart.horizon / 5) : null;
  const signal = preview
    ? { ...SIGNAL_META[direction === "up" ? "positive" : direction === "down" ? "negative" : "neutral"],
        label: direction ? SIGNAL_WORD[direction] : "미제공" }
    : SIGNAL_META[detail.signalLight];
  const hasBand = !preview || Boolean(chart?.distribution.histogram.central_68);
  const similar = chart?.distribution.status === "available" ? chart.distribution : null;
  const horizon = detail.returnHorizon ?? "h10";
  const ciPercent = Math.round(detail.returnBand.ciLevel * 100);
  const priceHistory = detail.priceHistory ?? [];
  const priceDate = detail.priceDates?.at(-1) ?? detail.priceProvenance?.asOf ?? detail.asOf;
  const realizedReturns = detail.realizedReturns ?? [];
  const currentPrice = typeof detail.currentPrice === "number" && Number.isFinite(detail.currentPrice) ? detail.currentPrice : null;
  const changePercent = detail.changePercent;
  const changeWon = priceHistory.length >= 2 ? priceHistory[priceHistory.length - 1] - priceHistory[priceHistory.length - 2] : null;
  const changeDirection = changeWon ?? changePercent ?? 0;
  const { color: changeColor, arrow: changeArrow } = changeMeta(changeDirection);
  const changeWord = changeDirection > 0 ? "상승" : changeDirection < 0 ? "하락" : "보합";
  const safeMaxRiskTier =
    Number.isInteger(maxRiskTier) && maxRiskTier >= 1 && maxRiskTier <= 5 ? maxRiskTier : 4;
  const risk = riskSnapshot(detail);
  const volatility = detail.volatilityAnnual == null ? null : `${(detail.volatilityAnnual * 100).toFixed(1)}%`;
  const volatilityRank = detail.volatilityPercentile == null ? null : Math.max(1, Math.round((1 - detail.volatilityPercentile) * 100));
  const riskNote = styleAxes && detail.riskGrade < safeMaxRiskTier
    ? `설문에서 위험 감수를 ‘${stageWord(SUMMARY_SCALE.riskTaking, stageIndex(profile.riskTolerance / 50 - 1))}’ 쪽으로 답했어요. ${volatility && volatilityRank !== null
        ? `이 종목의 최근 1년 변동성은 ${volatility}, 코스피 전 종목 중 큰 쪽 상위 ${volatilityRank}%예요.`
        : `이 종목의 위험도는 ${riskLevel(detail.riskGrade).word}이에요.`}`
    : null;

  const { supply, financial, provenance, psychology, disclosures } = insights;
  const institution = supply?.length ? supplyTotals(supply).find(({ key }) => key === "institution") : null;
  const supplyDate = supply?.at(-1)?.date;
  const metric = financial?.metrics.find(({ key, value }) => key === "debt_ratio" && value != null)
    ?? financial?.metrics.find(({ value }) => value != null);
  const median = metric ? MEDIANS[metric.key]?.median : undefined;
  const financialCompare = metric?.value != null && median !== undefined
    ? compareLine(metric.value, median, FINANCIAL_MEDIANS.basis, metric.unit) : null;
  const sentimentView = marketSentimentView(insights);
  const newsSource = sentimentView?.basis === "live" ? provenance.liveSentiment : provenance.sentiment;
  const range = hasBand ? (
    <>
      <ChangeText value={detail.returnBand.low} precision={1}>{formatSignedPercent(detail.returnBand.low)}</ChangeText>
      {currentPrice !== null && <span className="font-normal text-body"> ({bandPrice(currentPrice, detail.returnBand.low)})</span>}
      {" ~ "}
      <ChangeText value={detail.returnBand.high} precision={1}>{formatSignedPercent(detail.returnBand.high)}</ChangeText>
      {currentPrice !== null && <span className="font-normal text-body"> ({bandPrice(currentPrice, detail.returnBand.high)})</span>}
    </>
  ) : "미제공";
  const summary: Record<DetailTab, ReactNode> = {
    model: preview && !direction && !hasBand ? "모델 분류 및 과거 유사 사례 미제공" : (
      <>
        {HORIZON_LABEL[horizon]} 모델 분류 <span style={{ color: signal.ink }}>{signal.label}</span>
        {hasBand && <span className="block">과거 유사 사례 가운데 {ciPercent}% {range}</span>}
        {detail.asOf && <span className="block text-xs text-muted">{formatKstDateTime(detail.asOf)} 기준</span>}
      </>
    ),
    trading: institution && supplyDate
      ? <>최근 {supply?.length}거래일 기관 <ChangeText value={institution.total}>{formatShares(institution.total)}</ChangeText>
          <span className="block text-xs text-muted">{formatKstDateTime(supplyDate)}까지</span></>
      : "투자자별 순매수 미제공",
    company: financial && metric?.value != null
      ? <>{TERM_INFO[metric.key as keyof typeof TERM_INFO]?.label ?? metric.label} {oneDecimal(metric.value)}{metric.unit}
          {financialCompare && <span className="block text-xs text-muted">{financialCompare}</span>}
          <span className="block text-xs text-muted">{financial.period}</span></>
      : "재무 지표 미제공",
    news: sentimentView
      ? <>{sentimentView.basis === "live" ? "최근 24시간" : "과거"} 기사 표현은 {moodWord(sentimentView.score)}이에요.
          <span className="block text-xs text-muted">
            {formatKstDateTime(sentimentView.asOf)} 수집 기준{newsSource.kind === "real" && `, ${newsSource.source.replaceAll("\u00b7", ", ")}`}
          </span></>
      : "뉴스 분위기 미제공",
  };
  const summaryOrder = [...new Set<DetailTab>([
    ...(bit?.cardOrder ?? []).flatMap((card) => SUMMARY_TABS[card] ?? []),
    ...STOCK_TABS.flatMap(([id]) => id === "overview" ? [] : [id]),
  ])];

  function selectTab(tab: StockTab, moveFocus = false) {
    setActiveTab(tab);
    if (moveFocus) tabRefs.current[tab]?.focus();
  }

  function onTabKeyDown(event: KeyboardEvent<HTMLDivElement>) {
    const current = STOCK_TABS.findIndex(([id]) => id === activeTab);
    const last = STOCK_TABS.length - 1;
    const tabIndexByKey: Partial<Record<string, number>> = {
      ArrowLeft: current === 0 ? last : current - 1,
      ArrowRight: current === last ? 0 : current + 1,
      Home: 0,
      End: last,
    };
    const index = tabIndexByKey[event.key];
    if (index === undefined) return;
    event.preventDefault();
    selectTab(STOCK_TABS[index][0], true);
  }

  return (
    <div className="w-full">
      <SiteHeader query={query} onQueryChange={setQuery} profile={profile} marketStatus={marketStatus} />

      <main className="page pb-12 pt-6">
      <div className="page-wide flex flex-col gap-6">

        {loading && (
          <p role="status" className="m-0 text-xs text-muted">
            내 성향에 맞춘 신호와 근거를 불러오는 중이에요.
          </p>
        )}
        {dataError && (
          <div role="alert" className="surface flex flex-col gap-3 px-5 py-4 sm:flex-row sm:items-center">
            <p className="m-0 min-w-0 text-sm text-body">
              {!preview && "내 데이터를 불러오지 못해 예시 화면을 보여 드려요."}
              <span className="mt-1 block break-words text-xs text-muted">{dataError}</span>
            </p>
            {onRetry && (
              <button type="button" onClick={onRetry} className="btn-secondary flex-none sm:ml-auto">
                다시 시도
              </button>
            )}
          </div>
        )}

        <section aria-labelledby="stock-name" className="flex flex-col gap-2 px-1">
          <div className="flex min-w-0 flex-col gap-2">
            <span className="flex flex-wrap gap-x-3 text-2xs text-muted tabular-nums">
              <span>{detail.code}</span>
              <span>{detail.market}</span>
              {detail.riskFlags.map((flag) => <span key={flag}>{RISK_FLAG_LABEL[flag]}</span>)}
            </span>
            <div className="flex flex-wrap items-center gap-x-1">
              <h1 id="stock-name" className="m-0 break-words text-3xl font-semibold">{detail.name}</h1>
              <StockMarks key={detail.code} code={detail.code} name={detail.name} />
            </div>
          </div>
          <div className="flex flex-col items-start gap-1">
            {currentPrice !== null ? (
              <>
                <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1 tabular-nums">
                  <span className="text-4xl font-semibold">{currentPrice.toLocaleString("ko-KR")}원</span>
                  {typeof changePercent === "number" && Number.isFinite(changePercent) && (
                    <span className="whitespace-nowrap text-sm font-semibold" style={{ color: changeColor }}>
                      <span className="sr-only">전일 대비 {changeWord} </span>
                      {changeArrow && <span aria-hidden="true">{changeArrow} </span>}
                      {changeWon === null
                        ? `${Math.abs(changePercent).toFixed(1)}%`
                        : `${Math.round(Math.abs(changeWon)).toLocaleString("ko-KR")}원 (${Math.abs(changePercent).toFixed(1)}%)`}
                    </span>
                  )}
                </div>
                {priceDate && <span className="text-xs text-muted">{formatKstDateTime(priceDate)} 종가 기준</span>}
              </>
            ) : (
              <span className="text-sm text-muted">시세 데이터가 아직 없어요.</span>
            )}
            {own && (
              <p className="m-0 flex max-w-xs flex-wrap items-baseline gap-x-3 text-xs text-muted tabular-nums">
                <span>보유 {own.quantity.toLocaleString("ko-KR")}주</span>
                {own.rawAvgBuyPrice
                  ? <>
                      <span>평균 매입가 {own.rawAvgBuyPrice.toLocaleString("ko-KR")}원</span>
                      <GainText avgBuyPrice={own.rawAvgBuyPrice} close={detail.currentPrice} aligned />
                    </>
                  : <span>평균 매입가를 <Link href="/portfolio" className="text-brand hover:underline">보유 종목</Link>에 넣으면 평단 대비 수익률이 보여요.</span>}
              </p>
            )}
          </div>
        </section>

        <div role="tablist" aria-label="종목 상세" onKeyDown={onTabKeyDown} className="grid grid-cols-[1.18fr_repeat(3,1fr)_0.72fr] border-b border-line sm:flex sm:gap-4">
          {STOCK_TABS.map(([id, label]) => (
            <button
              key={id}
              ref={(node) => { tabRefs.current[id] = node; }}
              type="button"
              role="tab"
              id={`stock-tab-${id}`}
              aria-selected={activeTab === id}
              aria-controls={`stock-panel-${id}`}
              tabIndex={activeTab === id ? 0 : -1}
              onClick={() => selectTab(id)}
              className="min-h-11 whitespace-nowrap border-b-2 border-transparent px-1 text-xs font-medium text-body aria-selected:border-brand-accent aria-selected:font-semibold aria-selected:text-brand sm:px-4 sm:text-sm"
            >
              {label}
            </button>
          ))}
        </div>

        {STOCK_TABS.map(([id]) => (
          <div
            key={id}
            role="tabpanel"
            id={`stock-panel-${id}`}
            aria-labelledby={`stock-tab-${id}`}
            hidden={activeTab !== id}
            tabIndex={0}
          >
            {activeTab === id && (
              id === "overview" ? (
                <div className="flex flex-col gap-8">
                  <div className="grid items-start gap-6 lg:grid-cols-[minmax(0,2fr)_minmax(0,1fr)]">
                    <section aria-labelledby="recent-price" className="surface flex min-w-0 flex-col gap-4 p-4 sm:p-6">
                      <h2 id="recent-price" className="text-xl font-semibold">최근 주가</h2>
                      {priceHistory.length >= 2 ? (
                        <PriceHistoryChart
                          prices={priceHistory}
                          asOfLabel={priceDate ? formatKstDateTime(priceDate).slice(5, 10) : ""}
                          avgBuyPrice={own?.rawAvgBuyPrice ?? undefined}
                        />
                      ) : (
                        <p className="m-0 text-sm text-muted">최근 주가 기록이 아직 없어요.</p>
                      )}
                      {volatility && (
                        <>
                          <div className="text-sm text-body">
                            최근 1년 <TermLabel term="volatility" /> <strong>{volatility}</strong>
                            {volatilityRank !== null && <span className="block text-xs text-muted">코스피 전 종목 중 큰 쪽 상위 {volatilityRank}%</span>}
                            {detail.riskAsOf && <span className="block text-xs text-muted">{formatKstDateTime(detail.riskAsOf)} 변동성 기준</span>}
                          </div>
                          {risk && <dl className="m-0 grid grid-cols-2 gap-3 text-xs text-muted">
                            <div><dt>3개월 최고가 대비</dt><dd className="m-0"><ChangeText value={risk.drawdownFrom3mHigh * 100}>{signedPercent(risk.drawdownFrom3mHigh)}</ChangeText></dd></div>
                            <div><dt>최근 3거래일</dt><dd className="m-0"><ChangeText value={risk.return3d * 100}>{signedPercent(risk.return3d)}</ChangeText></dd></div>
                          </dl>}
                        </>
                      )}
                      {priceHistory.length >= 2 && <SourceTable rows={[["주가 출처", detail.priceProvenance ?? detail.provenance]]} />}
                      {(detail.priceProvenance?.source.includes("수정주가") || detail.priceProvenance?.source.includes("수정종가")) && priceHistory.length >= 2 && (
                        <p className="m-0 text-xs text-muted">배당과 주식 나눔을 반영한 수정주가예요. 그날 실제로 거래된 가격과 다를 수 있어요.</p>
                      )}
                      {volatility && <details className="disclosure">
                        <summary>계산 근거</summary>
                        <ul className="m-0 mt-2 flex list-none flex-col gap-2 p-0 text-xs text-muted">
                          <li>{TERM_INFO.volatility.label} = 최근 250거래일 하루 수익률(로그)의 표준편차 × √252, 코스피 전 종목 중 순위</li>
                          {risk && <>
                            <li>3개월 최고가 대비 = 지금 종가 ÷ 최근 60거래일 최고 종가 − 1</li>
                            <li>최근 3거래일 = 지금 종가 ÷ 3거래일 전 종가 − 1</li>
                          </>}
                        </ul>
                      </details>}
                    </section>
                    <Checkpoints bit={bit} detail={detail} insights={insights} holdings={nudgeHoldings} extra={riskNote} />
                  </div>

                  <section aria-labelledby="stock-summaries" className="flex flex-col gap-2">
                    <h2 id="stock-summaries" className="text-xl font-semibold">분야별 근거</h2>
                    <ul className="m-0 grid list-none gap-x-8 p-0 lg:grid-cols-2">
                      {summaryOrder.map((tab) => (
                        <li key={tab} className="border-b border-line-soft last:border-b-0 lg:nth-last-2:border-b-0">
                          <button
                            type="button"
                            onClick={() => selectTab(tab, true)}
                            className="flex min-h-11 w-full items-center justify-between gap-4 rounded-sm py-3 text-left hover:bg-track"
                          >
                            <span className="flex min-w-0 flex-col gap-1 break-words">
                              <span className="font-semibold text-ink">{STOCK_TABS.find(([key]) => key === tab)?.[1]}</span>
                              <span className="text-sm text-body">{summary[tab]}</span>
                            </span>
                            <span aria-hidden="true" className="shrink-0 text-muted">›</span>
                          </button>
                        </li>
                      ))}
                    </ul>
                  </section>
                </div>
              ) : (
                <div className="surface flex min-w-0 max-w-[720px] flex-col gap-8 p-4 sm:p-6">
                  {id === "model" && <>
                    <section aria-labelledby="model-signal" className="flex flex-col gap-3">
                      <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-2">
                        <div className="flex items-center">
                          <h2 id="model-signal" className="text-xl font-semibold">모델 신호 <span style={{ color: signal.ink }}>{signal.label}</span></h2>
                          <MarketDetail title="모델 신호 설명" className="inline-flex"
                            label={<><span aria-hidden className="px-2 text-muted">ⓘ</span><span className="sr-only">모델 신호 설명 보기</span></>}>
                            <p className="m-0">{TERM_INFO.model_signal.define} {TERM_INFO.model_signal.read}</p>
                          </MarketDetail>
                        </div>
                        {preview && onHorizonChange && <Segmented label="신호 기간" value={signalHorizon} options={[[5, "1주"], [20, "4주"]]} onChange={onHorizonChange} />}
                      </div>
                      {preview && direction && <p className="m-0 text-sm text-body">{HORIZON_AHEAD[signalHorizon]}를 분류한 모델에서 점수가 가장 높은 쪽이에요.</p>}
                      {!preview && <p className="m-0 text-sm text-muted">{topPercentLabel(detail.rankPercentile)}</p>}
                      <p className="m-0 text-xs text-muted">모델의 분류이며 미래에 오르거나 내릴 확률을 뜻하지 않아요.</p>
                      {(!preview || direction) && <SourceTable rows={[["모델 출처", detail.provenance]]} />}
                      {modelBasis && (
                        <details className="disclosure">
                          <summary>계산 근거</summary>
                          <p className="m-0 mt-3 text-xs text-muted">{modelBasis}</p>
                        </details>
                      )}
                    </section>

                    <section aria-labelledby="more-distribution" className="flex min-w-0 flex-col gap-3">
                      <h2 id="more-distribution" className="text-xl font-semibold">
                        과거 비슷한 신호{detail.similarCaseCount > 0 ? ` ${detail.similarCaseCount.toLocaleString("ko-KR")}건` : ""}의 실제 수익률
                      </h2>
                      <p className="m-0 text-sm text-body">{HORIZON_LABEL[horizon]} 수익률{hasBand ? `의 가운데 ${ciPercent}% 범위` : " 범위"} <strong>{range}</strong></p>
                      {!preview || similar ? (
                        <p className="m-0 text-xs text-muted" data-testid={preview ? "preview-provenance" : undefined}>
                          {detail.asOf && `${formatKstDateTime(detail.asOf)} 모델 기준. `}
                          {similar?.period_start && similar.period_end
                            ? similarCasesLine(similar.period_start, similar.period_end, similar.sample_count, similar.stock_count)
                            : !preview && `과거에 오늘과 비슷했던 경우의 결과예요.`}
                          {hasBand && currentPrice !== null && " 원은 오늘 종가 기준이에요."}
                        </p>
                      ) : <p className="m-0 text-xs text-muted" data-testid="preview-provenance">이 기간의 과거 유사 사례 분포 자료가 아직 없어요.</p>}
                      {hasBand && realizedReturns.length > 0 ? (
                        <>
                          <ReturnHistogram bins={realizedReturns} band={detail.returnBand} caseCount={detail.similarCaseCount} signal={signal} horizonLabel={HORIZON_LABEL[horizon]} />
                          <details className="disclosure">
                            <summary>계산 근거</summary>
                            <p className="m-0 mt-3 text-xs text-muted">범위는 과거 유사 사례 수익률 분포의 가운데 {ciPercent}%예요.</p>
                          </details>
                        </>
                      ) : <p className="m-0 text-xs text-muted">실제 수익률 분포를 그릴 자료가 아직 없어요.</p>}
                    </section>

                    <section aria-labelledby="model-contributions" className="flex flex-col gap-4">
                      <h2 id="model-contributions" className="text-xl font-semibold">{TERM.contribution}</h2>
                      <ContributionPanel
                        space={chart?.inference.contribution_space}
                        total={chart?.inference.contribution_abs_sum}
                        features={preview ? chart?.inference.features ?? [] : undefined}
                        reasons={detail.reasons.filter((reason) => reason.source === "chart")}
                      />
                      {(chart?.inference.features?.length || detail.reasons.some((reason) => reason.source === "chart")) && (
                        <SourceTable rows={[["모델 근거 출처", preview ? detail.provenance : provenance.contributions]]} />
                      )}
                    </section>

                    {psychology && <PricePsychology psychology={psychology} />}
                    {detail.aiAdvice?.trim() && (
                      <section aria-labelledby="model-explanation" className="flex flex-col gap-2">
                        <h2 id="model-explanation" className="text-xl font-semibold">숫자를 풀어 쓴 설명</h2>
                        <p className="m-0 text-xs text-muted">AI 작성, 매매 조언 아님</p>
                        <p className="m-0 text-sm text-body">{detail.aiAdvice}</p>
                      </section>
                    )}
                  </>}
                  {id === "trading" && <SupplyPanel supply={supply} volume={insights.supplyVolume} provenance={provenance.supply} volumeProvenance={psychology?.provenance} />}
                  {id === "company" && <>
                    <section aria-labelledby="company-financials" className="flex flex-col gap-4">
                      <h2 id="company-financials" className="text-xl font-semibold">{TERM.financial}</h2>
                      <FinancialPanel financial={financial} provenance={provenance.financial} />
                    </section>
                    <DisclosureList disclosures={disclosures} />
                  </>}
                  {id === "news" && (
                    <section aria-labelledby="news-sentiment" className="flex min-w-0 flex-col gap-4">
                      <h2 id="news-sentiment" className="text-xl font-semibold">{TERM.sentiment}</h2>
                      <NewsSentimentPanel insights={insights} code={detail.code} sentimentView={sentimentView} />
                    </section>
                  )}
                </div>
              )
            )}
          </div>
        ))}

      </div>
      </main>

      <DisclaimerFooter fixed={false} />
    </div>
  );
}
