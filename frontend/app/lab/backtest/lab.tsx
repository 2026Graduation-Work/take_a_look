"use client";

import { useCallback, useEffect, useState } from "react";
import { asMessage, read } from "./api";
import { Empty, Meter, Panel, Term } from "./charts";
import { Comparison } from "./comparison";
import { Detail } from "./detail";
import { NewRun } from "./new-run";
import { dec, median, pct, periodMetric, progress, STATUS, times, winMetric, wins } from "./metrics";
import type { Base, Benchmark, Run, Snapshot } from "./types";
import styles from "./lab.module.css";

const EMPTY: Snapshot = { runs: [], models: [], job: null, observed_at: 0 };
type View = { kind: "list" } | { kind: "detail"; id: string } | { kind: "new"; fix?: string } | { kind: "compare"; ids: string[] };

function getView(): View {
  const params = new URLSearchParams(window.location.search);
  if (params.has("new")) return { kind: "new", fix: params.get("new") || undefined };
  if (params.has("compare")) return { kind: "compare", ids: (params.get("compare") ?? "").split(",") };
  if (params.has("run")) return { kind: "detail", id: params.get("run") ?? "" };
  return { kind: "list" };
}

function List({ snapshot, selected, setSelected, open, newRun, compare }: {
  snapshot: Snapshot; selected: string[]; setSelected: (ids: string[]) => void;
  open: (id: string) => void; newRun: () => void; compare: (ids: string[]) => void;
}) {
  const { runs } = snapshot;
  const available = selected.filter((id) => runs.some((run) => run.id === id && run.status.status === "done"));
  const [limit, setLimit] = useState(false);
  function toggle(id: string) {
    if (available.includes(id)) {
      setSelected(available.filter((entry) => entry !== id));
      setLimit(false);
    } else if (available.length < 6) {
      setSelected([...available, id]);
      setLimit(false);
    } else setLimit(true);
  }
  return <>
    <div className={styles.head}><h1>실행 목록</h1>
      <div className={styles.actions}>
        <button className="btn-secondary" onClick={newRun}>새 실행</button>
        <button className="btn-primary" disabled={available.length < 2}
          onClick={() => compare(available)}>{available.length < 2 ? "2개 이상 골라 비교" : `${available.length}개 비교`}</button>
      </div>
    </div>
    {limit && <p className={styles.warning} role="status">한 번에 최대 6개까지 비교할 수 있어요. 하나를 해제한 뒤 골라 주세요.</p>}
    {runs.length === 0 ? <Panel><Empty>저장된 백테스트 결과가 없습니다. 새 실행에서 설정을 검사하고 실행해 보세요.</Empty></Panel> :
      <Panel className={styles.tablePanel}><div className={styles.scroll}>
        <table className={styles.table}><thead><tr>
          <th aria-label="선택" /><th>실행 이름</th><th>상태</th><th><Term>무작위 대비</Term></th>
          {["샤프", "MDD", "회전율"].map((term) => <th key={term} className={styles.right}><Term>{term}</Term></th>)}
        </tr></thead><tbody>{runs.map((run) => {
          const selected = available.includes(run.id);
          const complete = run.status.status === "done";
          const count = wins(run);
          const live = ["queued", "running"].includes(run.status.status);
          return <tr key={run.id} className={selected ? styles.selected : undefined} data-selectable={complete || undefined}
            onClick={complete ? () => toggle(run.id) : undefined}>
            <td>{complete && <input type="checkbox" checked={selected}
              onClick={(event) => event.stopPropagation()} onChange={() => toggle(run.id)}
              aria-label={`${run.name} 비교 선택`} />}</td>
            <td><button className={styles.rowAction} onClick={(event) => {
              event.stopPropagation();
              open(run.id);
            }}>{run.name}</button></td>
            <td><span className={run.status.status === "failed" ? styles.error : undefined}>{STATUS[run.status.status]}</span>
              {live ? <div className={styles.statusMeter}><Meter value={progress(run)} /><span>{Math.round(progress(run) * 100)}%</span></div> :
                complete && run.status.finished_at && <div className={styles.sub}>{new Date(run.status.finished_at).toLocaleString("ko-KR")}</div>}</td>
            <td>{complete && count.count ? <div className={styles.miniRow}>
              <div className={styles.mini} aria-label="기간별 무작위 대비">
                {run.periods.map((period) => {
                  const value = winMetric(period);
                  return value === null ? <span className={styles.missingBar} key={period.key} /> :
                    <span key={period.key} title={`${period.year ?? "전체 기간"} ${pct(value, 0)}`}
                      style={{ height: `${Math.max(2, value * 100)}%`, background: value > .5 ? "var(--color-brand)" : undefined }} />;
                })}
              </div><span className={styles.sub}>{count.won}/{count.count}{run.periods[0].year === null ? "" : "년"}</span>
            </div> : "—"}</td>
            {(["sharpe_ratio", "max_drawdown", "turnover"] as const).map((key, index) => <td key={key} className={styles.right}>
              {complete ? [dec, pct, times][index](median(run.periods.map((period) => periodMetric(period, key)))) : "—"}
            </td>)}
          </tr>;
        })}</tbody></table>
      </div></Panel>}
  </>;
}

