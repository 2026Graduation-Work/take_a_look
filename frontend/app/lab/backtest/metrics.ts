import type { Config, Period, Run, Values } from "./types";

export const LABEL: Record<string, string> = {
  "data.기간": "기간", "data.split": "학습·평가 분할", "labels.horizon": "예측 기간", "labels.up_mult": "라벨 익절 배수", "labels.down_mult": "라벨 손절 배수",
  "features.groups": "피처", "strategy.score_column": "점수", "strategy.top_n": "하루 매수 종목 수", "strategy.prob_threshold": "점수 문턱",
  "backtest.capital_mode": "자금 운용", "backtest.initial_cash": "초기 자금", "backtest.fee": "수수료", "backtest.slippage_bps": "슬리피지",
  "backtest.max_participation": "거래대금 상한", "backtest.max_holding_days": "최대 보유일", "backtest.up_mult": "익절 배수", "backtest.down_mult": "손절 배수",
  "backtest.hard_sl_mult": "강제 손절 배수", "evaluation.random_baseline_runs": "무작위 횟수", "evaluation.benchmark_file": "기준 지수", model: "모델", code: "코드 버전",
  "data.embargo_days": "학습·평가 사이 간격", "labels.type": "라벨 방식", "model.type": "알고리즘", "model.objective": "목표",
  "model.n_estimators": "트리 수", "model.learning_rate": "학습률", "model.max_depth": "최대 깊이", "model.num_leaves": "잎 수",
  "model.min_child_samples": "잎 최소 표본", "model.colsample_bytree": "피처 샘플 비율", "model.subsample": "행 샘플 비율", "model.class_weight": "클래스 가중치",
};
export const TERMS: Record<string, string> = {
  "ROC AUC": "상승한 종목을 상승하지 않은 종목보다 높게 점수 매길 확률. 0.5면 무작위, 1이면 완벽.",
  "PR AUC": "상승 클래스의 정밀도-재현율 곡선 아래 면적. 무작위 모델도 상승 비율만큼 나와서 그 값과 함께 봐야 해요.",
  "PR 향상": "PR AUC ÷ 상승 비율. ×1.00이 무작위 수준, ×1.20이면 무작위보다 20% 나음.",
  "Rank IC": "매일 예측 점수 순위와 실제 결과 순위의 상관(스피어만)을 구해 평균 낸 값. 0이면 무관. train.py 검증 기준은 0.02 이상.",
  "IC t값": "일별 IC 평균 ÷ (표준편차 ÷ √일수). 2 이상이면 우연으로 보기 어려워요. train.py 검증 기준과 같음.",
  "IC 양수 일 비율": "IC가 0보다 컸던 날의 비율. 50%가 무작위 수준.",
  "Brier": "예측 확률과 실제 결과(0 또는 1)의 제곱 오차 평균. 낮을수록 좋음.",
  "Brier 개선": "1 − Brier ÷ (늘 상승 비율만큼 예측했을 때의 Brier). 0보다 크면 평균값만 말하는 예측보다 확률이 정확해요.",
  "균형 정확도": "상승과 비상승 각각의 재현율 평균. 0.5가 무작위.",
  "상승 비율": "라벨이 상승 클래스인 표본의 비율. 무작위 모델의 PR AUC와 같아요.",
  "확률 보정": "예측 확률이 실제 비율과 맞는지. 점이 점선 위에 있으면 잘 맞는 것, 점선 아래면 확률을 부풀린 것.",
  "샤프": "일간 수익률 평균 ÷ 표준편차 × √252. 위험 한 단위당 수익.",
  "MDD": "기간 중 고점 대비 가장 크게 떨어진 폭.",
  "회전율": "1년 거래대금 ÷ 평균 자산. 3배면 자산을 1년에 3번 갈아탄 셈.",
  "무작위 대비": "같은 날 같은 개수를, 모델이 살 수 있었던 종목 중에서 무작위로 30번 골랐을 때 모델 샤프가 이긴 횟수.",
  "초과수익": "모델 수익률 − 기준 지수 수익률.",
  "기준 지수": "자산 곡선과 초과수익을 비교할 지수. 유니버스에 맞는 것을 골라요. datasets/*/benchmarks 의 파일 목록에서 가져옴.",
  "슬리피지": "주문가와 실제 체결가 차이 가정. 1bp = 0.01%.",
  "거래대금 상한": "한 종목 하루 거래대금 중 우리 주문이 차지할 수 있는 최대 비율.",
  "학습·평가 사이 간격": "학습 끝과 평가 시작 사이에 비워 두는 거래일(엠바고). 라벨 기간이 겹쳐 정보가 새는 걸 막아요.",
  "점수 문턱": "prob_up이 이 값 이상인 종목만 매수 후보가 돼요.",
  "익절 배수": "진입 때 변동성(σ)의 몇 배 올랐을 때 파는지.",
  "손절 배수": "진입 때 변동성(σ)의 몇 배 내렸을 때 파는지.",
  "강제 손절 배수": "장중 저가 기준으로 바로 손절하는 선(σ 배수).",
  "최대 보유일": "이 거래일 수가 지나면 장벽에 안 닿아도 팔아요.",
  "하루 매수 종목 수": "하루에 새로 사는 최대 종목 수(top-N).",
};

