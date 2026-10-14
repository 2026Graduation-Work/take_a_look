"use client";

// 모델 성적표: 연구용 화면이라 도메인 용어를 쓰되, 같은 수치는 한 번만 보인다.
// 성향·표본을 고르면 표 하나(A | B | Δ)가 바뀐다. 0~1 막대는 0.01 차이를 못 보여 줘서 두지 않는다.

import { useState } from "react";
import DisclaimerFooter from "./disclaimer-footer";
import SiteHeader from "./site-header";
import {
  METRICS,
  PROFILE_LABEL,
  deltaOutcome,
  formatDeltaValue,
  formatMetricValue,
  type DeltaOutcome,
  type MetricDefinition,
} from "@/lib/performance-display";
import type { ComparisonProfile, ComparisonResults, ComparisonSample } from "@/lib/performance-types";
import type { InvestorProfileSummary, MarketStatus } from "@/lib/types";

interface PerformanceDashboardProps {
  data: ComparisonResults;
  isSample: boolean;
  conclusion: string;
  profile: InvestorProfileSummary;
  marketStatus: MarketStatus;
}

const SAMPLE_LABEL: Record<ComparisonSample, string> = {
  all: "전체 테스트 구간",
  volatile_top_20pct: "고변동일 상위 20%",
};
const HORIZON: Record<ComparisonProfile, string> = { stable: "20거래일", aggressive: "5거래일" };

const GROUPS: { title: string; keys: MetricDefinition["key"][] }[] = [
  { title: "분류 성능", keys: ["auc", "hit_rate"] },
  { title: "확률 보정", keys: ["calibration_brier", "calibration_ece"] },
  { title: "백테스트", keys: ["sharpe", "mdd", "cumulative_return", "trade_count"] },
];

// 좋아졌는지는 색이 아니라 단어가 말한다(가격 방향색 적·청과 섞이지 않게).
const OUTCOME_WORD: Record<DeltaOutcome, string> = {
  improved: "개선",
  worsened: "저하",
  unchanged: "동일",
  neutral: "",
  unavailable: "미산출",
};

const DESIGN: [string, string][] = [
  ["모델", "LightGBM 다중 분류(하락·중립·상승), 네 런 모두 같은 하이퍼파라미터"],
  ["라벨", "동적 σ 배리어 — 안정형 20거래일, 공격형 5거래일 안에 위·아래 배리어 중 어느 쪽에 먼저 닿는지"],
  ["A (기준)", "가격·거래량 161개 + 수급 9개, 총 170개 입력"],
  ["B (처치)", "A + 시장 심리 4개, 총 174개 입력. 뉴스 감성과 개인 설문 점수는 포함하지 않음"],
  ["통제", "같은 종목 유니버스 · 같은 기간 분할 · 같은 시드 · 같은 평가 함수. 바뀌는 것은 피처 묶음뿐"],
  ["고변동일", "일별 시장 변동성 상위 20% 날짜만 다시 평가"],
];

