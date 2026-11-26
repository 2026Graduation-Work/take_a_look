"use client";

import { useEffect, useState } from "react";
import { act, asMessage, read } from "./api";
import { Calibration, calibrationVerdict, Distribution, Empty, EquityChart, Meter, Panel, Position, Segments, Term } from "./charts";
import { BT_METRICS, choices, dec, grade, groups, integer, LABEL, median, ML_METRICS, mlValue, n, pathName, pct, periodLabel, periodMetric, progress, show, STATUS, times, winMetric, wins } from "./metrics";
import type { Base, Benchmark, Model, PeriodData, Run, Snapshot, Values } from "./types";
import styles from "./lab.module.css";

export const VIEW_OPTIONS = [{ key: "bt", label: "백테스트" }, { key: "model", label: "모델" }];
const periodAvailability = ["queued", "running"];
const classifications = { good: "좋음", weak: "약함", bad: "나쁨", missing: "자료 없음" };
const EXCLUSIONS: Record<string, string> = {
  open_beyond_barrier: "시가가 이미 익절·손절선 밖", limit_up_open: "상한가라 못 삼",
  liquidity_capped: "거래대금 상한으로 줄임", insufficient_cash: "현금 부족", limit_down_locked: "하한가라 못 팖",
  trading_halt: "거래 정지", invalid_price: "가격 자료 없음", missing_bar: "거래일 자료 없음",
};

export function usePeriodData(runs: string[], year: string, benchmark: string, version = "") {
  const [result, setResult] = useState<{ key: string; data?: Record<string, PeriodData>; error?: string }>();
  const query = new URLSearchParams({ read: "periods", year, benchmark });
  for (const run of runs) query.append("run", run);
  const key = query.toString();
  useEffect(() => {
    if (!year || !new URLSearchParams(key).has("run")) return;
    let live = true;
    void read<Record<string, PeriodData>>(new URLSearchParams(key)).then(
      (data) => { if (live) setResult({ key: key + version, data }); },
      (error) => { if (live) setResult({ key: key + version, error: asMessage(error) }); },
    );
    return () => { live = false; };
  }, [key, version, year]);
  return result?.key === key + version ? result : undefined;
}

export function useBenchmarkReturns(runs: string[], benchmark: string, version: string) {
  type Returns = Record<string, Record<string, number | null>>;
  const [result, setResult] = useState<{ key: string; data: Returns }>();
  const query = new URLSearchParams({ read: "benchmark-returns", benchmark });
  for (const run of runs) query.append("run", run);
  const key = query.toString();
  useEffect(() => {
    if (!benchmark) return;
    let live = true;
    void read<Returns>(new URLSearchParams(key)).then(
      (data) => { if (live) setResult({ key: key + version, data }); },
      () => { if (live) setResult({ key: key + version, data: {} }); },
    );
    return () => { live = false; };
  }, [benchmark, key, version]);
  return result?.key === key + version ? result.data : undefined;
}

export function BenchmarkSelect({ benchmarks, benchmark, setBenchmark }: {
  benchmarks: Benchmark[]; benchmark: string; setBenchmark: (value: string) => void;
}) {
  return <select className={styles.chartSelect} aria-label="기준 지수" value={benchmark}
    onChange={(event) => setBenchmark(event.target.value)}>
    <option value="">실행에 저장된 기준 지수</option>
    {benchmarks.map(({ id, name }) => <option key={id} value={id}>{name} ({id.split("/")[1]})</option>)}
  </select>;
}

export function PeriodControls({ periods, year, setYear, benchmarks, benchmark, setBenchmark }: {
  periods: string[]; year: string; setYear: (value: string) => void;
  benchmarks: Benchmark[]; benchmark: string; setBenchmark: (value: string) => void;
}) {
  return <div className={styles.actions}><BenchmarkSelect {...{ benchmarks, benchmark, setBenchmark }} />
    <Segments options={periods.map((key) => ({ key, label: periodLabel(key) }))} selected={year}
      change={setYear} label="자산 곡선 기간" /></div>;
}

function Disclosure({ title, children }: { title: string; children: React.ReactNode }) {
  return <details className={styles.disclosure}><summary>{title}</summary>{children}</details>;
}

