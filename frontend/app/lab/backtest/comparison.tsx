"use client";

import type { CSSProperties } from "react";
import { useState } from "react";
import { Calibration, calibrationVerdict, Dot, Empty, EquityChart, Legend, Meter, Panel, Segments, Term, YearDuel } from "./charts";
import { BenchmarkSelect, PeriodControls, useBenchmarkReturns, usePeriodData, VIEW_OPTIONS } from "./detail";
import { BT_METRICS, COLORS, dataValue, dec, LABEL, median, ML_METRICS, mlValue, pct, periodLabel, periodMetric, show, times, wins } from "./metrics";
import type { Benchmark, Model, Run } from "./types";
import styles from "./lab.module.css";

const SECTION_NAMES: Record<string, string> = {
  data: "기간", labels: "모델", model: "모델", features: "모델", training: "모델",
  strategy: "매매 규칙", backtest: "매매 규칙", evaluation: "비교 기준", code: "코드",
};
const chosenColor = (index: number) => COLORS[index % COLORS.length];
const orderKeys = (a: string, b: string) => a === "all" ? 1 : b === "all" ? -1 : a.localeCompare(b);

function Conditions({ runs }: { runs: Run[] }) {
  const keys = [...new Set(runs.flatMap((run) => Object.entries(run.config).flatMap(([section, input]) =>
    typeof input === "object" && input !== null ? Object.keys(input).flatMap((key) => {
      if (key === "params") return Object.keys(input.params ?? {}).map((param) => `${section}.params.${param}`);
      if ((key === "sliding" || key === "expanding") && input[key]) {
        return Object.keys(input[key] as object).map((param) => `${section}.${key}.${param}`);
      }
      return [`${section}.${key}`];
    }) : [],
  )))].filter((key) => key.replace(".params.", ".") in LABEL);
  const fields = [...keys, "model", "code"];
  function value(run: Run, key: string) {
    if (key === "model") return run.hash;
    if (key === "code") return run.status.code_commit;
    return dataValue(run.config, key);
  }
  function signature(run: Run, key: string) { return JSON.stringify(value(run, key)); }
  const differences = fields.filter((key) => new Set(runs.map((run) => signature(run, key))).size > 1);
  const differentGroups = new Set(differences.map((key) => SECTION_NAMES[key.split(".")[0]]));
  const same = [...new Set(Object.values(SECTION_NAMES))].filter((group) =>
    !differentGroups.has(group) &&
    fields.some((key) => SECTION_NAMES[key.split(".")[0]] === group && runs.every((run) => value(run, key) != null)),
  );
  return <Panel title="조건" action={<div className={styles.chips}>
    {same.map((group) => <span className={styles.chip} key={group}>{group} 같음</span>)}
  </div>}>
    {differentGroups.size > 1 && <p className={styles.warning}>
      {[...differentGroups].join(", ")} 조건이 함께 달라서 어느 쪽 때문인지 나눌 수 없어요.
    </p>}
    {differences.length ? <div className={styles.scroll}><table className={styles.table}><thead>
      <tr><th>다른 조건</th>{runs.map((run, i) => <th key={run.id}><Dot color={chosenColor(i)} />{run.name}</th>)}</tr>
    </thead><tbody>{differences.map((key) => <tr key={key}>
      <th scope="row"><Term>{LABEL[key.replace(".params.", ".")] ?? key}</Term></th>
      {runs.map((run) => <td key={run.id} className={signature(run, key) === signature(runs[0], key) ? undefined : styles.strong}>
        {value(run, key) == null ? "—" : show(key, value(run, key))}</td>)}</tr>)}</tbody></table></div> :
      <Empty>다른 조건이 없습니다.</Empty>}
  </Panel>;
}

