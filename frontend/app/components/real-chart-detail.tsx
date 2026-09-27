"use client";

import { useState } from "react";
import Link from "next/link";
import DisclaimerFooter from "./disclaimer-footer";
import ReturnHistogram from "./return-histogram";
import type { ChartSignalDetail, ChartSignalDetailV1, ChartSignalDetailV2, PublishedChartDetail } from "@/lib/chart-signal";

const label = { 5: "다음 5거래일", 20: "다음 20거래일" } as const;
const date = (value: string | null) => value?.replaceAll("-", ".") ?? "—";
const money = (value: number) => `${value.toLocaleString("ko-KR", { maximumFractionDigits: 2 })}원`;
const ratio = (count: number, total: number) => total ? `${(count / total * 100).toFixed(1)}%` : "—";

function PriceLine({ snapshot }: { snapshot: ChartSignalDetail }) {
  const history = snapshot.prices.history;
  if (history.length < 2) return <p className="text-sm text-muted">최근 확정 일봉이 2건 미만이라 가격 흐름을 그릴 수 없어요.</p>;
  const prices = history.map(({ close }) => close);
  const low = Math.min(...prices);
  const high = Math.max(...prices);
  const span = high - low || 1;
  const points = prices.map((price, index) => `${(index / (prices.length - 1) * 100).toFixed(2)},${(100 - (price - low) / span * 100).toFixed(2)}`).join(" ");
  return (
    <div>
      <svg viewBox="0 0 100 100" preserveAspectRatio="none" role="img" className="h-40 w-full" aria-label={`최근 ${history.length}개 거래일 수정종가. ${date(history[0].date)} ${money(prices[0])}부터 ${date(history.at(-1)!.date)} ${money(prices.at(-1)!)}까지`}>
        <polyline points={points} fill="none" stroke="var(--color-muted)" strokeWidth="1.2" vectorEffect="non-scaling-stroke" />
      </svg>
      <p className="m-0 flex justify-between text-xs text-muted tabular-nums"><span>{date(history[0].date)}</span><span>{date(history.at(-1)!.date)}</span></p>
    </div>
  );
}

function CaseResults({ snapshot }: { snapshot: ChartSignalDetailV1 }) {
  const { cases } = snapshot;
  const period = cases.period_start && cases.period_end ? `${date(cases.period_start)}~${date(cases.period_end)}` : "2019~2025 참조 원장";
  return (
    <section aria-labelledby="cases-title" className="surface p-6">
      <span className="eyebrow">과거 같은 종목의 비슷한 신호</span>
      <h2 id="cases-title" className="mt-1 text-xl font-semibold">상방·하방 기준을 충족한 사례</h2>
      {cases.status === "unavailable" ? (
        <p role="status" className="text-sm text-body">과거 사례를 제공할 수 없어요. {cases.reason}</p>
      ) : cases.status === "no_cases" ? (
        <div role="status" className="text-sm text-body"><p>해당 조건의 과거 사례 없음</p><p>상방 기준 충족 0/0건 · —</p><p>하방 기준 충족 0/0건 · —</p><p>양쪽 충족 0건은 위 두 항목에 중복 포함돼요.</p></div>
      ) : (
        <>
          <p className="text-sm text-muted">{period} 예측 중 관측을 마친 {cases.sample_count}건</p>
          <dl className="grid gap-4 sm:grid-cols-2">
            <div className="rounded-md bg-field p-4"><dt className="text-sm text-body">상방 기준 충족</dt><dd className="m-0 text-xl font-semibold tabular-nums">{cases.up_count}/{cases.sample_count}건 · {ratio(cases.up_count, cases.sample_count)}</dd></div>
            <div className="rounded-md bg-field p-4"><dt className="text-sm text-body">하방 기준 충족</dt><dd className="m-0 text-xl font-semibold tabular-nums">{cases.down_count}/{cases.sample_count}건 · {ratio(cases.down_count, cases.sample_count)}</dd></div>
          </dl>
          <p className="text-sm text-body">양쪽 기준을 모두 충족한 {cases.both_count}건은 위 두 항목에 각각 포함돼요. 둘 다 충족하지 않은 사례는 {cases.neither_count}건이에요.</p>
        </>
      )}
      <p className="text-xs text-muted">출처 · 2019~2025 당시 모델의 종목별 과거 예측 · 관측 완료 기준 {date(cases.observed_through)} · 사례 원장 {snapshot.sources.cases_sha256?.slice(0, 12) ?? "확인 불가"}</p>
      <details className="disclosure mt-3 text-sm text-body"><summary>비슷한 신호와 집계 기준</summary>
        <p>같은 종목·기간·학습 정책에서 당시 모델의 상방 출력 차이 ≤ {cases.tolerances.up_absolute}, 하방 출력 차이 ≤ {cases.tolerances.down_absolute}, 흔들림 지표 차이 ≤ 현재 값의 {cases.tolerances.sigma_relative * 100}%인 사례만 세었어요. 비교 전 반올림하지 않아요.</p>
        <p>상방은 다음 거래 세션부터 {snapshot.horizon}개 거래 세션 중 고가가 상방 기준 이상, 하방은 종가가 하방 기준 이하인 경우예요. 먼저 한쪽에 닿아도 다른 쪽을 계속 관측해요. 관측 미완료 사례는 제외해요.</p>
        <p>연속된 관측 기간은 서로 겹칠 수 있고, 연도별 당시 모델의 출력은 서로 다른 모델에서 나왔어요. 이 건수는 모델의 적중이나 미래 결과를 뜻하지 않아요.</p>
        {Object.keys(cases.by_year).length > 0 && <p>연도별 사례 · {Object.entries(cases.by_year).map(([year, count]) => `${year}년 ${count}건`).join(" · ")}</p>}
      </details>
    </section>
  );
}