function Settings({ run, model }: { run: Run; model?: Model }) {
  const sections = model ? ["data", "labels", "features", "model"] : groups.map(({ fields }) => fields[0].split(".")[0]);
  const sectionLabels: Record<string, string> = {
    data: "데이터", labels: "라벨", features: "피처", model: "알고리즘",
  };
  function rows(section: string, entries: [string, unknown][]) {
    return <dl className={styles.kv}>{entries.map(([key, value]) => {
      const full = `${section}.${key}`;
      if (!LABEL[full] && !choices[full]) return null;
      return <div key={key}><dt><Term>{LABEL[full] ?? key}</Term></dt><dd>{show(full, value)}</dd></div>;
    })}</dl>;
  }
  return model ? <Panel title="모델 설정">
    {sections.map((section) => {
      const config = run.config[section] ?? {};
      if (section === "model") {
        const params = Object.entries((config.params as Values) ?? {});
        return <div key={section} className={styles.settingsPart}><strong>{sectionLabels[section]}</strong>
          {rows(section, Object.entries(config).filter(([key]) => key !== "params"))}
          {rows(section, params.slice(0, 4))}
          {params.length > 4 && <Disclosure title="나머지 하이퍼파라미터">{rows(section, params.slice(4))}</Disclosure>}
        </div>;
      }
      return <div key={section} className={styles.settingsPart}><strong>{sectionLabels[section]}</strong>
        {rows(section, Object.entries(config))}
        {section === "features" && <p className={styles.sub}>피처 {model.featureColumns.length}개</p>}
      </div>;
    })}
  </Panel> : <Panel><Disclosure title="매매 설정">
    {[...new Set(sections)].map((section) => <div key={section}>{rows(section, Object.entries(run.config[section] ?? {}))}</div>)}
  </Disclosure></Panel>;
}

function Failure({ run, fix }: { run: Run; fix: () => void }) {
  const [log, setLog] = useState<string>();
  const reason = run.status.error?.reason ?? "실행이 중단되었습니다.";
  const lead = reason.split("\n")[0];
  return <Panel title={<span className={styles.error}>{STATUS[run.status.status]}</span>}
    action={<button className="btn-secondary" onClick={fix}>설정 고치기</button>}>
    <p>{lead}</p>
    {run.status.status === "failed" && <pre className={styles.log}>{run.status.error?.hint ??
      `python -m experiments.run_backtest --config ${run.configPath ?? "<수정한 설정 파일>"}`}</pre>}
    <details className={styles.disclosure} onToggle={(event) => {
      if (event.currentTarget.open && run.jobId && log === undefined) {
        void read<{ log: string }>(new URLSearchParams({ read: "log", id: run.jobId }))
          .then(({ log }) => setLog(log || reason), () => setLog(reason));
      }
    }}><summary>로그</summary><pre className={styles.log}>{log ?? reason}</pre></details>
  </Panel>;
}