export default function Lab() {
  const [view, setView] = useState<View>({ kind: "list" });
  const [snapshot, setSnapshot] = useState(EMPTY);
  const [catalog, setCatalog] = useState<{ bases: Base[]; benchmarks: Benchmark[] }>({ bases: [], benchmarks: [] });
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [catalogError, setCatalogError] = useState("");
  const [selected, setSelected] = useState<string[]>([]);
  const refresh = useCallback(async () => {
    try {
      setSnapshot(await read<Snapshot>());
      setError("");
    } catch (error) { setError(asMessage(error)); }
    finally { setLoading(false); }
  }, []);
  const refreshCatalog = useCallback(async () => {
    try {
      setCatalog(await read<{ bases: Base[]; benchmarks: Benchmark[] }>(new URLSearchParams({ read: "catalog" })));
      setCatalogError("");
    } catch (error) { setCatalogError(asMessage(error)); }
  }, []);

  useEffect(() => {
    function fromUrl() { setView(getView()); }
    const initial = window.setTimeout(() => {
      fromUrl();
      void refresh();
      void refreshCatalog();
    }, 0);
    window.addEventListener("popstate", fromUrl);
    const timer = window.setInterval(() => void refresh(), 1000);
    return () => {
      window.clearTimeout(initial);
      window.clearInterval(timer);
      window.removeEventListener("popstate", fromUrl);
    };
  }, [refresh, refreshCatalog]);

  function navigate(next: View) {
    const params = new URLSearchParams();
    if (next.kind === "detail") params.set("run", next.id);
    if (next.kind === "new") params.set("new", next.fix ?? "");
    if (next.kind === "compare") params.set("compare", next.ids.join(","));
    window.history.pushState(null, "", params.size ? `?${params}` : window.location.pathname);
    setView(next);
    if (next.kind === "new") void refreshCatalog();
    window.scrollTo(0, 0);
  }
  function open(id: string) { navigate({ kind: "detail", id }); }
  const run: Run | undefined = view.kind === "detail" ? snapshot.runs.find((entry) => entry.id === view.id) : undefined;
  const runs = view.kind === "compare"
    ? [...new Set(view.ids)].flatMap((id) => snapshot.runs.filter((run) => run.id === id && run.status.status === "done")).slice(0, 6)
    : [];
  return <div className={styles.lab}>
    <header className={styles.header}><div className={styles.wrap}><button className={styles.logo}
      onClick={() => navigate({ kind: "list" })}>백테스트 실험실</button><span className={styles.sub}>로컬 워크스페이스</span></div></header>
    <main className={`${styles.wrap} ${styles.main}`}>
      {view.kind !== "list" && <button className={styles.back} onClick={() => navigate({ kind: "list" })}>← 실행 목록</button>}
      {error && <p className={styles.warning} role="alert">{error}</p>}
      {loading ? <Panel><Empty>실행 결과를 읽고 있습니다.</Empty></Panel> :
        view.kind === "list" ? <List snapshot={snapshot} selected={selected} setSelected={setSelected} open={open}
          newRun={() => navigate({ kind: "new" })} compare={(ids) => navigate({ kind: "compare", ids })} /> :
          view.kind === "detail" ? run
            ? <Detail key={run.id} run={run} snapshot={snapshot} {...catalog} open={open} refresh={refresh}
              fix={() => navigate({ kind: "new", fix: run.id })} />
            : <Panel><Empty>선택한 실행을 찾을 수 없습니다.</Empty></Panel> :
          view.kind === "compare" ? <Comparison runs={runs} models={snapshot.models} benchmarks={catalog.benchmarks} /> :
          <NewRun key={view.fix ?? "new"} {...catalog} catalogError={catalogError}
            fixed={snapshot.runs.find((run) => run.id === view.fix)} busy={snapshot.job?.status === "running"} open={open} refresh={refresh} />}
    </main>
  </div>;
}