function HistoricalDistribution({ snapshot }: { snapshot: ChartSignalDetailV2 }) {
  const { distribution } = snapshot;
  const { current, tolerances, histogram } = distribution;
  const period = distribution.period_start && distribution.period_end
    ? `${date(distribution.period_start)}~${date(distribution.period_end)}` : "기간 정보 없음";
  const scoreRange = current && `${Math.max(0, current.up - tolerances.up_absolute).toFixed(3)}~${Math.min(1, current.up + tolerances.up_absolute).toFixed(3)}`;
  const sigmaRange = current && `${(current.sigma * (1 - tolerances.sigma_relative)).toFixed(4)}~${(current.sigma * (1 + tolerances.sigma_relative)).toFixed(4)}`;
  const bins = histogram.bins.map(({ left, right, count }) => ({ from: left, to: right, count }));
  return <section aria-labelledby="distribution-title" className="surface p-6">
    <span className="eyebrow">비슷한 신호·변동성 구간의 과거 사례</span>
    <h2 id="distribution-title" className="mt-1 text-xl font-semibold">{label[snapshot.horizon]} 뒤 실제 수익률 분포</h2>
    {distribution.status === "unavailable" ? <p role="status" className="text-sm text-body">과거 사례를 조회할 수 없어요. {distribution.reason}</p> :
      distribution.status === "no_cases" ? <p role="status" className="text-sm text-body">같은 기간의 점수·흔들림 조건에 맞고 결과가 확인된 과거 사례가 0건이에요.</p> :
      histogram.central_68 && bins.length > 0 ? <>
        <p className="text-sm text-body tabular-nums">{period} 예측 중 관측을 마친 {distribution.sample_count}건 · 포함 종목 {distribution.stock_count}개</p>
        {distribution.sample_count === 1 && <p className="text-sm text-body">표본 1건의 결과예요. 표시된 범위도 이 한 건의 수익률과 같아요.</p>}
        <ReturnHistogram bins={bins} band={{ ...histogram.central_68, ciLevel: 0.68 }} caseCount={distribution.sample_count}
          signal={{ label: "과거 사례", ink: "var(--color-muted)", tint: "var(--color-field)", solid: "var(--color-muted)" }} horizonLabel={`${snapshot.horizon}거래일 뒤`} />
        <details className="disclosure mt-3 text-sm text-body"><summary>구간별 건수 보기</summary>
          <ul className="list-none p-0 tabular-nums">{bins.map((bin, index) => <li key={index}>{bin.from.toFixed(1)}%~{bin.to.toFixed(1)}% · {bin.count}건</li>)}</ul>
        </details>
      </> : <p role="status" className="text-sm text-body">분포 자료가 완전하지 않아 표시할 수 없어요.</p>}
    <p className="text-sm text-body tabular-nums">비교 범위 · 상방 점수 {scoreRange ?? "—"} · 흔들림 지표 {sigmaRange ?? "—"}</p>
    <p className="text-xs text-muted">출처 · 2019~2025 당시 모델의 여러 종목 예측 · 관측 완료 기준 {date(distribution.observed_through)} · 사례 원장 {snapshot.sources.cases_sha256?.slice(0, 12) ?? "확인 불가"}</p>
    <details className="disclosure mt-3 text-sm text-body"><summary>표본 선택과 수익률 계산</summary>
      <p>같은 기간·학습 정책에서 당시 상방 점수 차이 ≤ {tolerances.up_absolute}, 흔들림 지표 차이 ≤ 현재 값의 {tolerances.sigma_relative * 100}%인 사례를 골랐어요. 비교 전 반올림하지 않고 경계값도 포함해요.</p>
      <p>실제 수익률은 예측일 수정종가와 {snapshot.horizon}거래일 뒤 수정종가를 비교해 계산했어요. 과거 표본의 중앙 68% 범위는 선택된 사례의 16·84백분위예요. 미래 결과를 보장하지 않아요.</p>
      {Object.keys(distribution.by_fold).length > 0 && <p>학습 구간별 사례 · {Object.entries(distribution.by_fold).map(([fold, count]) => `${fold} ${count}건`).join(" · ")}</p>}
    </details>
  </section>;
}

