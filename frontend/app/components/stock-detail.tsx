"use client";

import { useEffect, useState, useSyncExternalStore } from "react";
import Link from "next/link";
import DisclaimerFooter from "./disclaimer-footer";
import EvidenceTabs, {
  BasisNumbers,
  CalculationBasis,
  Checkpoints,
  SourceList,
  useDemoStyleAxes,
} from "./insight-cards";
import StockMarks from "./stock-marks";
import Segmented from "./segmented";
import MarketDetail from "./market-detail";
import { SUMMARY_SCALE, stageIndex, stageWord } from "@/lib/profiling/axis-scale";
import GainText from "./gain-text";
import ChangeText from "./change-text";
import { costBasis, parseSavedHoldings } from "@/lib/holdings-rules";
import { loadLatestCloses, type LatestCloses } from "@/lib/latest-closes";
import { getSupabaseClient } from "@/lib/supabase";
import { getSavedHoldingsSnapshot, getServerHoldingsSnapshot, subscribeToSavedHoldings } from "@/lib/save-holdings";
import PriceHistoryChart from "./price-history-chart";
import PriceEventPanel from "./price-event-panel";
import { usePriceEvents } from "@/lib/use-price-events";
import ReturnHistogram from "./return-histogram";
import SiteHeader from "./site-header";
import {
  AGREEMENT_ANSWER,
  bandSentence,
  similarCasesLine,
  DIRECTION_WORD,
  HORIZON_AHEAD,
  HORIZON_LABEL,
  riskLevel,
  TERM,
  TERM_INFO,
  topPercentLabel,
  SIGNAL_WORD,
} from "@/lib/copy-glossary";
import { bandPrice, changeMeta, formatSignedPercent, formatWonChange, HORIZON_META, RISK_FLAG_LABEL, SIGNAL_META } from "@/lib/display";
import { chartDirection } from "@/lib/chart-detail";
import type { ChartHorizon, ChartSnapshot } from "@/lib/chart-public";
import type { HoldingWeight, StockInsights } from "@/lib/providers";
import type { InvestorProfileSummary, MarketStatus, StockDetail, StyleAxes } from "@/lib/types";
import { staleLabel } from "@/lib/market-status";

function formatDate(iso: string) {
  return iso.replaceAll("-", ".");
}

