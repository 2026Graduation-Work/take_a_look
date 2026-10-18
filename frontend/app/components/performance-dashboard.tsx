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
// 대시보드 기간 전환(앞으로 4주 | 1주)과 같은 말
const HORIZON: Record<ComparisonProfile, string> = { stable: "4주", aggressive: "1주" };

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
  ["모델", "LightGBM 분류 모델이 하락, 중립, 상승 중 하나를 골라요. A와 B는 설정이 같아요."],
  ["정답(라벨)", "안정형은 20거래일(약 4주), 공격형은 5거래일(약 1주) 안에 위아래 기준선 중 어느 쪽에 먼저 닿는지예요."],
  ["A (기준)", "가격과 거래량 지표 161개, 투자자별 매매(수급) 9개로 모두 170개를 넣어요."],
  ["B (비교)", "A에 시장 분위기(심리) 지표 4개를 더해 174개예요. 뉴스 분위기와 설문 점수는 넣지 않았어요."],
  ["같게 둔 것", "종목, 기간 나누기, 무작위 시드, 평가 방법이 모두 같고 바뀐 것은 지표 묶음뿐이에요."],
  ["고변동일", "시장이 크게 흔들린 상위 20% 날만 따로 다시 평가해요."],
];

// 대시보드에 있던 "데이터 출처·기준"을 여기로 모은다(10/18 사용자 피드백). 화면별 기준일은 시장 바·각 카드가 말한다
const SOURCES: [string, string][] = [
  ["시장 지수·흔들림", "KRX 지수(pykrx), 영업일마다"],
  ["모델 신호·종가", "LightGBM 게시 배치(앞으로 4주·1주), 모델 검증 전"],
  ["누가 사고팔았나", "KRX 투자자별 순매수"],
  ["뉴스 분위기", "NewsAPI.ai 기사를 KR-FinBERT로 하루 단위 분석"],
  ["공시·회사 체력", "DART 공시와 정기보고서"],
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

      {/* 머리말·표·정의가 모두 같은 폭(왼쪽·오른쪽 끝이 맞게, 10/18 사용자 피드백) */}
      <main className="mx-auto box-border flex w-full max-w-[800px] flex-col gap-8 px-4 pb-12 pt-8 sm:px-8">
        <section aria-labelledby="scorecard-title" className="flex flex-col gap-2 px-1">
          <span className="eyebrow">모델 성적표</span>
          <h1 id="scorecard-title" className="text-3xl font-semibold">
            시장 분위기 지표를 더하면 예측이 나아질까요?
          </h1>
          <p className="m-0 text-sm text-body">
            A는 지금 운영 모델과 같은 지표로, B는 여기에 시장 분위기(심리) 지표 4개를 더해 학습했어요. 과거 연도마다 따로 학습해 비교한 연구 결과라, 지금 운영 중인 모델의 성적은 아니에요.
          </p>
          {isSample && (
            <p role="note" className="m-0 mt-2 rounded-md bg-field px-4 py-3 text-sm text-body">
              <strong className="font-semibold text-ink">예시 데이터</strong> · {conclusion}
            </p>
          )}
          {!isSample && (
            <p className="m-0 mt-2 rounded-md bg-surface px-4 py-3 text-sm text-ink">
              <strong className="font-semibold">결론</strong> {conclusion}
            </p>
          )}
          {data.experiment && (
            <p className="m-0 text-xs text-muted tabular-nums">
              {data.experiment.start.replaceAll("-", ".")}~{data.experiment.end.replaceAll("-", ".")}, {data.experiment.years.length}개 연도를 해마다 직전 3년 자료로 학습
            </p>
          )}
        </section>

        <section aria-labelledby="compare-title" className="flex flex-col gap-3">
          <h2 id="compare-title" className="px-1 text-xl font-semibold">
            A와 B 비교
          </h2>
          <div className="flex flex-col gap-2 sm:flex-row">
            <Segmented
              label="성향"
              value={runProfile}
              options={(["stable", "aggressive"] as const).map((id) => [id, `${PROFILE_LABEL[id]} ${HORIZON[id]}`])}
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
              {SAMPLE_LABEL[sample]}: 관측치 {b.sample_rows.toLocaleString("ko-KR")}건, 거래일 {b.sample_dates.toLocaleString("ko-KR")}일, 실제 상승 비율{" "}
              {(b.positive_rate * 100).toFixed(1)}%
            </p>
          )}
          {data.experiment && <p className="m-0 px-1 text-xs text-muted">
            지표와 상승 비율은 연도별 평균, 관측치·거래일·거래 수는 합계예요.
            {sample !== "all" && " 고변동일은 맞히는 능력과 확률만 다시 평가해서 모의 투자 결과는 별도 백테스트 미산출이에요."}
          </p>}
        </section>

        <section aria-labelledby="design-title" className="flex flex-col gap-3">
          <h2 id="design-title" className="px-1 text-xl font-semibold">
            실험 설계
          </h2>
          <Definitions items={data.experiment ? [...DESIGN.filter(([term]) => term !== "고변동일"),
            ["고변동일", data.experiment.volatile_definition], ["모의 투자 규칙", "상승 점수 0.65 이상인 종목을 하루 최대 5개, 다음 날 시가에 사고팔아요. 사고팔 때마다 비용 0.105%를 빼요."],
            ["집계", data.experiment.backtest_scope], ["한계", data.experiment.limitations], ["출처", data.experiment.source]] : DESIGN} />
        </section>

        <section aria-labelledby="metrics-title" className="flex flex-col gap-3">
          <h2 id="metrics-title" className="px-1 text-xl font-semibold">
            지표 정의
          </h2>
          <Definitions
            items={METRICS.filter((metric) => metric.description).map((metric) => [metric.label, metric.description!])}
          />
        </section>
        <section aria-labelledby="sources-title" className="flex flex-col gap-3">
          <h2 id="sources-title" className="px-1 text-xl font-semibold">
            데이터 출처
          </h2>
          <Definitions items={SOURCES} />
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
    <dl className="surface m-0 grid grid-cols-1 gap-x-6 px-5 py-2 sm:grid-cols-[132px_1fr]">
      {items.map(([term, description]) => (
        <div key={term} className="contents">
          <dt className="pt-3 text-sm font-medium text-ink sm:pb-3">{term}</dt>
          <dd className="m-0 border-b border-line-soft pb-3 text-sm text-body last:border-0 sm:pt-3">{description}</dd>
        </div>
      ))}
    </dl>
  );
}