function Features({ snapshot }: { snapshot: ChartSignalDetail }) {
  const features = snapshot.inference.features;
  if (snapshot.inference.status !== "available" || !features.length) return null;
  const item = (feature: typeof features[number]) => (
    <li key={feature.name} className="py-3">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <span className="font-medium">{feature.label_ko}</span>
        <span className="tabular-nums" style={{ color: feature.contribution > 0 ? "var(--color-up)" : feature.contribution < 0 ? "var(--color-down)" : "var(--color-muted)" }}>
          {feature.contribution > 0 ? "+" : ""}{feature.contribution.toFixed(4)} · {feature.contribution > 0 ? "상방 첫 충족 점수 높임" : feature.contribution < 0 ? "상방 첫 충족 점수 낮춤" : "중립 기여"}
        </span>
      </div>
      <p className="m-0 text-xs text-muted">{feature.meaning_ko} · 입력값 {feature.value === null ? "결측" : feature.value.toLocaleString("ko-KR")}</p>
    </li>
  );
  return <section aria-labelledby="features-title" className="surface p-6"><span className="eyebrow">이번 예측의 근거</span><h2 id="features-title" className="mt-1 text-xl font-semibold">상방 첫 충족 점수에 기여한 항목</h2>
    <p className="text-sm text-body">필요성 · 모델 출력만으로는 어떤 가격·거래량 입력이 작용했는지 알기 어려워요. 기대 역할 · 아래 항목에서 이번 계산의 방향과 입력값을 확인할 수 있어요.</p>
    <ol className="m-0 list-none divide-y divide-line-soft p-0 text-sm">{features.slice(0, 3).map(item)}</ol>
    {features.length > 3 && <details className="disclosure"><summary>근거 {features.length - 3}개 더 보기</summary><ol className="m-0 list-none divide-y divide-line-soft p-0 text-sm">{features.slice(3).map(item)}</ol></details>}
    <p className="text-xs text-muted">출처 · 모델 {snapshot.sources.model_sha256?.slice(0, 12) ?? "확인 불가"} · 피처 {snapshot.sources.features_sha256?.slice(0, 12) ?? "확인 불가"}. 부호가 있는 값은 모델 내부 원점수 기여도예요. 확률·수익률 변화량은 아니에요.</p>
  </section>;
}