function BacktestComparison({ runs, benchmarks }: { runs: Run[]; benchmarks: Benchmark[] }) {
  const [metricKey, setMetric] = useState(BT_METRICS[0].key);
  const [wantedYear, setYear] = useState("");
  const [benchmark, setBenchmark] = useState("");
  const metric = BT_METRICS.find(({ key }) => key === metricKey) ?? BT_METRICS[0];
  const periods = [...new Set(runs.flatMap((run) => run.periods.map(({ key }) => key)))].sort(orderKeys);
  const year = periods.includes(wantedYear) ? wantedYear : (periods.at(-1) ?? "");
  const current = runs.filter((run) => run.periods.some(({ key }) => key === year));
  const results = usePeriodData(current.map(({ id }) => id), year, benchmark, current.map((run) => run.status.finished_at ?? "").join());
  const selectedReturns = useBenchmarkReturns(runs.map(({ id }) => id), metricKey === "excess" ? benchmark : "",
    runs.map((run) => run.status.finished_at ?? "").join());
  const legend = runs.map(({ name }, index) => ({ name, color: chosenColor(index) }));
  const series = legend.map((line, i) => ({
    ...line, values: new Map(runs[i].periods.map((period) => {
      if (metricKey !== "excess" || !benchmark) return [periodLabel(period.key), periodMetric(period, metricKey)];
      const indexReturn = selectedReturns?.[runs[i].id]?.[period.key];
      const runReturn = periodMetric(period, "total_return");
      return [periodLabel(period.key), indexReturn == null || runReturn === null ? null : runReturn - indexReturn];
    })),
  }));
  const docs = [
    { label: "무작위 대비", description: "절반 넘게 이긴 기간", data: runs.map((run) => {
      const { won, count } = wins(run);
      return { value: count ? won / count : null, text: count ? `${won}/${count}` : "—" };
    }), lower: false },
    ...[
      { key: "sharpe_ratio", label: "샤프", fmt: dec }, { key: "max_drawdown", label: "MDD", fmt: pct },
      { key: "turnover", label: "회전율", fmt: times },
    ].map(({ key, label, fmt }) => ({
      label, description: "기간 중앙값", data: runs.map((run) => {
        const value = median(run.periods.map((period) => periodMetric(period, key)));
        return { value, text: fmt(value) };
      }), lower: key === "turnover",
    })),
  ];
  const res = results?.data;
  const actualBenchmarks = new Map<string, { name: string; color: string; points: { date: string; value: number }[]; dashed: true }>();
  for (const run of current) {
    const points = res?.[run.id]?.benchmark ?? [];
    if (!points.length) continue;
    const name = benchmark ? benchmarks.find(({ id }) => id === benchmark)?.name ?? "기준 지수"
      : show("evaluation.benchmark_file", run.config.evaluation?.benchmark_file);
    const identity = JSON.stringify(points);
    if (!actualBenchmarks.has(identity)) actualBenchmarks.set(identity, { name, color: "#86868b", points, dashed: true });
  }
  return <>
    <Panel title="한눈에" action={<Legend series={legend} />}>
      <div className={styles.summaryGrid}>{docs.map((doc) => {
        const values = doc.data.map(({ value }) => value).filter((value) => value !== null);
        const scale = Math.max(...values.map(Math.abs), 0) || 1;
        const best = doc.lower ? Math.min(...values) : Math.max(...values);
        return <div className={styles.metricCard} key={doc.label}>
          <div className={styles.sub}><Term>{doc.label}</Term> {doc.description}</div>
          {doc.data.map(({ value, text }, index) => <div className={styles.barRow} key={runs[index].id} title={runs[index].name}>
            <Meter color={chosenColor(index)} value={Math.abs(value ?? 0) / scale} />
            <span className={value === best ? styles.strong : styles.sub}>{text}</span>
          </div>)}
        </div>;
      })}</div>
    </Panel>
    <Panel title="연도별" action={<div className={styles.actions}>
      {metricKey === "excess" && <BenchmarkSelect {...{ benchmarks, benchmark, setBenchmark }} />}
      <Segments options={BT_METRICS} selected={metricKey} change={setMetric} label="연도별 백테스트 지표" /></div>}>
      <YearDuel series={series} labels={periods.map(periodLabel)} metric={metric}
        reference={metric.key === BT_METRICS[0].key ? "절반" : metric.key === "max_drawdown" ? "−15%" : "0"} />
      <p className={styles.sub}><Term>{metric.label}</Term>의 큰 점과 아래 색 칸이 앞선 실행을 나타냅니다.
        {metric.key === "excess" && (benchmark ? " 선택한 지수에 해당 기간의 종가가 없으면 값을 표시하지 않습니다."
          : " 각 실행에 저장된 기준 지수 대비입니다.")}</p>
    </Panel>
    <Panel title={`${periodLabel(year)} 자산`} action={<PeriodControls {...{ periods, year, setYear, benchmarks, benchmark, setBenchmark }} />}>
      {results?.error ? <Empty>{results.error}</Empty> : res ? <>
        <EquityChart series={[...actualBenchmarks.values(), ...legend.map((line, index) => ({
          ...line, points: res[runs[index].id]?.equity ?? [],
        }))]} />
        {benchmark && actualBenchmarks.size === 0 && <Empty>선택한 지수에 이 기간의 종가가 없습니다.</Empty>}
      </> : <Empty>자산 곡선을 읽고 있습니다.</Empty>}
    </Panel>
  </>;
}