function Backtest({ run, benchmarks, snapshot, bases, fix, refresh }: {
  run: Run; benchmarks: Benchmark[]; snapshot: Snapshot; bases: Base[]; fix: () => void; refresh: () => Promise<void>;
}) {
  const [wantedYear, setYear] = useState("");
  const [benchmark, setBenchmark] = useState("");
  const [error, setError] = useState("");
  const [cancelling, setCancelling] = useState(false);
  const periods = run.periods.map(({ key }) => key);
  const year = periods.includes(wantedYear) ? wantedYear : periods.at(-1) ?? "";
  const current = run.periods.find(({ key }) => key === year);
  const result = usePeriodData(current ? [run.id] : [], year, benchmark, run.status.started_at ?? "");
  const selectedReturns = useBenchmarkReturns([run.id], benchmark, `${run.status.started_at ?? ""}:${periods.join()}`);
  const data = result?.data?.[run.id];
  const label = benchmark ? benchmarks.find(({ id }) => id === benchmark)?.name || pathName(benchmark) :
    pathName(String(run.config.evaluation?.benchmark_file ?? "기준 지수"));
  const live = periodAvailability.includes(run.status.status);
  const canCancel = snapshot.job?.run === run.id && snapshot.job?.kind === "backtest" && snapshot.job?.status === "running";
  const fraction = progress(run);
  const [done, total] = run.status.progress.random;
  const [yearIndex] = run.status.progress.year;
  const configBase = bases.find(({ id, name }) => id === run.configPath || name === run.name);
  const currentYear = run.config.backtest?.capital_mode === "continuous" ? "전체 기간"
    : configBase?.years[yearIndex - 1] ? `${configBase.years[yearIndex - 1]}년`
      : yearIndex ? `${yearIndex}번째 연도` : "준비 중";
  const elapsed = run.status.started_at ? (snapshot.observed_at - Date.parse(run.status.started_at)) / 1000 : 0;
  const remaining = fraction > 0 ? Math.max(0, Math.ceil(elapsed / fraction * (1 - fraction))) : null;
  async function cancel() {
    setCancelling(true); setError("");
    try {
      await act({ action: "cancel", id: snapshot.job?.id }); await refresh();
    } catch (error) { setError(asMessage(error)); }
    finally { setCancelling(false); }
  }
  if (run.status.status === "failed" || run.status.status === "cancelled") return <>
    <Failure run={run} fix={fix} /><Settings run={run} />
  </>;
  const count = wins(run);
  return <>
    {live ? <Panel title={`${STATUS[run.status.status]} ${Math.round(fraction * 100)}%`}
      action={canCancel && <button className="btn-secondary" disabled={cancelling} onClick={() => void cancel()}>취소</button>}>
      <Meter value={fraction} />
      <p className={styles.sub}>{currentYear}{total > 0 && ` 무작위 ${done}/${total}회`}
        {remaining !== null && ` | 약 ${Math.floor(remaining / 60)}분 ${remaining % 60}초 남음`}</p>
      {error && <p role="alert" className={styles.error}>{error}</p>}
    </Panel> : <Panel>
      <div className={styles.stats}>
        <div><div className={styles.sub}><Term>무작위 대비</Term>를 절반 넘게 이긴 {periods.includes("all") ? "기간" : "연도"}</div>
          <div className={styles.big}>{count.count ? `${count.won}/${count.count}` : "—"}</div><div className={styles.sub}>샤프 기준</div></div>
        {[
          { key: "sharpe_ratio", label: "샤프", fmt: dec }, { key: "max_drawdown", label: "MDD", fmt: pct },
          { key: "turnover", label: "회전율", fmt: times },
        ].map(({ key, label, fmt }) => <div key={key}><div className={styles.sub}><Term>{label}</Term></div>
          <div className={styles.big}>{fmt(median(run.periods.map((period) => periodMetric(period, key))))}</div>
          <div className={styles.sub}>{periods.includes("all") ? "전체 기간" : "연도 중앙값"}</div></div>)}
      </div>
    </Panel>}
    <Panel className={styles.tablePanel}><div className={styles.scroll}><table className={styles.table}>
      <thead><tr><th>연도</th>{["수익률", "기준 지수", "샤프", "무작위 대비", "MDD", "회전율", "거래 수"].map((term) =>
        <th className={styles.right} key={term}>{term === "기준 지수" ? <Term definition={`${label}의 수익률`}>{term}</Term> : <Term>{term}</Term>}</th>)}</tr></thead>
      <tbody>{run.periods.map((period) => {
        const share = winMetric(period);
        const valid = n(period.metrics.sharpe_ratio_valid_runs);
        return <tr key={period.key} className={year === period.key ? styles.selected : undefined} onClick={() => setYear(period.key)}>
          <td><button className={styles.rowAction} onClick={() => setYear(period.key)}>{periodLabel(period.key)}</button></td>
          <td className={styles.right}>{pct(periodMetric(period, "total_return"))}</td>
          <td className={styles.right}>{pct(benchmark ? selectedReturns?.[run.id]?.[period.key] ?? null
            : n((period.metrics.benchmark as Values | undefined)?.total_return))}</td>
          <td className={styles.right}>{dec(periodMetric(period, "sharpe_ratio"))}</td>
          <td className={styles.right}>{share === null || valid === null ? "—" : `${Math.round(share * valid)}/${valid}`}</td>
          <td className={styles.right}>{pct(periodMetric(period, "max_drawdown"))}</td>
          <td className={styles.right}>{times(periodMetric(period, "turnover"))}</td>
          <td className={styles.right}>{integer(periodMetric(period, "number_of_trades"))}</td>
        </tr>;
      })}{live && <tr><td>{currentYear}</td><td colSpan={7} className={styles.muted}>계산 중</td></tr>}</tbody>
    </table></div></Panel>
    {current && <>
      <div className={styles.detailLayout}>
        <Panel title={`${periodLabel(year)} 자산`}
          action={<PeriodControls {...{ periods, year, setYear, benchmarks, benchmark, setBenchmark }} />}>
          {result?.error ? <Empty>{result.error}</Empty> : data ? <>
            <EquityChart series={[
              { name: label, color: "#86868b", points: data.benchmark, dashed: true },
              { name: "모델", color: "#1d1d1f", points: data.equity },
            ]} />
            {benchmark && !data.benchmark.length && <Empty>선택한 지수에 이 기간의 종가가 없습니다.</Empty>}
          </> : <Empty>자산 곡선을 읽고 있습니다.</Empty>}
        </Panel>
        <Panel title={`무작위${current.metrics.random_runs ? ` ${current.metrics.random_runs}회` : ""}와 비교`}>
          {data?.random.length ? BT_METRICS.filter((metric) =>
            ["sharpe_ratio", "total_return", "max_drawdown"].includes(metric.key),
          ).map((metric) => <div key={metric.key} className={styles.sub}><Term>{metric.label}</Term>
            <Distribution values={data.random.map((row) => n(row[metric.key])).filter((score) => score !== null)}
              model={periodMetric(current, metric.key)} metric={metric} /></div>) : <Empty>저장된 무작위 분포가 없습니다.</Empty>}
        </Panel>
      </div>
      <div className={styles.columns}>
        <Panel title="못 하거나 줄인 주문">
          {data?.exclusions.length ? data.exclusions.map(({ reason, count }) => <div className={styles.exclusion} key={reason}>
            <span>{EXCLUSIONS[reason] ?? reason}</span><Meter color="#86868b" value={count / data.exclusions[0].count} />
            <span>{integer(count)}</span></div>) : <Empty>저장된 주문 제외 사유가 없습니다.</Empty>}
        </Panel>
        <Settings run={run} />
      </div>
    </>}
  </>;
}

