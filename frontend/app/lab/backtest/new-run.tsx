"use client";

import { useState } from "react";
import { Empty, Panel, Term } from "./charts";
import { act, asMessage } from "./api";
import { choices, dataValue, groups, LABEL, n, show } from "./metrics";
import type { Base, Benchmark, Check, Run } from "./types";
import styles from "./lab.module.css";

export function NewRun({ bases, benchmarks, fixed, busy, catalogError, open, refresh }: {
  bases: Base[]; benchmarks: Benchmark[]; fixed?: Run; busy: boolean; catalogError: string;
  open: (id: string) => void; refresh: () => Promise<void>;
}) {
  const [baseId, setBase] = useState("");
  const [name, setName] = useState<string>();
  const [changes, setChanges] = useState<Record<string, string>>({});
  const [check, setCheck] = useState<Check>();
  const [pending, setPending] = useState(false);
  const [overwrite, setOverwrite] = useState(false);
  const [error, setError] = useState("");
  const selected = bases.find((entry) => entry.id === baseId) ??
    (fixed?.configPath ? bases.find((entry) => entry.id === fixed.configPath) :
      bases.find((entry) => entry.name === fixed?.name) ?? bases[0]);
  if (!selected) return <><h1>새 실행</h1><Panel><Empty>{catalogError || "사용 가능한 설정을 확인하는 중입니다."}</Empty></Panel></>;
  const base = selected;
  const config = base.config;
  const getRaw = (key: string) => dataValue(config, key);
  const getText = (key: string) => {
    if (Object.hasOwn(changes, key)) return changes[key];
    const original = getRaw(key);
    if (key === "evaluation.benchmark_file") {
      return String(original ?? "").replace(/^.*workspace\/experiments\//, "");
    }
    return original == null ? "" : String(original);
  };
  const runName = name ?? (fixed?.name || `${base.name}_custom`);
  const changed = groups.flatMap(({ fields }) => fields).filter((key) => Object.hasOwn(changes, key) &&
    (key === "evaluation.benchmark_file" ? getText(key) !== String(getRaw(key) ?? "").replace(/^.*workspace\/experiments\//, "")
      : getText(key) !== String(getRaw(key) ?? "")));
  function invalidate() {
    setCheck(undefined);
    setError("");
    setOverwrite(false);
  }
  const mismatch = config.labels?.type === "dynamic_sigma" &&
    (n(getText("backtest.up_mult")) !== n(config.labels?.up_mult) || n(getText("backtest.down_mult")) !== n(config.labels?.down_mult));
  const years = getText("backtest.capital_mode") === "continuous" ? 1 : base.years.length;
  const duration = Math.max(0, Math.round(years * (1 + (n(getText("evaluation.random_baseline_runs")) ?? 0)) * 1.1));
  function converted(key: string) {
    const text = getText(key);
    if (key in choices || key === "evaluation.benchmark_file") return text;
    if (text === "" && ["backtest.max_participation", "backtest.hard_sl_mult", "backtest.up_mult", "backtest.down_mult"].includes(key)) return null;
    if (!text.trim() || n(text) === null) throw new Error(`${LABEL[key]} 값을 숫자로 입력하세요.`);
    return n(text);
  }
  async function inspect() {
    setPending(true);
    invalidate();
    try {
      const values = Object.fromEntries(changed.map((key) => [key, converted(key)]));
      setCheck(await act<Check>({ action: "check", base: base.id, name: runName, changes: values }));
    } catch (error) { setError(asMessage(error)); }
    finally { setPending(false); }
  }
  async function launch() {
    if (!check?.ok || (check.existing && !overwrite)) return;
    setPending(true);
    setError("");
    try {
      const { run } = await act<{ run: string }>({ action: "run", config: check.config, overwrite });
      await refresh();
      open(run);
    } catch (error) { setError(asMessage(error)); }
    finally { setPending(false); }
  }
  return <>
    <h1>새 실행</h1>
    <div className={styles.newLayout}>
      <div className={styles.stack}>
        <Panel title="모델">
          <label className={styles.label}>기준 설정<select aria-label="기준 설정" disabled={pending} value={base.id} onChange={(event) => {
            setBase(event.target.value); setChanges({}); setName(undefined); invalidate();
          }}>{bases.map((entry) => <option key={entry.id} value={entry.id}>{entry.name}</option>)}</select></label>
          <p className={styles.sub}>예측 기간 {show("labels.horizon", config.labels?.horizon)} | {String(config.data?.start_date)} ~ {String(config.data?.end_date)}</p>
        </Panel>
        {groups.map(({ title, fields }) => <Panel key={title} title={title}>
          <div className={styles.fieldGrid}>{fields.map((key) => {
            const title = LABEL[key] ?? key;
            const options = key === "evaluation.benchmark_file" ? benchmarks.map(({ id }) => id) : choices[key];
            const value = getText(key);
            const edited = changed.includes(key);
            function change(text: string) { setChanges({ ...changes, [key]: text }); invalidate(); }
            return <label key={key} className={styles.label}>
              <span><Term>{title}</Term></span>
              {options ? <select aria-label={title} disabled={pending} value={value} className={edited ? styles.changed : ""}
                onChange={(event) => change(event.target.value)}>
                {!options.includes(value) && <option value={value}>{value ? `${show(key, value)} (설정 파일)` : "선택 가능 파일 없음"}</option>}
                {options.map((option) => <option key={option} value={option}>{show(key, option)}</option>)}
              </select> : <input aria-label={title} disabled={pending} inputMode="decimal" value={value} className={edited ? styles.changed : ""}
                onChange={(event) => change(event.target.value)} />}
              {edited && <span className={styles.original}>원래 값 {show(key, getRaw(key))}</span>}
            </label>;
          })}</div>
        </Panel>)}
      </div>
      <Panel className={styles.formSummary}>
        <label className={styles.label}>이름<input disabled={pending} value={runName} onChange={(event) => { setName(event.target.value); invalidate(); }} /></label>
        <div className={styles.stackSmall}><div className={styles.sub}>바꾼 값</div>
          <div>{changed.length ? changed.map((key) => <span className={`${styles.chip} ${styles.diff}`} key={key}>
            {LABEL[key]} {show(key, getRaw(key))} → {getText(key) || "제한 없음"}</span>) : <Empty>없음</Empty>}</div>
        </div>
        {(mismatch || check?.label_barrier_mismatch) && <div className={styles.warning}>익절·손절 배수가 모델 라벨과 달라요. 라벨의 배수는 {String(config.labels?.up_mult)}, {String(config.labels?.down_mult)}입니다.</div>}
        {error && <p className={styles.error} role="alert">{error}</p>}
        {check && <div role="status">
          {check.ok ? <strong className={styles.success}>검사 통과</strong> : <strong className={styles.error}>검사 실패</strong>}
          {check.errors.map((message) => <p className={styles.error} key={message}>{message}</p>)}
          {check.predictions_hash && <p className={styles.sub}>예측 캐시 {check.predictions_hash} {check.cache_exists ? "있음" : "없음"}</p>}
          {check.ok && check.existing && <div className={styles.warning}>
            <strong>기존 결과 덮어쓰기</strong><p className={styles.path}>{check.result_dir}</p>
            <label className={styles.confirm}><input type="checkbox" disabled={pending} checked={overwrite} onChange={(event) => setOverwrite(event.target.checked)} />이 폴더의 기존 백테스트 결과를 덮어씁니다.</label>
          </div>}
        </div>}
        <div className={styles.sub}>예상 시간 약 {Math.floor(duration / 60)}분 {duration % 60}초</div>
        {busy && <div className={styles.sub}>다른 작업이 끝난 뒤 실행할 수 있어요.</div>}
        <div className={styles.actions}>
          <button className="btn-secondary" disabled={pending} onClick={() => void inspect()}>검사</button>
          <button className="btn-primary" disabled={pending || busy || !check?.ok || (check.existing && !overwrite)}
            onClick={() => void launch()}>실행</button>
        </div>
      </Panel>
    </div>
  </>;
}