function ModelComparison({ runs, models }: { runs: Run[]; models: Model[] }) {
  const [selected, setSelected] = useState(ML_METRICS[0].key);
  const metric = ML_METRICS.find(({ key }) => key === selected) ?? ML_METRICS[0];
  const groups = [...new Set(runs.map(({ hash }) => hash))].map((hash, i) => {
    const matches = runs.filter((run) => run.hash === hash);
    const model = models.find((model) => model.hash === hash);
    return { model, name: model?.name ?? matches[0].name, count: matches.length, color: chosenColor(i) };
  });
  const rows = ML_METRICS.map((metric) => {
    const values = groups.map(({ model }) => mlValue(model?.summary, metric.key));
    const ranking = values.flatMap((value, i) => value === null ? [] : [{ i, value }]).sort((a, b) => b.value - a.value);
    const winner = ranking.length >= 2 && metric.fmt(ranking[0].value) !== metric.fmt(ranking[1].value) ? ranking[0].i : -1;
    const scores = values.map((value) => value === null ? null : (value - metric.ref) / (metric.good - metric.ref));
    return { metric, values, winner, scores, compared: ranking.length >= 2 };
  });
  const scores = rows.flatMap(({ scores }) => scores.filter((score) => score !== null));
  const min = Math.min(-.25, ...scores);
  const max = Math.min(Math.max(1.4, ...scores), 2.5) + .4;
  const axis = (value: number) => (value - min) / (max - min) * 100;
  const total = groups.map((_, index) => rows.filter(({ winner }) => winner === index).length);
  const highest = Math.max(...total);
  const winner = total.filter((count) => count === highest).length === 1 ? groups[total.indexOf(highest)] : null;
  const series = groups.map(({ model, name, color }) => ({
    name, color, values: new Map((model?.folds ?? []).map((fold) => [String(fold.period ?? fold.Fold), mlValue(fold, metric.key, true)])),
  }));
  const years = [...new Set(series.flatMap(({ values }) => [...values.keys()]))].sort();
  const legend = groups.map((group) => ({ ...group, name: `${group.name} (실행 ${group.count}개)` }));
  return <>
    <Panel title="한눈에" action={<Legend series={legend} />}>
      {groups.length === 1 && <p className={styles.warning}>선택한 실행은 같은 모델을 사용합니다.</p>}
      {winner && highest > 0 && <p className={styles.leader}><Dot color={winner.color} /><strong>{winner.name}</strong> 모델이
        6개 지표 중 <strong>{highest}개</strong>에서 더 나아요.</p>}
      {groups.length > 1 && <p className={styles.sub}>{groups.map(({ name }, i) => `${name} ${total[i]}승`).join(" | ")}</p>}
      {groups.some(({ model }) => !model?.summary) && <p className={styles.sub}>ML 평가 자료가 없는 모델은 —로 표시합니다.</p>}
      <div className={styles.scroll}><div className={styles.modelChart} style={{ "--reference": `${axis(0)}%`, "--good": `${axis(1)}%` } as CSSProperties}>
        <div className={styles.modelRow}><div /><div className={styles.modelAxis}><span>무작위</span><span>좋음 기준</span></div><div className={styles.sub}>더 나은 모델</div></div>
        {rows.map(({ metric, values, winner, scores, compared }) => <div className={styles.modelRow} key={metric.key}>
          <div><Term definition={metric.rule}>{metric.label}</Term></div>
          <div className={styles.modelBars}>{scores.map((score, index) => {
            const clipped = Math.min(score ?? 0, 2.5);
            const start = axis(Math.min(clipped, 0)), end = axis(Math.max(clipped, 0));
            return <div className={styles.modelBarRow} key={index} title={groups[index].name}>
              <div className={styles.modelBar} style={{ left: `${start}%`, width: `${end - start}%`, background: groups[index].color,
                opacity: winner >= 0 && winner !== index ? .42 : 1 }} />
              <span className={winner === index ? styles.strong : undefined}
                style={{ left: `calc(${end}% + 7px)` }}>{metric.fmt(values[index])}{(score ?? 0) > 2.5 && " ›"}</span>
            </div>;
          })}</div>
          <div>{winner >= 0 ? <><Dot color={groups[winner].color} /><strong>{groups[winner].name}</strong></> :
            <span className={styles.sub}>{compared ? "비슷" : "비교 자료 없음"}</span>}</div>
        </div>)}
      </div></div>
      <p className={styles.sub}>무작위 수준을 0, 좋음 기준을 점선에 맞췄습니다. 막대 옆에는 원래 값을 표시합니다.</p>
    </Panel>
    <Panel title="연도별" action={<Segments options={ML_METRICS} selected={selected} change={setSelected} label="연도별 모델 지표" />}>
      {groups.length > 1 ? <YearDuel series={series} labels={years} metric={metric} /> : <Empty>같은 모델의 실행끼리는 연도별 모델 지표도 같습니다.</Empty>}
    </Panel>
    <Panel title={<Term>확률 보정</Term>}><div className={styles.columns}>
      <Calibration series={groups.map(({ model, name, color }) => ({ name, color, calibration: model?.calibration ?? [] }))} />
      <div className={styles.stackSmall}>{groups.map(({ model, name, color }, i) => <div key={i}>
        <strong><Dot color={color} />{name}</strong><p className={styles.sub}>{calibrationVerdict(model?.calibration ?? [])}</p>
      </div>)}</div>
    </div></Panel>
  </>;
}

export function Comparison({ runs, models, benchmarks }: { runs: Run[]; models: Model[]; benchmarks: Benchmark[] }) {
  const [view, setView] = useState("bt");
  return <>
    <div className={styles.head}><h1>비교</h1><Segments options={VIEW_OPTIONS} selected={view} change={setView} label="비교 보기" /></div>
    {runs.length < 2 ? <Panel><Empty>실행 목록에서 완료된 실행을 2개 이상 골라 주세요.</Empty></Panel> :
      <><Conditions runs={runs} />{view === "bt" ? <BacktestComparison runs={runs} benchmarks={benchmarks} /> :
        <ModelComparison runs={runs} models={models} />}</>}
  </>;
}
