"use client";

// 종목 상세 — "이 종목, 지금 뭘 확인하면 되지?"
// 순서: 헤더 → 한눈에 보기 → 나에게 맞춘 체크포인트 → 판단 근거 4탭 → 더 알아보기(접힘).
// 필수 정보는 지우지 않고 "더 알아보기"에 접는다.

import { useState } from "react";
import Link from "next/link";
import DisclaimerFooter from "./disclaimer-footer";
import EvidenceTabs, {
  CalculationBasis,
  Checkpoints,
  ScreenGuideBanner,
  SourceList,
  useDemoStyleAxes,
} from "./insight-cards";
import SourceLine from "./source-line";
import StockMarks from "./stock-marks";
import PriceHistoryChart from "./price-history-chart";
import ReturnHistogram from "./return-histogram";
import SiteHeader from "./site-header";
import {
  AGREEMENT_ANSWER,
  bandSentence,
  DIRECTION_WORD,
  HORIZON_LABEL,
  riskLevel,
  TERM,
  topPercentLabel,
} from "@/lib/copy-glossary";
import { HORIZON_META, RISK_FLAG_LABEL, SIGNAL_META } from "@/lib/display";
import { chartDirection } from "@/lib/chart-detail";
import type { ChartHorizon, ChartSnapshot } from "@/lib/chart-public";
import type { HoldingWeight, StockInsights } from "@/lib/providers";
import type { InvestorProfileSummary, MarketStatus, StockDetail, StyleAxes } from "@/lib/types";

function formatPercent(value: number) {
  return `${value > 0 ? "+" : ""}${value.toFixed(1)}%`;
}

function formatDate(iso: string) {
  return iso.replaceAll("-", ".");
}

function RiskMeter({ grade }: { grade: StockDetail["riskGrade"] }) {
  const { word, filled } = riskLevel(grade);
  return (
    <span className="inline-flex items-center gap-2 text-sm text-body">
      위험도 <strong className="font-semibold text-ink">{word}</strong>
      <span className="flex gap-0.5" aria-hidden>
        {Array.from({ length: 5 }, (_, index) => (
          <span key={index} className={`h-2 w-3 rounded-[2px] ${index < filled ? "bg-ink" : "bg-track"}`} />
        ))}
      </span>
      <span className="sr-only">5칸 중 {filled}칸</span>
    </span>
  );
}