function RiskMeter({ grade }: { grade: StockDetail["riskGrade"] }) {
  const { word, filled } = riskLevel(grade);
  return (
    <span className="inline-flex items-center gap-2 text-sm text-body">
      위험도 <strong className="font-semibold text-ink">{word}</strong>
      <span className="flex gap-1" aria-hidden>
        {Array.from({ length: 5 }, (_, index) => (
          <span key={index} className={`h-2 w-3 rounded-[2px] ${index < filled ? "bg-ink" : "bg-track"}`} />
        ))}
      </span>
      <span className="sr-only">5칸 중 {filled}칸</span>
    </span>
  );
}

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
  chartRevision?: number;
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
  chartRevision = 0,
  signalHorizon = 20,
  onHorizonChange,
}: StockDetailViewProps) {
  const demo = useDemoStyleAxes(styleAxes);
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
  const events = usePriceEvents(chartSnapshots?.get(20), chartRevision);
  const direction = chartDirection(chart);
  const signal = preview
    ? { ...SIGNAL_META[direction === "up" ? "positive" : direction === "down" ? "negative" : "neutral"],
        label: direction ? SIGNAL_WORD[direction] : "미제공" }
    : SIGNAL_META[detail.signalLight];
  const hasBand = !preview || Boolean(chart?.distribution.histogram.central_68);
  const similar = chart?.distribution.status === "available" && chart.distribution.period_start && chart.distribution.period_end ? chart.distribution : null;
  const horizon = detail.returnHorizon ?? "h10";
  const ciPercent = Math.round(detail.returnBand.ciLevel * 100);
  const priceHistory = detail.priceHistory ?? [];
  const realizedReturns = detail.realizedReturns ?? [];
  const hasCurrentPrice =
    typeof detail.currentPrice === "number" &&
    Number.isFinite(detail.currentPrice) &&
    typeof detail.changePercent === "number" &&
    Number.isFinite(detail.changePercent);
  const changePercent = detail.changePercent ?? 0;
  const changeWon = priceHistory.length >= 2 ? priceHistory[priceHistory.length - 1] - priceHistory[priceHistory.length - 2] : null;
  const { color: changeColor, arrow: changeArrow } = changeMeta(changePercent, 1);
  const safeMaxRiskTier =
    Number.isInteger(maxRiskTier) && maxRiskTier >= 1 && maxRiskTier <= 5 ? maxRiskTier : 4;
  const riskNote =
    detail.riskGrade < safeMaxRiskTier
      ? `이 종목의 위험도는 ${riskLevel(detail.riskGrade).word}이에요. 설문에서 답한 위험 감수(${stageWord(SUMMARY_SCALE.riskTaking, stageIndex(profile.riskTolerance / 50 - 1))})보다 가격이 크게 흔들릴 수 있어요.`
      : null;
  const drawdownFirst = (demo.styleAxes?.axes.find(({ axis_id }) => axis_id === "drawdown_reaction")?.ratio ?? 0) > 0.3;
  const horizonKeys = preview ? (drawdownFirst ? (["h20", "h5"] as const) : (["h5", "h20"] as const)) : (["h5", "h10", "h20"] as const);
  const horizons = horizonKeys.map((key) => [key, detail.horizonAgreement[key]] as const);
  return (
    <div className="w-full">
      <SiteHeader query={query} onQueryChange={setQuery} profile={profile} marketStatus={marketStatus} />

      <main className="page pb-12 pt-6">
      <div className="page-wide flex flex-col gap-12">

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

        <section aria-labelledby="stock-name" className="flex flex-wrap items-end justify-between gap-x-6 gap-y-3 px-1">
          <div className="flex flex-col gap-2">
            <span className="flex flex-wrap gap-x-3 text-2xs text-muted tabular-nums">
              <span>{detail.code}</span>
              <span>{detail.market}</span>
              {detail.riskFlags.map((flag) => <span key={flag}>{RISK_FLAG_LABEL[flag]}</span>)}
            </span>
            <h1 id="stock-name" className="text-3xl font-semibold">
              {detail.name}
            </h1>
            <RiskMeter grade={detail.riskGrade} />
          </div>
          <div className="flex flex-col items-start gap-1 sm:items-end">
            {hasCurrentPrice ? (
              <>
                <span className="text-4xl font-semibold tabular-nums">
                  {detail.currentPrice?.toLocaleString("ko-KR")}원
                </span>
                <span className="inline-grid grid-cols-[4rem_auto] items-baseline gap-x-2 self-start text-xs text-muted sm:self-end">
                  <span>전일 대비</span>
                  <span className="whitespace-nowrap text-right text-sm font-semibold tabular-nums" style={{ color: changeColor }}>
                    {changeArrow && `${changeArrow} `}{changeWon === null ? formatSignedPercent(changePercent) : formatWonChange(changeWon, changePercent)}
                  </span>
                </span>
                {detail.asOf && staleLabel(detail.asOf) && (
                  <span className="text-xs text-muted">{formatDate(detail.asOf)} 기준</span>
                )}
              </>
            ) : (
              <span className="text-sm text-muted">시세 데이터가 아직 없어요.</span>
            )}
            {own && (
              <p className="m-0 flex flex-wrap items-baseline gap-x-3 self-start text-xs text-muted tabular-nums sm:self-end">
                <span>보유 {own.quantity.toLocaleString("ko-KR")}주</span>
                {own.rawAvgBuyPrice
                  ? <GainText avgBuyPrice={own.rawAvgBuyPrice} close={detail.currentPrice} aligned />
                  : <span>평균 매입가를 <Link href="/portfolio" className="text-brand hover:underline">보유 종목</Link>에 넣으면 평단 대비 수익률이 보여요</span>}
              </p>
            )}
          </div>
        </section>

        <StockMarks code={detail.code} name={detail.name} />

        <section aria-labelledby="glance-title" className="surface flex flex-col gap-4 p-6">
          <div className="flex flex-col gap-1">
            <div className="flex items-start">
            <h2 id="glance-title" className="text-xl font-semibold">
              모델 신호 <span style={{ color: signal.ink }}>{signal.label}</span>
              {preview && direction && <span className="ml-3 text-xs font-normal text-muted">{HORIZON_AHEAD[signalHorizon]}</span>}
              {!preview && <span className="block text-xs font-normal text-muted sm:ml-2 sm:inline">{topPercentLabel(detail.rankPercentile)}</span>}
            </h2>
            <MarketDetail title="모델 신호 설명" className="inline-flex"
              label={<><span aria-hidden className="px-2 text-muted">ⓘ</span><span className="sr-only">모델 신호 설명 보기</span></>}>
              <p className="m-0">{TERM_INFO.model_signal.define} {TERM_INFO.model_signal.read}</p>
            </MarketDetail>
            </div>
            {preview && onHorizonChange && <div className="flex justify-end">
              <Segmented label="신호 기간" value={signalHorizon} options={[[5, "1주"], [20, "4주"]]} onChange={onHorizonChange} />
            </div>}
            <p className="m-0 text-sm text-body">
              {bandSentence(horizon, detail.returnBand.ciLevel)}:{" "}
              <strong className="font-semibold tabular-nums text-ink">
                {hasBand ? <>
                  <ChangeText value={detail.returnBand.low} precision={1}>{formatSignedPercent(detail.returnBand.low)}</ChangeText>
                  {hasCurrentPrice && <span className="font-normal text-body"> ({bandPrice(detail.currentPrice!, detail.returnBand.low)})</span>}
                  {" ~ "}
                  <ChangeText value={detail.returnBand.high} precision={1}>{formatSignedPercent(detail.returnBand.high)}</ChangeText>
                  {hasCurrentPrice && <span className="font-normal text-body"> ({bandPrice(detail.currentPrice!, detail.returnBand.high)})</span>}
                </> : "미제공"}
              </strong>
            </p>
          </div>
          {priceHistory.length >= 2 ? (
            <PriceHistoryChart
              prices={priceHistory}
              band={hasBand ? detail.returnBand : undefined}
              signal={signal}
              asOfLabel={formatDate(detail.asOf).slice(5)}
              horizonLabel={HORIZON_LABEL[horizon]}
              avgBuyPrice={own?.rawAvgBuyPrice ?? undefined}
              priceEvents={{ dates: detail.priceDates ?? [], moves: events.moves, selectedDate: events.move?.date, select: events.select }}
            />
          ) : (
            <p className="m-0 text-xs text-muted">
              최근 주가 기록이 아직 없어 흐름을 그리지 않았어요.
            </p>
          )}
          <p className="m-0 max-w-2xl text-2xs text-muted" data-testid={preview ? "preview-provenance" : undefined}>{preview && detail.asOf && staleLabel(detail.asOf) && `${formatDate(detail.asOf)} 기준. `}{similar
            ? similarCasesLine(similar.period_start!, similar.period_end!, similar.sample_count, similar.stock_count)
            : `과거에 오늘과 비슷했던 경우, ${HORIZON_LABEL[horizon]} 수익률은 대부분 이 범위 안이었어요.`}{hasBand && hasCurrentPrice && " 원은 오늘 종가 기준이에요."}</p>
          {chart && <PriceEventPanel events={events} />}
        </section>

        <Checkpoints demo={demo} detail={detail} insights={insights} holdings={nudgeHoldings} extra={riskNote} />

        <EvidenceTabs detail={detail} insights={insights} demo={demo}
          contributionSpace={chart?.inference.contribution_space}
          contributionTotal={chart?.inference.contribution_abs_sum}
          modelFeatures={preview ? chart?.inference.features ?? [] : undefined} />

        <details className="disclosure surface p-6">
          <summary>
            <span className="text-lg font-semibold">더 알아보기</span>
          </summary>
          <div className="mt-6 flex flex-col gap-12">
            <CalculationBasis demo={demo} detail={detail} insights={insights} holdings={nudgeHoldings} />

            <section aria-labelledby="more-distribution" className="flex flex-col gap-3">
              <h3 id="more-distribution" className="text-lg font-semibold">
                과거 비슷한 신호 {detail.similarCaseCount}건의 실제 수익률
              </h3>
              {realizedReturns.length > 0 ? (
                <>
                  <ReturnHistogram
                    bins={realizedReturns}
                    band={detail.returnBand}
                    caseCount={detail.similarCaseCount}
                    signal={signal}
                    horizonLabel={HORIZON_LABEL[horizon]}
                  />
                  <p className="m-0 text-xs text-muted">
                    위 범위는 이 분포의 가운데 {ciPercent}%예요. 미래 가격 경로가 아니라 {HORIZON_LABEL[horizon]} 시점의 분포예요.
                  </p>
                </>
              ) : (
                <p className="m-0 text-xs text-muted">분포 원본이 아직 저장되지 않아 그림은 생략했어요.</p>
              )}
            </section>

            <section aria-labelledby="more-horizons" className="flex flex-col gap-3">
              <h3 id="more-horizons" className="text-lg font-semibold">
                {TERM.horizonAgreement}
              </h3>
              <p className="m-0 text-sm text-body">{preview
                ? "각 모델에서 가장 높은 분류 점수의 방향이에요. 미래에 오르거나 내릴 확률을 뜻하지 않아요."
                : AGREEMENT_ANSWER[detail.horizonAgreement.agreement]}</p>
              <ul className={`m-0 grid list-none gap-3 p-0 ${preview ? "grid-cols-2" : "grid-cols-3"}`}>
                {horizons.map(([key, legacyDirection]) => {
                  const direction = preview ? chartDirection(chartSnapshots?.get(key === "h5" ? 5 : 20)) : legacyDirection;
                  return (
                  <li key={key} className="flex flex-col gap-1">
                    <span className="text-2xs text-muted">{preview ? key === "h5" ? `${HORIZON_AHEAD[5]}(5거래일)` : `${HORIZON_AHEAD[20]}(20거래일)` : HORIZON_LABEL[key]}</span>
                    <span className="text-sm font-semibold" style={{ color: direction ? HORIZON_META[direction].ink : "var(--color-muted)" }}>
                      {direction ? `${HORIZON_META[direction].arrow} ${preview ? SIGNAL_WORD[direction] : DIRECTION_WORD[direction]}` : "미제공"}
                    </span>
                  </li>
                  );
                })}
              </ul>
              <p className="m-0 text-xs text-muted tabular-nums">
                {preview ? `과거 상승 비율은 제공하지 않아요.${drawdownFirst ? " 하락 때 정리하는 편이라고 답해 4주를 먼저 놓았어요." : ""}` : `과거 비슷한 신호 ${detail.similarCaseCount}건 중 ${Math.round(detail.hitRate * 100)}%가 실제로 올랐어요.`}
              </p>
            </section>

            {detail.aiAdvice?.trim() && (
              <section aria-labelledby="more-ai" className="flex flex-col gap-2">
                <h3 id="more-ai" className="text-lg font-semibold">
                  숫자를 풀어 쓴 설명 <span className="text-2xs font-normal text-muted">AI 작성, 매매 조언 아님</span>
                </h3>
                <p className="m-0 text-sm text-body">{detail.aiAdvice}</p>
              </section>
            )}


            <BasisNumbers demo={demo} insights={insights} chart={chart} />

            <section aria-labelledby="more-sources" className="flex flex-col gap-3">
              <h3 id="more-sources" className="text-lg font-semibold">
                데이터 출처
              </h3>
              <SourceList detail={detail} insights={insights} />
            </section>

          </div>
        </details>

      </div>
      </main>

      <DisclaimerFooter fixed={false} />
    </div>
  );
}