export default function PerformanceDashboard({
  data,
  isSample,
  conclusion,
  profile,
  marketStatus,
}: PerformanceDashboardProps) {
  const [runProfile, setRunProfile] = useState<ComparisonProfile>("stable");
  const [sample, setSample] = useState<ComparisonSample>("all");

  const rows = sample === "all" ? data.four_run_metrics : data.volatile_subsample_metrics;
  const a = rows.find((row) => row.profile === runProfile && row.variant === "A");
  const b = rows.find((row) => row.profile === runProfile && row.variant === "B");
  const delta = data.comparison_deltas.find((row) => row.profile === runProfile && row.sample === sample);

  return (
    <div className="min-h-screen w-full">
      <SiteHeader profile={profile} marketStatus={marketStatus} activePage="performance" />

      <main className="mx-auto box-border flex w-full max-w-[960px] flex-col gap-8 px-4 pb-12 pt-8 sm:px-8">
        <section aria-labelledby="scorecard-title" className="flex flex-col gap-2 px-1">
          <span className="eyebrow">모델 성적표 · 비교 실험</span>
          <h1 id="scorecard-title" className="text-3xl font-semibold">
            심리 피처를 더하면 예측이 나아지나요?
          </h1>
          <p className="m-0 max-w-2xl text-sm text-body">
            운영 모델과 같은 입력 구성의 A와 시장 심리 피처를 더한 B를 비교했어요. 과거 연도별로 따로 학습한 연구 결과이며, 현재 운영 모델 자체의 성적은 아니에요.
          </p>
          {isSample && (
            <p role="note" className="m-0 mt-2 rounded-md bg-field px-4 py-3 text-sm text-body">
              <strong className="font-semibold text-ink">예시 데이터</strong> · {conclusion}
            </p>
          )}
          {!isSample && <p className="m-0 max-w-2xl text-sm text-ink">{conclusion}</p>}
          {data.experiment && <>
            <p className="m-0 text-xs text-muted tabular-nums">{data.experiment.start}~{data.experiment.end} · {data.experiment.years.length}개 평가 연도 · 각 연도 직전 3년 학습</p>
            <p className="m-0 max-w-2xl text-xs text-body">{data.experiment.limitations}</p>
          </>}
        </section>

        <section aria-labelledby="compare-title" className="flex flex-col gap-3">
          <h2 id="compare-title" className="px-1 text-xl font-semibold">
            A · B 지표 비교
          </h2>
          <div className="flex flex-col gap-2 sm:flex-row">
            <Segmented
              label="성향"
              value={runProfile}
              options={(["stable", "aggressive"] as const).map((id) => [id, `${PROFILE_LABEL[id]} · ${HORIZON[id]}`])}
              onChange={setRunProfile}
            />
            <Segmented
              label="표본"
              value={sample}
              options={(["all", "volatile_top_20pct"] as const).map((id) => [id, SAMPLE_LABEL[id]])}
              onChange={setSample}
            />
          </div>

          <div className="surface overflow-x-auto">
            <table className="w-full min-w-[340px] border-collapse text-sm tabular-nums">
              <thead>
                <tr className="text-xs text-muted">
                  <th className="px-4 py-3 text-left font-medium">지표</th>
                  <th className="px-3 py-3 text-right font-medium">
                    A<span className="block text-2xs font-normal">피처 {a?.feature_count ?? "-"}개</span>
                  </th>
                  <th className="px-3 py-3 text-right font-medium">
                    B<span className="block text-2xs font-normal">피처 {b?.feature_count ?? "-"}개</span>
                  </th>
                  <th className="px-4 py-3 text-right font-medium">B − A</th>
                </tr>
              </thead>
              {GROUPS.map((group) => (
                <tbody key={group.title}>
                  <tr className="border-t border-line">
                    <th colSpan={4} className="bg-field px-4 py-2 text-left text-xs font-semibold text-body">
                      {group.title}
                    </th>
                  </tr>
                  {group.keys.map((key) => {
                    const metric = METRICS.find((candidate) => candidate.key === key)!;
                    const value = delta?.[metric.deltaKey] ?? null;
                    const outcome = deltaOutcome(value, metric);
                    return (
                      <tr key={key} className="border-t border-line-soft">
                        <th className="px-4 py-3 text-left font-medium text-ink">
                          {metric.label}
                          <span className="block text-2xs font-normal text-muted">
                            {metric.direction === "higher" ? "↑ 높을수록 좋음" : metric.direction === "lower" ? "↓ 낮을수록 좋음" : "참고"}
                          </span>
                        </th>
                        <td className="px-3 py-3 text-right text-body">{a ? formatMetricValue(a[key], metric) : "-"}</td>
                        <td className="px-3 py-3 text-right font-medium text-ink">{b ? formatMetricValue(b[key], metric) : "-"}</td>
                        <td className={`px-4 py-3 text-right ${outcome === "improved" ? "font-semibold text-ink" : "text-muted"}`}>
                          {formatDeltaValue(value, metric)}
                          {OUTCOME_WORD[outcome] && <span className="block text-2xs font-normal">{OUTCOME_WORD[outcome]}</span>}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              ))}
            </table>
          </div>
          <p className="m-0 px-1 text-xs text-muted sm:hidden">표를 좌우로 밀면 B−A 차이를 볼 수 있어요.</p>
          {b && (
            <p className="m-0 px-1 text-xs text-muted tabular-nums">
              {SAMPLE_LABEL[sample]} · 관측치 {b.sample_rows.toLocaleString("ko-KR")}건 · 거래일 {b.sample_dates.toLocaleString("ko-KR")}일 · 상승 라벨 비율{" "}
              {(b.positive_rate * 100).toFixed(1)}%
            </p>
          )}
          {data.experiment && <p className="m-0 px-1 text-xs text-muted">
            지표는 연도별 단순평균, 관측치·거래일·거래 수는 합계입니다. 상승 라벨 비율도 연도별 평균입니다.
            {sample !== "all" && " 고변동일은 분류·보정 지표만 다시 평가하며 별도 백테스트는 미산출입니다."}
          </p>}
        </section>

        <section aria-labelledby="design-title" className="flex flex-col gap-3">
          <h2 id="design-title" className="px-1 text-xl font-semibold">
            실험 설계
          </h2>
          <Definitions items={data.experiment ? [...DESIGN.filter(([term]) => term !== "고변동일"),
            ["고변동일", data.experiment.volatile_definition], ["체결 기준", "상승 점수 0.65 이상 · 일별 신규 후보 최대 5개 · 다음 거래일 시가 · 매수·매도 각각 비용 0.105%"],
            ["집계", data.experiment.backtest_scope], ["출처", data.experiment.source]] : DESIGN} />
        </section>

        <section aria-labelledby="metrics-title" className="flex flex-col gap-3">
          <h2 id="metrics-title" className="px-1 text-xl font-semibold">
            지표 정의
          </h2>
          <Definitions
            items={METRICS.filter((metric) => metric.description).map((metric) => [metric.label, metric.description!])}
          />
        </section>
      </main>

      <DisclaimerFooter fixed={false} />
    </div>
  );
}

function Segmented<T extends string>({
  label,
  value,
  options,
  onChange,
}: {
  label: string;
  value: T;
  options: [T, string][];
  onChange: (value: T) => void;
}) {
  return (
    <div role="tablist" aria-label={label} className="segmented grid flex-1 grid-cols-2">
      {options.map(([id, text]) => (
        <button key={id} type="button" role="tab" aria-selected={value === id} onClick={() => onChange(id)}>
          {text}
        </button>
      ))}
    </div>
  );
}

function Definitions({ items }: { items: [string, string][] }) {
  return (
    <dl className="surface m-0 grid grid-cols-1 gap-x-6 px-5 py-2 sm:grid-cols-[120px_1fr]">
      {items.map(([term, description]) => (
        <div key={term} className="contents">
          <dt className="pt-3 text-sm font-medium text-ink sm:pb-3">{term}</dt>
          <dd className="m-0 border-b border-line-soft pb-3 text-sm text-body last:border-0 sm:pt-3">{description}</dd>
        </div>
      ))}
    </dl>
  );
}