function ModelDetail({ run, models, other, bases, busy, open, refresh }: {
  run: Run; models: Model[]; other: Run[]; bases: Base[]; busy: boolean;
  open: (id: string) => void; refresh: () => Promise<void>;
}) {
  const [pending, setPending] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const model = models.find(({ hash }) => hash === run.hash);
  const seen = model ?? { hash: run.hash, name: run.name, summary: null, folds: [], calibration: [], featureColumns: [] };
  const config = run.configPath ?? bases.find(({ name }) => name === run.name)?.id;
  const gradeCounts = ML_METRICS.map((metric) => grade(metric, mlValue(model?.summary, metric.key)));
  const links = other.filter(({ id, hash }) => id !== run.id && hash && hash === run.hash);
  async function evaluate() {
    setPending(true); setError(""); setMessage("");
    try {
      await act({ action: "ml", config, hash: run.hash });
      setMessage("ML 평가를 시작했습니다."); await refresh();
    } catch (error) { setError(asMessage(error)); }
    finally { setPending(false); }
  }
  return <>
    {model?.summary ? <>
      <Panel title="전체 평가 기간" action={<div className={styles.chips}>
        {(["good", "weak", "bad"] as const).map((key) => <span className={styles[key]} key={key}>
          {classifications[key]} {gradeCounts.filter((grade) => grade === key).length}</span>)}
      </div>}>
        <div className={styles.fieldGrid}>{ML_METRICS.map((metric) => {
          const value = mlValue(model.summary, metric.key);
          const level = grade(metric, value);
          const peers = models.flatMap((peer) => {
            const value = mlValue(peer.summary, metric.key);
            return value === null ? [] : [{ name: peer.name, value, current: peer.hash === model.hash }];
          });
          const rank = value === null ? null : 1 + peers.filter((peer) => peer.value > value).length;
          return <div className={styles.metricCard} key={metric.key}>
            <div className={styles.head}><span className={styles.sub}><Term definition={metric.rule}>{metric.label}</Term></span>
              <span className={styles[level]}>{classifications[level]}</span></div>
            <div className={styles.metricValue}><span className={styles.big}>{metric.fmt(value)}</span>
              <span className={styles.sub}>무작위 수준 {metric.fmt(metric.ref)}</span></div>
            <Position metric={metric} values={peers} /><div className={styles.sub}>
              {rank !== null ? `워크스페이스 모델 ${peers.length}개 중 ${rank}위` : "순위를 계산할 수 없습니다."}</div>
          </div>;
        })}</div>
        <p className={styles.sub}>점선은 무작위 수준, 연한 초록은 좋음 구간입니다. 회색 점은 다른 모델입니다.</p>
      </Panel>
      <Panel title="연도별"><div className={styles.scroll}><table className={styles.table}><thead><tr>
        <th>평가 기간</th><th className={styles.right}>표본</th><th className={styles.right}><Term>상승 비율</Term></th>
        {ML_METRICS.map((metric) => <th className={styles.right} key={metric.key}><Term definition={metric.rule}>{metric.label}</Term></th>)}
      </tr></thead><tbody>{model.folds.map((fold, i) => <tr key={i}>
        <td>{String(fold.period ?? fold.Fold)}</td><td className={styles.right}>{integer(n(fold.sample_count))}</td>
        <td className={styles.right}>{pct(n(fold.up_class_ratio))}</td>
        {ML_METRICS.map((metric) => {
          const value = mlValue(fold, metric.key, true);
          return <td className={styles.right} key={metric.key}><span className={styles[grade(metric, value)]}>{metric.fmt(value)}</span></td>;
        })}</tr>)}</tbody></table></div></Panel>
      <div className={styles.columns}><Settings run={run} model={model} /><Panel title={<Term>확률 보정</Term>}>
        <p>{calibrationVerdict(model.calibration)}</p>
        <Calibration series={[{ ...model, color: "#124532" }]} />
        {model.calibration.length > 0 && <div className={styles.scroll}><table className={styles.table}>
          <thead><tr>{["예측 구간", "예측 평균", "실제 상승률", "표본"].map((label) => <th key={label}>{label}</th>)}</tr></thead>
          <tbody>{model.calibration.map(({ bin, x, y, count }) => <tr key={bin}>
            <td>{bin}</td><td>{pct(x, 0)}</td><td>{pct(y, 0)}</td><td>{integer(count)}</td>
          </tr>)}</tbody></table></div>}
      </Panel></div>
    </> : <div className={styles.columns}><Settings run={run} model={seen} />
      <Panel title="ML 지표">
        <p>아직 이 모델의 ML 평가 결과가 없습니다.</p>
        <pre className={styles.log}>python -m experiments.run_ml_evaluation --config {config ?? "<설정 파일>"}</pre>
        <button className="btn-primary" disabled={!config || !run.hash || pending || busy} onClick={() => void evaluate()}>ML 평가 실행</button>
        {(!config || !run.hash) && <p className={styles.sub}>이 실행의 기준 설정을 찾을 수 없습니다.</p>}
        {message && <p className={styles.sub} role="status">{message}</p>}
        {error && <p className={styles.error} role="alert">{error}</p>}
      </Panel></div>}
    <div className={styles.sub}>이 모델을 쓴 다른 실행 {links.length ? links.map(({ id, name }) =>
      <button key={id} className={styles.related} onClick={() => open(id)}>{name}</button>) : "없음"}</div>
  </>;
}

export function Detail({ run, snapshot, benchmarks, bases, open, fix, refresh }: {
  run: Run; snapshot: Snapshot; benchmarks: Benchmark[]; bases: Base[];
  open: (id: string) => void; fix: () => void; refresh: () => Promise<void>;
}) {
  const [view, setView] = useState("bt");
  return <>
    <div><div className={styles.head}><h1>{run.name}</h1><Segments options={VIEW_OPTIONS} selected={view} change={setView} label="상세 보기" /></div>
      <p className={styles.sub}>모델 <code>{run.hash || "—"}</code>{run.status.code_commit && <> | 코드 <code>{run.status.code_commit.slice(0, 9)}</code></>}
        {run.status.finished_at && <> | {new Date(run.status.finished_at).toLocaleString("ko-KR")}</>}</p></div>
    {view === "bt" ? <Backtest {...{ run, benchmarks, snapshot, bases, fix, refresh }} /> :
      <ModelDetail run={run} models={snapshot.models} other={snapshot.runs} bases={bases}
        busy={snapshot.job?.status === "running"} open={open} refresh={refresh} />}
  </>;
}
