"use client";

import Link from "next/link";
import { useState } from "react";
import { usePublicCharts } from "@/lib/use-public-charts";
import { chartChange, type ChartHorizon, type ChartSnapshot } from "@/lib/chart-public";
import type { InvestorProfileSummary, MarketStatus } from "@/lib/types";
import type { StockInsights } from "@/lib/providers";
import { SIGNAL_META } from "@/lib/display";
import SiteHeader from "./site-header";
import StockMarks from "./stock-marks";
import SourceChip from "./source-chip";
import ReturnHistogram from "./return-histogram";
import DisclaimerFooter from "./disclaimer-footer";

const signed = (value: number) => `${value > 0 ? "+" : ""}${value.toFixed(2)}%`;
const period = (horizon: ChartHorizon) => horizon === 5 ? "1주 · 5거래일" : "4주 · 20거래일";
const note = "연결 확인용 · 모델 검증 전";

export function PreviewStockRow({ code, name }: { code: string; name: string }) {
  const { charts, loading, error } = usePublicCharts([code]);
  const snapshot = charts?.get(code)?.get(20);
  const band = snapshot?.distribution.histogram.central_68;
  return <Link href={`/stocks/${code}`} data-stock-row={code} className="flex min-h-11 flex-col gap-1 px-5 py-4 text-ink hover:bg-field hover:no-underline">
    <span className="text-base font-medium">{name} <span className="text-xs text-muted">{code}</span></span>
    <span className="text-xs text-muted">{note}{snapshot ? ` · ${snapshot.data_asof} 기준` : ""}</span>
    <span className="text-sm">{loading ? "시험 결과를 불러오는 중이에요." : error ? "연결을 확인하지 못했어요. 상세에서 다시 시도해 주세요." :
      band ? `4주 · 20거래일 후 과거 수익률 가운데 68%: ${signed(band.low)} ~ ${signed(band.high)}` : "시험 결과가 아직 준비되지 않았어요."}</span>
    {snapshot && <span className="text-xs text-muted">과거 유사 사례 {snapshot.distribution.sample_count.toLocaleString("ko-KR")}건 · 기존 모델 계산 · 상세 보기</span>}
  </Link>;
}

function ObservedPrices({ chart }: { chart: ChartSnapshot }) {
  const history = chart.prices.history;
  if (history.length < 2) return <p>가격 기록이 부족해요.</p>;
  const low = Math.min(...history.map(p => p.close));
  const high = Math.max(...history.map(p => p.close));
  const span = high - low || high * 0.01;
  const points = history.map((p, i) => `${70 + i * 670 / (history.length - 1)},${190 - (p.close - low) * 160 / span}`).join(" ");
  return <figure className="m-0">
    <svg viewBox="0 0 760 225" role="img" aria-label={`${history[0].date}부터 ${history.at(-1)!.date}까지 관측된 수정종가`} className="w-full">
      <text x="0" y="34" fill="var(--color-muted)" fontSize="13">{high.toLocaleString("ko-KR")}원</text>
      <text x="0" y="194" fill="var(--color-muted)" fontSize="13">{low.toLocaleString("ko-KR")}원</text>
      <polyline points={points} fill="none" stroke="var(--color-body)" strokeWidth="2" />
      <text x="70" y="218" fill="var(--color-muted)" fontSize="13">{history[0].date}</text>
      <text x="740" y="218" textAnchor="end" fill="var(--color-muted)" fontSize="13">{history.at(-1)!.date}</text>
    </svg>
    <figcaption className="text-xs text-muted">관측된 수정종가 · {chart.prices.source} · {history.length}개 거래일</figcaption>
  </figure>;
}

