"use client";

import {
  Bar,
  BarChart,
  LabelList,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import DisclaimerFooter from "./disclaimer-footer";
import SiteHeader from "./site-header";
import {
  METRICS,
  ML_METRICS,
  PROFILE_LABEL,
  TRADING_METRICS,
  deltaOutcome,
  formatDeltaValue,
  formatMetricValue,
  type DeltaOutcome,
  type MetricDefinition,
} from "@/lib/performance-display";
import { CHART } from "@/lib/chart-colors";
import type {
  ComparisonDeltaRow,
  ComparisonMetricRow,
  ComparisonProfile,
  ComparisonResults,
  ComparisonSample,
} from "@/lib/performance-types";
import type { InvestorProfileSummary, MarketStatus } from "@/lib/types";

interface PerformanceDashboardProps {
  data: ComparisonResults;
  isSample: boolean;
  conclusion: string;
  profile: InvestorProfileSummary;
  marketStatus: MarketStatus;
}

const CONTROL_CONDITIONS = [
  "동일 유니버스",
  "동일 기간",
  "동일 시드",
  "공용 평가함수",
];

// 개선·저하는 색이 아니라 ▲▼(값이 커졌나 작아졌나)와 단어로 읽힌다.
// 가격 방향색(적·청)과 섞이지 않게 무채색으로 두고, 좋아졌는지는 단어가 말한다(Brier는 ▼ 개선).
const OUTCOME_STYLE: Record<DeltaOutcome, { text: string; label: string }> = {
  improved: { text: "text-ink", label: "개선" },
  worsened: { text: "text-ink", label: "저하" },
  unchanged: { text: "text-muted", label: "동일" },
  neutral: { text: "text-muted", label: "증감" },
  unavailable: { text: "text-muted", label: "미산출" },
};

const deltaMark = (value: number | null) => (value === null || value === 0 ? "" : value > 0 ? "▲" : "▼");

// A/B 두 막대만 명암으로 나누고, 안정형·공격형은 차트를 따로 그려 위치로 구분한다.
const VARIANT_FILL = { A: CHART.line, B: CHART.priceLine } as const;

export default function PerformanceDashboard({
  data,
  isSample,
  conclusion,
  profile,
  marketStatus,
}: PerformanceDashboardProps) {
  const headline = findMetricRow(data.four_run_metrics, "stable", "B");
  const auc = headline?.auc ?? null;
  const allDeltas = data.comparison_deltas.filter(({ sample }) => sample === "all");

  return (
    <div className="min-h-screen w-full">
      <SiteHeader profile={profile} marketStatus={marketStatus} activePage="performance" />

      <main className="mx-auto box-border flex w-full max-w-[960px] flex-col gap-8 px-4 pb-12 pt-8 sm:px-8">
        <section aria-labelledby="scorecard-title" className="flex flex-col gap-1.5 px-1">
          <span className="eyebrow">모델 성적표 · 안정형 모델 B(심리 지표 포함) 기준</span>
          <h1 id="scorecard-title" className="text-3xl font-semibold tabular-nums">
            판별력(AUC) {auc === null ? "미산출" : auc.toFixed(2)} · 0.5는 동전 던지기 수준
          </h1>
          <p className="m-0 max-w-2xl text-sm text-body">
            A는 가격 지표만, B는 같은 지표에 가격·거래량 심리 지표와 뉴스 분위기를 더한 모델이에요. 바뀌는 조건은 지표 묶음뿐이에요.
          </p>
          {isSample && <p className="m-0 text-xs text-muted">예시 데이터 · 실제 실험 결과가 들어오면 바뀌어요</p>}
        </section>

        <section aria-labelledby="ab-summary-title" className="flex flex-col gap-3">
          <h2 id="ab-summary-title" className="px-1 text-xl font-semibold">
            심리 지표를 더하면 나아지나요?
          </h2>
          <div className="surface overflow-x-auto">
            <table className="w-full min-w-[520px] border-collapse text-left">
              <thead>
                <tr className="text-xs text-muted">
                  <th className="px-5 py-3 font-medium">지표</th>
                  <th className="px-3 py-3 font-medium">안정형 A → B</th>
                  <th className="px-3 py-3 font-medium">공격형 A → B</th>
                </tr>
              </thead>
              <tbody>
                {METRICS.filter(({ direction }) => direction !== "neutral").map((metric) => (
                  <tr key={metric.key} className="border-t border-line-soft">
                    <th className="px-5 py-3 text-sm font-medium text-ink">
                      {metric.label}
                      <span className="block text-2xs font-normal text-muted">
                        {metric.direction === "higher" ? "클수록 좋아요" : "작을수록 좋아요"}
                      </span>
                    </th>
                    {(["stable", "aggressive"] as const).map((comparisonProfile) => (
                      <PairCell
                        key={comparisonProfile}
                        metric={metric}
                        profile={comparisonProfile}
                        sample="all"
                        rows={data.four_run_metrics}
                        deltas={allDeltas}
                      />
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="m-0 px-1 text-2xs text-muted">같은 종목·기간·시드·평가 함수로 비교했어요 · 테스트 기간 전체</p>
        </section>

        <details className="disclosure surface p-6">
          <summary>
            <span className="flex flex-col gap-0.5">
              <span className="text-lg font-semibold">자세히 보기</span>
              <span className="text-xs text-muted">연구 결론 · 4런 전체 표 · 시장이 크게 흔들린 날만 따로 본 결과</span>
            </span>
          </summary>
          <div className="mt-6 flex flex-col gap-8">
            <section aria-labelledby="conclusion-title" className="flex flex-col gap-2">
              <h3 id="conclusion-title" className="text-base font-semibold">
                연구 결론 <span className="text-xs font-normal text-muted">{isSample ? "실제 결과 반영 전" : "실험 결과 반영"}</span>
              </h3>
              <p className="m-0 text-sm leading-6 text-body">{conclusion}</p>
              <p className="m-0 flex flex-wrap gap-2">
                {CONTROL_CONDITIONS.map((condition) => (
                  <span key={condition} className="text-xs text-muted">
                    {condition}
                  </span>
                ))}
              </p>
            </section>
            <section aria-labelledby="four-run-title" className="flex flex-col gap-3">
              <SectionHeading id="four-run-title" title="4런 전체 구간 비교" description="안정형·공격형 각각 A/B를 같은 표본에서 평가" />
              <div className="overflow-x-auto rounded-md bg-field">
                <FourRunTable rows={data.four_run_metrics} deltas={allDeltas} />
              </div>
            </section>
            <section aria-labelledby="subsample-title" className="flex flex-col gap-3">
              <SectionHeading
                id="subsample-title"
                title="시장이 크게 흔들린 날만 따로 보기"
                description="일별 시장 변동성 상위 20% 날짜"
              />
              <div className="grid grid-cols-1 gap-4">
                <SamplePanel
                  title="전체 구간에서의 A vs B"
                  subtitle="테스트 기간의 모든 관측치"
                  sample="all"
                  rows={data.four_run_metrics}
                  deltas={data.comparison_deltas}
                />
                <SamplePanel
                  title="흔들린 날에서의 A vs B"
                  subtitle="일별 시장 변동성 상위 20%"
                  sample="volatile_top_20pct"
                  rows={data.volatile_subsample_metrics}
                  deltas={data.comparison_deltas}
                />
              </div>
            </section>
          </div>
        </details>
      </main>

      <DisclaimerFooter fixed={false} />
    </div>
  );
}

function SectionHeading({ id, title, description }: { id: string; title: string; description: string }) {
  return (
    <div className="flex flex-col gap-0.5">
      <h3 id={id} className="text-base font-semibold">
        {title}
      </h3>
      <span className="text-xs text-muted">{description}</span>
    </div>
  );
}

// 지표 설명은 "?" 동그라미 대신 표 머리글의 title(마우스 올리면 보임)로 둔다.
function MetricInfoBadge({ description }: { description?: string }) {
  if (!description) return null;
  return <span className="sr-only">{description}</span>;
}

function FourRunTable({
  rows,
  deltas,
}: {
  rows: ComparisonMetricRow[];
  deltas: ComparisonDeltaRow[];
}) {
  return (
    <table className="min-w-[940px] w-full table-fixed border-collapse text-left">
      <thead>
        <tr className="border-b border-line bg-field text-2xs font-medium text-muted">
          <th rowSpan={2} className="w-[160px] border-r border-line px-4 py-3">
            실험 런
          </th>
          <th colSpan={ML_METRICS.length} className="border-r border-line px-3 py-2 text-center">
            ML 지표
          </th>
          <th colSpan={TRADING_METRICS.length} className="px-3 py-2 text-center">
            Trading 지표
          </th>
        </tr>
        <tr className="border-b border-line bg-field text-2xs font-medium text-body">
          {METRICS.map((metric, index) => (
            <th
              key={metric.key}
              className={`px-2 py-2.5 text-right ${
                index === ML_METRICS.length - 1 ? "border-r border-line" : ""
              }`}
            >
              <span className="inline-flex items-center justify-end gap-1">
                {metric.label}
                <MetricInfoBadge description={metric.description} />
              </span>
            </th>
          ))}
        </tr>
      </thead>
      <tbody>
        {rows.map((row, rowIndex) => {
          const delta = deltas.find(({ profile }) => profile === row.profile);
          const startsProfile = rowIndex > 0 && rows[rowIndex - 1]?.profile !== row.profile;
          return (
            <tr
              key={`${row.profile}-${row.variant}`}
              className={`${startsProfile ? "border-t-2 border-edge" : "border-t border-line-soft"}`}
            >
              <th className="border-r border-line px-4 py-3.5">
                <div className="flex items-center gap-2">
                  <span className="font-semibold">{PROFILE_LABEL[row.profile]}</span>
                  <span
                    className={`grid size-6 place-items-center rounded-md text-2xs font-semibold ${
                      row.variant === "B"
                        ? "bg-ink text-white"
                        : "border border-edge bg-field text-body"
                    }`}
                  >
                    {row.variant}
                  </span>
                </div>
                <div className="mt-1 text-2xs font-medium text-muted">
                  {row.feature_set === "baseline" ? "차트 피처" : "차트 + 심리 피처"} · {row.feature_count}개
                </div>
              </th>
              {METRICS.map((metric, index) => {
                const deltaValue = delta?.[metric.deltaKey] ?? null;
                const outcome = row.variant === "B" ? deltaOutcome(deltaValue, metric) : null;
                return (
                  <td
                    key={metric.key}
                    className={`px-2 py-3 text-right tabular-nums ${
                      index === ML_METRICS.length - 1 ? "border-r border-line" : ""
                    } `}
                  >
                    <div className="text-sm font-medium text-ink">
                      {formatMetricValue(row[metric.key], metric)}
                    </div>
                    {row.variant === "B" && (
                      <div className={`mt-0.5 text-2xs font-medium ${OUTCOME_STYLE[outcome!].text}`}>
                        {deltaMark(deltaValue)} {formatDeltaValue(deltaValue, metric)} · {OUTCOME_STYLE[outcome!].label}
                      </div>
                    )}
                  </td>
                );
              })}
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}

function SamplePanel({
  title,
  subtitle,
  sample,
  rows,
  deltas,
}: {
  title: string;
  subtitle: string;
  sample: ComparisonSample;
  rows: ComparisonMetricRow[];
  deltas: ComparisonDeltaRow[];
}) {
  const chartData = (profile: ComparisonProfile) =>
    ML_METRICS.map((metric) => ({
      metric: metric.shortLabel,
      A: metricValue(rows, profile, "A", metric),
      B: metricValue(rows, profile, "B", metric),
    }));

  return (
    <article className="min-w-0 rounded-md bg-field">
      <div className="px-4 py-3.5">
        <h3 className="text-sm font-semibold">{title}</h3>
        <p className="mt-0.5 text-2xs text-muted">{subtitle}</p>
      </div>

      <div className="grid grid-cols-1 gap-2 px-3 pb-1 pt-3 sm:grid-cols-2">
        {(["stable", "aggressive"] as const).map((chartProfile) => (
          <div key={chartProfile} className="min-w-0">
            <span className="px-1 text-xs font-medium text-body">
              {PROFILE_LABEL[chartProfile]} · 옅은 막대 A, 진한 막대 B
            </span>
            <div className="mt-1 h-[200px] min-w-0">
              <ResponsiveContainer
                width="100%"
                height="100%"
                minWidth={1}
                minHeight={1}
                initialDimension={{ width: 280, height: 200 }}
              >
                <BarChart data={chartData(chartProfile)} margin={{ top: 16, right: 4, left: -18, bottom: 0 }}>
                  <XAxis
                    dataKey="metric"
                    tick={{ fill: CHART.muted, fontSize: 11 }}
                    axisLine={{ stroke: CHART.edge }}
                    tickLine={false}
                  />
                  <YAxis domain={[0, 1]} ticks={[0, 0.5, 1]} tick={{ fill: CHART.muted, fontSize: 11 }} axisLine={false} tickLine={false} width={34} />
                  <Tooltip
                    cursor={{ fill: CHART.page }}
                    contentStyle={{ border: `1px solid ${CHART.line}`, borderRadius: 8, fontSize: 12 }}
                    formatter={(value) => Number(value).toFixed(3)}
                  />
                  {(["A", "B"] as const).map((variant) => (
                    <Bar key={variant} dataKey={variant} name={variant} fill={VARIANT_FILL[variant]} maxBarSize={16} isAnimationActive={false}>
                      <LabelList dataKey={variant} position="top" formatter={() => variant} style={{ fill: CHART.muted, fontSize: 11 }} />
                    </Bar>
                  ))}
                </BarChart>
              </ResponsiveContainer>
            </div>
          </div>
        ))}
      </div>

      <div className="overflow-x-auto border-t border-line">
        <table className="w-full min-w-[440px] table-fixed border-collapse">
          <thead>
            <tr className="bg-field text-2xs font-medium text-muted">
              <th className="w-[92px] px-3 py-2 text-left">지표</th>
              <th className="px-2 py-2 text-left">안정형 A → B</th>
              <th className="px-2 py-2 text-left">공격형 A → B</th>
            </tr>
          </thead>
          <tbody>
            {METRICS.map((metric) => (
              <tr key={metric.key} className="border-t border-line-soft">
                <th className="px-3 py-2 text-left text-2xs font-medium text-body">
                  <span className="inline-flex items-center gap-1">
                    {metric.shortLabel}
                    <MetricInfoBadge description={metric.description} />
                  </span>
                </th>
                {(["stable", "aggressive"] as const).map((comparisonProfile) => (
                  <PairCell
                    key={comparisonProfile}
                    metric={metric}
                    profile={comparisonProfile}
                    sample={sample}
                    rows={rows}
                    deltas={deltas}
                  />
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </article>
  );
}

function PairCell({
  metric,
  profile,
  sample,
  rows,
  deltas,
}: {
  metric: MetricDefinition;
  profile: ComparisonProfile;
  sample: ComparisonSample;
  rows: ComparisonMetricRow[];
  deltas: ComparisonDeltaRow[];
}) {
  const baseline = findMetricRow(rows, profile, "A");
  const treatment = findMetricRow(rows, profile, "B");
  const delta = deltas.find((row) => row.profile === profile && row.sample === sample);
  const deltaValue = baseline && treatment ? (delta?.[metric.deltaKey] ?? null) : null;
  const outcome = deltaOutcome(deltaValue, metric);
  const style = OUTCOME_STYLE[outcome];
  const baselineValue = baseline?.[metric.key] ?? null;
  const treatmentValue = treatment?.[metric.key] ?? null;

  return (
    <td className="px-2 py-2 tabular-nums">
      <div className="whitespace-nowrap text-xs font-medium text-body">
        A {formatMetricValue(baselineValue, metric)} → B{" "}
        {formatMetricValue(treatmentValue, metric)}
      </div>
      <div className={`mt-0.5 text-xs font-semibold ${style.text}`}>
        {deltaMark(deltaValue)} {formatDeltaValue(deltaValue, metric)} · {style.label}
      </div>
    </td>
  );
}

function metricValue(
  rows: ComparisonMetricRow[],
  profile: ComparisonProfile,
  variant: "A" | "B",
  metric: MetricDefinition,
): number | null {
  return findMetricRow(rows, profile, variant)?.[metric.key] ?? null;
}

function findMetricRow(
  rows: ComparisonMetricRow[],
  profile: ComparisonProfile,
  variant: "A" | "B",
): ComparisonMetricRow | undefined {
  return rows.find((candidate) => candidate.profile === profile && candidate.variant === variant);
}