export default function RealChartDetail({ data }: { data: PublishedChartDetail }) {
  const [horizon, setHorizon] = useState<5 | 20>(data.initialHorizon);
  const snapshot = data.snapshots[horizon];
  const stale = data.stale[horizon];
  return <div className="w-full"><header className="border-b border-line-soft bg-white"><div className="mx-auto flex max-w-[960px] items-center px-4 py-4 sm:px-8"><Link href="/" className="text-lg font-semibold text-brand">Take a Look</Link></div></header>
    <main className="mx-auto box-border flex w-full max-w-[960px] flex-col gap-6 px-4 pb-12 pt-5 sm:px-8">
      <Link href="/" className="btn-text self-start text-xs">‹ 대시보드</Link>
      <div><span className="eyebrow">{snapshot?.stock_code ?? ""} · KOSPI</span><h1 className="text-3xl font-semibold">{data.name}</h1><p className="text-sm text-body">이 종목의 확정 일봉과 비슷한 신호의 과거 결과를 확인해요.</p></div>
      <div className="segmented self-start" role="tablist" aria-label="예측 기간">{([5, 20] as const).map((value) => <button key={value} type="button" role="tab" aria-selected={horizon === value} onClick={() => setHorizon(value)}>{label[value]}</button>)}</div>
      {!snapshot ? <p role="status" className="surface p-6 text-sm">선택한 기간의 공개 데이터가 없어요.</p> : <>
        <p className="m-0 text-sm text-muted tabular-nums" role="status">연구 데모 · 실제 데이터 기준일 {date(snapshot.data_asof)} · {stale ? "기준일이 오래됐어요. 최근 자료 확인이 필요해요." : "확정 일봉"} · {snapshot.contract === "chart_signal_detail_v2" ? `모델 묶음 ${snapshot.pack_id}` : `배치 ${snapshot.batch_id}`}</p>
        <section aria-labelledby="price-title" className="surface p-6"><span className="eyebrow">확정 가격</span><h2 id="price-title" className="mt-1 text-xl font-semibold">최근 {snapshot.prices.history.length}개 거래일 수정종가</h2>
          {snapshot.inference.close !== null && <p className="text-lg font-semibold tabular-nums">기준일 종가 {money(snapshot.inference.close)}</p>}
          <PriceLine snapshot={snapshot} />
          <p className="text-xs text-muted">출처 · {snapshot.prices.source} · {date(snapshot.data_asof)} · 수정종가 · 가격 자료 {snapshot.sources.prices_sha256?.slice(0, 12) ?? "확인 불가"}</p>
        </section>
        <section aria-labelledby="model-title" className="surface p-6"><span className="eyebrow">모델의 한 가지 근거</span><h2 id="model-title" className="mt-1 text-xl font-semibold">상방 기준을 먼저 충족하는 사건의 모델 출력</h2>
          {snapshot.inference.status === "available" && snapshot.inference.scores && snapshot.inference.barriers ? <>
            <p className="text-sm text-body tabular-nums">상방 첫 충족 출력 {(snapshot.inference.scores.up * 100).toFixed(1)}% · 하방 첫 충족 출력 {(snapshot.inference.scores.down * 100).toFixed(1)}% · 중립 출력 {(snapshot.inference.scores.neutral * 100).toFixed(1)}%</p>
            <p className="text-sm text-body tabular-nums">{label[horizon]} 관측 기준 · 상방 {money(snapshot.inference.barriers.up)} · 하방 {money(snapshot.inference.barriers.down)}</p>
            <p className="text-xs text-muted">모델 출력은 과거 학습으로 계산한 분류 점수예요. 미래 가격이나 실제 충족 비율을 뜻하지 않아요.</p>
          </> : <p role="status" className="text-sm text-body">이번 예측을 제공할 수 없어요. {snapshot.inference.reason}</p>}
          <p className="text-xs text-muted">출처 · release {snapshot.release_id} · 모델 {snapshot.sources.model_sha256?.slice(0, 12) ?? "확인 불가"} · {date(snapshot.data_asof)}</p>
        </section>
        {snapshot.contract === "chart_signal_detail_v2" ? <HistoricalDistribution snapshot={snapshot} /> : <CaseResults snapshot={snapshot} />}
        <Features snapshot={snapshot} />
      </>}
    </main><DisclaimerFooter fixed={false} /></div>;
}