export default function ChartPreviewDetail({ code, name, profile, marketStatus, insights }: {
  code: string; name: string; profile: InvestorProfileSummary; marketStatus: MarketStatus; insights: StockInsights;
}) {
  const [query, setQuery] = useState("");
  const [horizon, setHorizon] = useState<ChartHorizon>(20);
  const { charts, loading, error, retry } = usePublicCharts([code]);
  const chart = charts?.get(code)?.get(horizon);
  const latest = chart?.prices.history.at(-1);
  const change = chart ? chartChange(chart) : null;
  const distribution = chart?.distribution;
  const band = distribution?.histogram.central_68;
  return <div className="w-full">
    <SiteHeader query={query} onQueryChange={setQuery} profile={profile} marketStatus={marketStatus} />
    <main className="mx-auto flex w-full max-w-[960px] flex-col gap-6 px-4 pb-12 pt-5 sm:px-8">
      <Link href="/" className="btn-text self-start">‹ 대시보드</Link>
      <header className="flex flex-col gap-2">
        <h1 className="text-3xl font-semibold">{name}</h1>
        <p className="m-0 text-sm text-body">기존 모델의 시험 결과가 화면에 연결되는지 확인하는 화면이에요.</p>
        <p className="m-0 text-xs text-muted" data-testid="preview-provenance">{note}{chart ? ` · ${chart.data_asof} 기준` : ""}</p>
        {latest && <p className="m-0 text-xl tabular-nums">기준일 수정종가 {latest.close.toLocaleString("ko-KR")}원
          {change !== null && <span className="ml-2 text-sm text-muted">전일 대비 {signed(change)}</span>}</p>}
      </header>
      <StockMarks code={code} name={name} />
      <div className="segmented self-start" role="tablist" aria-label="비교 기간">
        {([5, 20] as const).map(h => <button key={h} type="button" role="tab" aria-selected={horizon === h} tabIndex={horizon === h ? 0 : -1} onClick={() => setHorizon(h)}
          onKeyDown={event => { if (["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) {
            event.preventDefault();
            const next = event.key === "Home" ? 5 : event.key === "End" ? 20 : h === 5 ? 20 : 5;
            setHorizon(next);
            (event.currentTarget.parentElement?.children[next === 5 ? 0 : 1] as HTMLButtonElement)?.focus();
          } }}>{period(h)}</button>)}
      </div>
      {loading && <p role="status">시험 결과를 불러오는 중이에요.</p>}
      {error && <div role="alert" className="surface flex flex-wrap items-center gap-3 p-5">
        <p className="m-0 text-sm">{error}</p><button type="button" className="btn-secondary" onClick={retry}>다시 시도</button>
      </div>}
      {!loading && !error && !chart && <div className="surface p-5"><p>이 기간의 시험 결과가 아직 준비되지 않았어요.</p><button type="button" className="btn-secondary" onClick={retry}>다시 시도</button></div>}
      {chart && <>
        <section className="surface flex flex-col gap-4 p-6" aria-label="관측 가격">
          <h2 className="text-xl font-semibold">기준일까지의 가격 흐름</h2>
          <ObservedPrices chart={chart} />
        </section>
        <section className="surface flex flex-col gap-4 p-6" aria-label="과거 유사 사례 분포">
          <h2 className="text-xl font-semibold">{period(horizon)} 후 과거 수익률</h2>
          {distribution?.status === "available" && band ? <>
            <p className="m-0 text-sm">유사 사례의 가운데 68%: <strong className="tabular-nums">{signed(band.low)} ~ {signed(band.high)}</strong></p>
            <ReturnHistogram bins={distribution.histogram.bins.map(b => ({ from: b.left, to: b.right, count: b.count }))}
              band={{ ...band, ciLevel: .68 }} caseCount={distribution.sample_count} signal={SIGNAL_META.neutral} horizonLabel={period(horizon)} />
          </> : <p>{distribution?.status === "no_cases" ? "조건에 맞는 과거 사례가 없어요." : "이 결과의 과거 사례 분포를 계산하지 못했어요."}</p>}
          <p className="m-0 text-xs text-muted">과거 유사 사례 {distribution?.sample_count.toLocaleString("ko-KR")}건 · {distribution?.stock_count.toLocaleString("ko-KR")}종목
            {distribution?.period_start ? ` · ${distribution.period_start} ~ ${distribution.period_end}` : ""} · 기존 모델의 과거 예측 기록</p>
        </section>
        <section className="surface flex flex-col gap-4 p-6" aria-label="모델 계산 근거">
          <h2 className="text-xl font-semibold">모델 계산에 영향을 준 항목</h2>
          <p className="m-0 text-sm text-body">각 항목이 상방 점수를 높였는지 낮췄는지 확인해요. 수익률 변화량을 뜻하지 않아요.</p>
          {chart.inference.status === "unavailable" ? <p>이 기준일에는 추론값이 없어요.</p> :
            <ul className="m-0 list-none space-y-4 p-0">{chart.inference.features.map(f => <li key={f.name}>
              <div className="flex flex-wrap justify-between gap-2"><strong className="font-medium">{f.label_ko}</strong>
                <span className="tabular-nums text-sm">{f.contribution >= 0 ? "높이는 쪽" : "낮추는 쪽"} {Math.abs(f.contribution).toFixed(4)}</span></div>
              <p className="m-0 text-xs text-muted">{f.meaning_ko} · 관측값 {f.value === null ? "없음" : f.value.toLocaleString("ko-KR", { maximumFractionDigits: 4 })}</p>
            </li>)}</ul>}
          <p className="m-0 text-xs text-muted">기존 모델의 상방 원점수 기여도 · 0 기준 · {chart.data_asof}</p>
        </section>
      </>}
      <section className="surface flex flex-col gap-4 p-6" aria-label="뉴스와 재무">
        <h2 className="text-xl font-semibold">뉴스·재무 확인</h2>
        <SourceChip provenance={insights.provenance.sentiment} />
        <ul className="m-0 list-none space-y-3 p-0">{insights.sentiment?.headlines.map(h => <li key={`${h.date}:${h.title}`} className="text-sm">{h.title}<span className="ml-2 text-xs text-muted">{h.date}</span></li>)}</ul>
        {insights.financial && <><p className="m-0 text-xs text-muted">{insights.financial.period} · <SourceChip provenance={insights.provenance.financial} /></p>
          <dl className="grid grid-cols-2 gap-3 sm:grid-cols-3">{insights.financial.metrics.map(m => <div key={m.key}><dt className="text-xs text-muted">{m.label}</dt><dd className="m-0 tabular-nums">{m.value === null ? "—" : `${m.value.toLocaleString("ko-KR")}${m.unit}`}</dd></div>)}</dl></>}
      </section>
    </main>
    <DisclaimerFooter fixed={false} />
  </div>;
}