export const COLORS = ["#1d1d1f", "#ff6c0f", "#4666b5", "#8dc63f", "#86868b", "#8057a2"];
export const STATUS = { queued: "대기 중", running: "실행 중", done: "완료", failed: "실패", cancelled: "취소됨" };
export const groups = [
  { title: "전략", fields: ["strategy.top_n", "strategy.prob_threshold", "strategy.score_column"] },
  { title: "매매 규칙", fields: ["backtest.max_holding_days", "backtest.up_mult", "backtest.down_mult",
    "backtest.hard_sl_mult", "backtest.capital_mode", "backtest.initial_cash"] },
  { title: "비용", fields: ["backtest.fee", "backtest.slippage_bps", "backtest.max_participation"] },
  { title: "비교 기준", fields: ["evaluation.random_baseline_runs", "evaluation.benchmark_file"] },
];
export const choices: Record<string, string[]> = {
  "strategy.score_column": ["prob_up", "prob_neutral", "prob_down"],
  "backtest.capital_mode": ["independent_year", "continuous"],
};
const values: Record<string, string> = {
  independent_year: "연도마다 새로 시작", continuous: "이어서 운용", prob_up: "상승 확률",
  prob_down: "하락 확률", prob_neutral: "횡보 확률", dynamic_sigma: "변동성 기준 3분류",
  fixed: "고정 장벽", multiclass: "하락, 횡보, 상승 3분류", sliding: "이동 창",
  expanding: "확장 창", single: "한 번 분할", custom_blocks: "직접 지정",
  equal_weight: "동일 비중", top_k: "상위 종목", open: "시가", rule: "장벽 규칙",
};
Object.assign(LABEL, {
  "data.start_date": "분석 시작일", "data.end_date": "분석 종료일", "data.split_strategy": "학습과 평가 분할",
  "data.point_in_time": "시점별 종목 편입", "data.universe": "종목 범위", "data.tickers": "지정 종목",
  "data.universe_file": "종목 편입표", "data.sliding.train_window_years": "이동 창 학습 연수",
  "data.sliding.test_window_years": "이동 창 평가 연수", "data.expanding.initial_train_years": "최초 학습 연수",
  "data.expanding.test_window_years": "확장 창 평가 연수", "data.splits": "평가 구간",
  "data.custom_blocks": "직접 지정한 구간", "features.include": "추가 피처", "features.exclude": "제외 피처",
  "features.sources": "추가 피처 출처", "training.skip_validation": "학습 검증 생략",
  "backtest.signal_lag_days": "신호 적용 시차", "backtest.entry_price": "진입 가격",
  "backtest.exit_price": "청산 가격", "strategy.selection": "종목 선택 방식",
  "strategy.position_weighting": "비중 배분", "evaluation.probability_bins": "확률 보정 구간",
  "evaluation.benchmark_strategies": "기준 지수 사용", "labels.tp": "라벨 상승 장벽", "labels.sl": "라벨 하락 장벽",
  "labels.volatility_mode": "라벨 변동성 방식", "labels.up_class": "상승 클래스",
  "labels.neutral_class": "횡보 클래스", "labels.down_class": "하락 클래스",
  "model.random_state": "난수 시드", "model.n_jobs": "병렬 작업 수", "model.subsample_freq": "표본 추출 주기",
  "model.max_bin": "최대 구간 수", "model.reg_alpha": "L1 규제", "model.reg_lambda": "L2 규제",
  "model.min_split_gain": "최소 분할 이득",
});

export function n(value: unknown): number | null {
  if ((typeof value !== "number" && typeof value !== "string") || value === "") return null;
  const result = Number(value);
  return Number.isFinite(result) ? result : null;
}
export const dec = (value: number | null, digits = 2) => value === null ? "—" : value.toFixed(digits);
export const pct = (value: number | null, digits = 1) => value === null ? "—" : `${(value * 100).toFixed(digits)}%`;
export const times = (value: number | null) => value === null ? "—" : `${value.toFixed(1)}배`;
export const integer = (value: number | null) => value === null ? "—" : value.toLocaleString("ko-KR");
export const periodLabel = (key: string) => key === "all" ? "전체 기간" : key;
export const pathName = (value: string) => value.split("/").at(-1)?.replace(/\.(?:parquet|csv)$/, "") ?? value;
export const dataValue = (config: Config, key: string) =>
  key.split(".").reduce<unknown>((value, part) => (value as Values | undefined)?.[part], config);
export function show(key: string, value: unknown): string {
  if (value === null) return "제한 없음";
  if (value === undefined || value === "") return "—";
  if (key === "evaluation.benchmark_file") return pathName(String(value));
  if (key === "backtest.initial_cash") return `${integer(n(value))}원`;
  if (key === "backtest.fee" || key === "backtest.max_participation") return pct(n(value), 3);
  if (key === "backtest.slippage_bps") return `${value}bp`;
  if (["labels.horizon", "backtest.max_holding_days", "data.embargo_days", "backtest.signal_lag_days"].includes(key)) return `${value}일`;
  if (typeof value === "boolean") return value ? "사용" : "사용하지 않음";
  if (Array.isArray(value)) return value.length ? value.map((item) => show(key, item)).join(", ") : "없음";
  if (typeof value === "object") return JSON.stringify(value);
  return values[String(value)] ?? String(value);
}