interface StockDetailViewProps {
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
}: StockDetailViewProps) {
  const demo = useDemoStyleAxes(styleAxes);
  const [query, setQuery] = useState("");

  const preview = chartSnapshots !== undefined;
  const chart = chartSnapshots?.get(20);
  const direction = chartDirection(chart);
  const signal = preview
    ? { ...SIGNAL_META[direction === "up" ? "positive" : direction === "down" ? "negative" : "neutral"],
        label: direction === "up" ? "상방" : direction === "down" ? "하방" : direction === "flat" ? "중립" : "미제공" }
    : SIGNAL_META[detail.signalLight];
  const hasBand = !preview || Boolean(chart?.distribution.histogram.central_68);
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
  const changeColor =
    changePercent > 0 ? "var(--color-up)" : changePercent < 0 ? "var(--color-down)" : "var(--color-muted)";
  const changeArrow = changePercent > 0 ? "▲" : changePercent < 0 ? "▼" : "";
  const safeMaxRiskTier =
    Number.isInteger(maxRiskTier) && maxRiskTier >= 1 && maxRiskTier <= 5 ? maxRiskTier : 4;
  // 성향에서 나온 허용 범위(소프트 틸트)보다 위험한 종목이면 체크포인트에 한 줄 더한다. 종목을 거르지 않는다.
  const riskNote =
    detail.riskGrade < safeMaxRiskTier
      ? `이 종목의 위험도는 ${riskLevel(detail.riskGrade).word}이에요. 설문에서 답한 위험 감수 정도(${profile.riskTolerance})보다 가격이 크게 흔들릴 수 있어요.`
      : null;
  // #170: 공개 모델은 1주·4주 둘. 하락 시 이탈 쪽으로 답한 성향(체크포인트와 같은 0.3 기준)은 단기 흔들림보다 4주를 먼저 본다.
  const drawdownFirst = (demo.styleAxes?.axes.find(({ axis_id }) => axis_id === "drawdown_reaction")?.ratio ?? 0) > 0.3;
  const horizonKeys = preview ? (drawdownFirst ? (["h20", "h5"] as const) : (["h5", "h20"] as const)) : (["h5", "h10", "h20"] as const);
  const horizons = horizonKeys.map((key) => [key, detail.horizonAgreement[key]] as const);
  return (
    <div className="w-full">
      <SiteHeader query={query} onQueryChange={setQuery} profile={profile} marketStatus={marketStatus} />

      <main className="mx-auto box-border flex w-full max-w-[960px] flex-col gap-8 px-4 pb-12 pt-5 sm:px-8">
        <Link href="/" className="btn-text self-start text-xs">
          ‹ 대시보드
        </Link>

        {loading && (
          <p role="status" className="m-0 text-sm text-muted">
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

        {/* 1. 헤더 */}
        <section aria-labelledby="stock-name" className="flex flex-wrap items-end justify-between gap-x-6 gap-y-3 px-1">
          <div className="flex flex-col gap-1.5">
            <span className="eyebrow tabular-nums">
              {detail.code} · {detail.market}
              {detail.riskFlags.length > 0 && ` · ${detail.riskFlags.map((flag) => RISK_FLAG_LABEL[flag]).join(" · ")}`}
            </span>
            <h1 id="stock-name" className="text-3xl font-semibold">
              {detail.name}
            </h1>
            <RiskMeter grade={detail.riskGrade} />
          </div>
          <div className="flex flex-col items-start gap-0.5 sm:items-end">
            {hasCurrentPrice ? (
              <>
                <span className="text-4xl font-semibold tabular-nums">
                  {detail.currentPrice?.toLocaleString("ko-KR")}원
                </span>
                <span className="text-base font-medium tabular-nums" style={{ color: changeColor }}>
                  {changeArrow} {formatPercent(changePercent)}
                  <span className="ml-1.5 text-xs font-normal text-muted">
                    전일 대비 · {formatDate(detail.asOf)} 기준
                  </span>
                </span>
              </>
            ) : (
              <span className="text-sm text-muted">시세 데이터가 아직 없어요</span>
            )}
          </div>
        </section>

        <StockMarks code={detail.code} name={detail.name} />

        {/* 2. 한눈에 보기 */}
        <section aria-labelledby="glance-title" className="surface flex flex-col gap-4 p-6">
          <div className="flex flex-col gap-1">
            <h2 id="glance-title" className="text-xl font-semibold">
              모델 신호 <span style={{ color: signal.ink }}>{signal.label}</span>
              {!preview && <span className="block text-sm font-normal text-muted sm:ml-2 sm:inline">{topPercentLabel(detail.rankPercentile)}</span>}
            </h2>
            <p className="m-0 text-sm text-body">
              {bandSentence(horizon, detail.returnBand.ciLevel)}:{" "}
              <strong className="font-semibold tabular-nums text-ink">
                {hasBand ? `${formatPercent(detail.returnBand.low)} ~ ${formatPercent(detail.returnBand.high)}` : "미제공"}
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
            />
          ) : (
            <p className="m-0 rounded-md bg-field px-4 py-8 text-center text-sm text-muted">
              최근 주가 기록이 아직 없어 흐름을 그리지 않았어요.
            </p>
          )}
          <div className="m-0 flex flex-wrap items-center gap-x-3 gap-y-1 text-2xs text-muted">
            <span className="max-w-2xl" data-testid={preview ? "preview-provenance" : undefined}>{preview && `모델 검증 전${detail.asOf ? ` · ${formatDate(detail.asOf)} 기준` : ""} · `}지난 3개월 주가와 {HORIZON_LABEL[horizon]} 범위만 그려요. 미래 가격 곡선은 그리지 않아요.</span>
            <SourceLine label="주가 출처" provenance={detail.priceProvenance ?? detail.provenance} />
            <SourceLine label="신호 출처" provenance={detail.provenance} />
          </div>
        </section>

        {/* 3. 나에게 맞춘 체크포인트 */}
        <Checkpoints demo={demo} detail={detail} insights={insights} holdings={holdings} extra={riskNote} />

        {/* 4. 판단 근거 4가지 */}
        <EvidenceTabs detail={detail} insights={insights} demo={demo}
          contributionSpace={chart?.inference.contribution_space}
          contributionTotal={chart?.inference.contribution_abs_sum}
          modelFeatures={preview ? chart?.inference.features ?? [] : undefined} />

        {/* 5. 더 알아보기 */}
        <details className="disclosure surface p-6">
          <summary>
            <span className="flex flex-col gap-0.5">
              <span className="text-lg font-semibold">더 알아보기</span>
              <span className="text-xs text-muted">수익률 분포 · 기간별 비교 · 계산 근거 · 데이터 출처</span>
            </span>
          </summary>
          <div className="mt-6 flex flex-col gap-8">
            <section aria-labelledby="more-distribution" className="flex flex-col gap-3">
              <h3 id="more-distribution" className="text-base font-semibold">
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
                <p className="m-0 text-sm text-muted">분포 원본이 아직 저장되지 않아 그림은 생략했어요.</p>
              )}
            </section>

            <section aria-labelledby="more-horizons" className="flex flex-col gap-3">
              <h3 id="more-horizons" className="text-base font-semibold">
                {TERM.horizonAgreement}
              </h3>
              <p className="m-0 text-sm text-body">{preview
                ? "각 모델에서 가장 높은 분류 점수의 방향이에요. 미래 상승·하락 확률을 뜻하지 않아요."
                : AGREEMENT_ANSWER[detail.horizonAgreement.agreement]}</p>
              <ul className={`m-0 grid list-none gap-3 p-0 ${preview ? "grid-cols-2" : "grid-cols-3"}`}>
                {horizons.map(([key, legacyDirection]) => {
                  const direction = preview ? chartDirection(chartSnapshots?.get(key === "h5" ? 5 : 20)) : legacyDirection;
                  return (
                  <li key={key} className="flex flex-col gap-0.5 rounded-md bg-field px-4 py-3">
                    <span className="text-xs text-muted">{preview ? key === "h5" ? "1주 · 5거래일" : "4주 · 20거래일" : HORIZON_LABEL[key]}</span>
                    <span className="text-sm font-semibold" style={{ color: direction ? HORIZON_META[direction].ink : "var(--color-muted)" }}>
                      {direction ? `${HORIZON_META[direction].arrow} ${preview ? direction === "up" ? "상방" : direction === "down" ? "하방" : "중립" : DIRECTION_WORD[direction]}` : "미제공"}
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
                <h3 id="more-ai" className="text-base font-semibold">
                  숫자를 풀어 쓴 설명 <span className="text-xs font-normal text-muted">AI 작성 · 매매 조언 아님</span>
                </h3>
                <p className="m-0 text-sm leading-relaxed text-body">{detail.aiAdvice}</p>
              </section>
            )}

            <section aria-labelledby="more-basis" className="flex flex-col gap-3">
              <h3 id="more-basis" className="text-base font-semibold">
                계산 근거
              </h3>
              <CalculationBasis demo={demo} detail={detail} insights={insights} holdings={holdings} />
            </section>

            <section aria-labelledby="more-sources" className="flex flex-col gap-3">
              <h3 id="more-sources" className="text-base font-semibold">
                데이터 출처
              </h3>
              <SourceList detail={detail} insights={insights} />
            </section>

          </div>
        </details>

        <ScreenGuideBanner bit={demo.bit} />
      </main>

      <DisclaimerFooter fixed={false} />
    </div>
  );
}