export function periodMetric(period: Period, key: string) {
  const metrics = period.metrics;
  if (key === "excess") {
    const ret = n(metrics.total_return);
    const bench = n((metrics.benchmark as Values | undefined)?.total_return);
    return ret === null || bench === null ? null : ret - bench;
  }
  return n(metrics[key]);
}
export const winMetric = (period: Period) => periodMetric(period, "sharpe_ratio_percentile_vs_random");

export function median(values: (number | null)[]) {
  const sorted = values.filter((value) => value !== null).sort((a, b) => a - b);
  const mid = Math.floor(sorted.length / 2);
  if (!sorted.length) return null;
  return sorted.length % 2 ? sorted[mid] : (sorted[mid - 1] + sorted[mid]) / 2;
}

export function wins(run: Run) {
  const available = run.periods.map(winMetric).filter((value) => value !== null);
  return { won: available.filter((value) => value > 0.5).length, count: available.length };
}
export function progress(run: Run) {
  if (run.status.status === "done") return 1;
  const [index, count] = run.status.progress.year;
  const [done, total] = run.status.progress.random;
  if (!index || !count) return 0;
  const finished = run.periods.length >= index;
  return Math.min(0.99, (index - 1 + (finished ? 1 : done / (1 + total))) / count);
}

export interface Metric {
  key: string;
  label: string;
  ref: number;
  good: number;
  fmt: (value: number | null) => string;
}
export const BT_METRICS: Metric[] = [
  { key: "sharpe_ratio_percentile_vs_random", label: "무작위 대비", ref: .5, good: .8, fmt: (v) => pct(v, 0) },
  { key: "sharpe_ratio", label: "샤프", ref: 0, good: 1.2, fmt: dec },
  { key: "excess", label: "초과수익", ref: 0, good: .15, fmt: pct },
  { key: "total_return", label: "수익률", ref: 0, good: .25, fmt: pct },
  { key: "max_drawdown", label: "MDD", ref: -.15, good: -.07, fmt: pct },
];
export interface MLMetric extends Metric {
  weak: number;
  rule: string;
}
export const ML_METRICS: MLMetric[] = [
  { key: "auc", label: "ROC AUC", ref: .5, weak: .52, good: .55, fmt: (v) => dec(v, 3), rule: "0.55 이상 좋음, 0.52 미만 나쁨 (임시 경험칙)" },
  { key: "lift", label: "PR 향상", ref: 1, weak: 1.05, good: 1.15, fmt: (v) => v === null ? "—" : `×${dec(v)}`, rule: "×1.15 이상 좋음, ×1.05 미만 나쁨 (임시 경험칙)" },
  { key: "ic", label: "Rank IC", ref: 0, weak: .01, good: .02, fmt: (v) => dec(v, 3), rule: "0.02 이상 좋음, 0.01 미만 나쁨 (train.py 검증 기준)" },
  { key: "ict", label: "IC t값", ref: 0, weak: 1, good: 2, fmt: (v) => dec(v, 1), rule: "2.0 이상 좋음, 1.0 미만 나쁨 (train.py 검증 기준)" },
  { key: "icpos", label: "IC 양수 일 비율", ref: .5, weak: .52, good: .55, fmt: (v) => pct(v, 0), rule: "55% 이상 좋음, 52% 미만 나쁨 (임시 경험칙)" },
  { key: "bss", label: "Brier 개선", ref: 0, weak: 0, good: .03, fmt: (v) => v !== null && v > 0 ? `+${pct(v)}` : pct(v), rule: "+3% 이상 좋음, 0 미만 나쁨 (임시 경험칙)" },
];

export function mlValue(values: Values | null | undefined, key: string, fold = false) {
  if (!values) return null;
  const cls = (name: string) => n(values[(fold ? "" : "ml_") + name]);
  switch (key) {
    case "auc": return cls("roc_auc");
    case "ic": return n(values[fold ? "ic_mean" : "ic_ic_mean"]);
    case "ict": return n(values[fold ? "ic_t_stat" : "ic_ic_t_stat"]);
    case "icpos": return n(values.ic_positive_day_ratio);
    case "lift": {
      const pr = cls("pr_auc");
      const ratio = cls("up_class_ratio");
      return pr === null || !ratio ? null : pr / ratio;
    }
    case "bss": {
      const brier = cls("brier_score");
      const ratio = cls("up_class_ratio");
      return brier === null || !ratio || ratio === 1 ? null : 1 - brier / (ratio * (1 - ratio));
    }
    default: return null;
  }
}
export function grade(metric: MLMetric, value: number | null) {
  if (value === null) return "missing";
  return value >= metric.good ? "good" : value >= metric.weak ? "weak" : "bad";
}
