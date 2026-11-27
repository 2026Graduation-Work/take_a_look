import { execFileSync, spawn } from "node:child_process";
import { lstat, readFile, readdir, stat } from "node:fs/promises";
import path from "node:path";
import type { Config, Job, Model, Period, Point, Run, Snapshot, Status, Values } from "../../../lab/backtest/types";

export const chart = path.resolve(process.cwd(), "../backend/analysis/chart");
export const workspace = path.join(chart, "workspace/experiments");
export const runsRoot = path.join(workspace, "runs");
export const jobsRoot = path.join(workspace, "lab/jobs");
export const python = process.env.BACKTEST_LAB_PYTHON || "python3";
export const runId = /^[^./\\\0][^/\\\0]{0,179}$/u;
export const jobId = /^[a-f0-9-]{36}$/;

async function files(directory: string) {
  try {
    return await readdir(directory, { withFileTypes: true });
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code === "ENOENT") return [];
    throw error;
  }
}

async function file(filename: string) {
  try {
    if (!(await lstat(filename)).isFile()) return null;
    return await readFile(filename, "utf8");
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code === "ENOENT") return null;
    throw error;
  }
}

export async function json<T>(filename: string): Promise<T | null> {
  const data = await file(filename);
  // Python emits these nonfinite tokens for undefined metrics. Keep quoted text intact.
  return data === null ? null : JSON.parse(
    data.replace(/("(?:[^"\\]|\\.)*")|\bNaN\b|-?\bInfinity\b/g, (token, quoted: string) => quoted ?? "null"),
  ) as T;
}

async function csv(filename: string) {
  const contents = await file(filename);
  if (!contents?.trim()) return [];
  const rows: string[][] = [];
  let quoted = false;
  let value = "";
  let row: string[] = [];
  for (let i = 0; i < contents.length; i++) {
    const c = contents[i];
    if (c === '"') {
      if (quoted && contents[i + 1] === '"') {
        value += c;
        i++;
      } else quoted = !quoted;
    } else if (!quoted && (c === "," || c === "\n")) {
      row.push(value);
      value = "";
      if (c === "\n") {
        rows.push(row);
        row = [];
      }
    } else if (quoted || c !== "\r") value += c;
  }
  if (row.length || value) rows.push([...row, value]);
  const [header, ...body] = rows;
  return body.filter((fields) => fields.length === header.length).map((fields) =>
    Object.fromEntries(header.map((key, index) => [key, fields[index]])),
  );
}

export function number(value: unknown): number | null {
  if ((typeof value !== "number" && typeof value !== "string") || value === "") return null;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

export function alive(pid: number | null) {
  if (!pid || pid <= 0) return false;
  try {
    process.kill(pid, 0);
    return true;
  } catch {
    return false;
  }
}

export function ownsJob(job: Job) {
  if (!alive(job.pid) || !jobId.test(job.id)) return false;
  try {
    const command = execFileSync("/bin/ps", ["-p", String(job.pid), "-o", "command="], { encoding: "utf8" });
    return command.includes("backtest-lab-job.py") && command.includes(job.id);
  } catch {
    return false;
  }
}

export async function activeJob() {
  const job = await json<Job>(path.join(jobsRoot, "active.json"));
  if (job?.status === "running" && !ownsJob(job)) {
    const final = await json<Job>(path.join(jobsRoot, job.id + ".json"));
    return final && final.status !== "running" ? final : {
      ...job, status: "failed" as const, error: "실행 프로세스가 종료되었습니다.",
    };
  }
  return job;
}

function period(metrics: Values, year: number | null, config: Config): Period {
  return {
    key: year === null ? "all" : String(year),
    year,
    start: typeof metrics.start === "string" ? metrics.start : String(config.data?.start_date ?? "") || null,
    end: typeof metrics.end === "string" ? metrics.end : String(config.data?.end_date ?? "") || null,
    metrics,
  };
}

async function getPeriods(directory: string, config: Config, status: Status) {
  if (status.status === "queued") return [];
  if (status.status === "done") {
    const metrics = await json<Values>(path.join(directory, "backtest_metrics.json"));
    if (!metrics) return [];
    if (Array.isArray(metrics.years)) return metrics.years.map((row: Values) => period(row, number(row.year), config));
    return [period(metrics, null, config)];
  }
  const started = Date.parse(status.started_at ?? "");
  if (!Number.isFinite(started)) return [];
  const yearsRoot = path.join(directory, "years");
  const completed = await Promise.all((await files(yearsRoot)).filter((entry) =>
    entry.isDirectory() && /^\d{4}$/.test(entry.name),
  ).map(async ({ name }) => {
    const filename = path.join(yearsRoot, name, "backtest_metrics.json");
    const timestamp = await lstat(filename).catch(() => null);
    if (!timestamp?.isFile() || timestamp.mtimeMs < started) return null;
    const metrics = await json<Values>(filename);
    if (!metrics) return null;
    const dateKey = (row: Record<string, string>) => row.Date || row.date || row[""] || row["Unnamed: 0"];
    const returns = await csv(path.join(yearsRoot, name, "daily_returns.csv"));
    return period({ ...metrics, start: returns[0] && dateKey(returns[0]), end: returns.at(-1) && dateKey(returns.at(-1)!) }, Number(name), config);
  }));
  return completed.filter((value) => value !== null).sort((a, b) => a.key.localeCompare(b.key));
}

async function modelArtifacts(run: Run, columns: string[]) {
  const directory = path.join(runsRoot, run.id);
  const summary = await json<Values>(path.join(directory, "ml_metrics_summary.json")).catch((error: unknown) => {
    if (error instanceof SyntaxError) return null;
    throw error;
  });
  const model: Model = { hash: run.hash, name: run.name, summary, folds: [], calibration: [], featureColumns: columns };
  if (!summary) return model;
  const [folds, dates, calibration] = await Promise.all([
    csv(path.join(directory, "model_metrics_by_fold.csv")),
    csv(path.join(directory, "fold_alignment.csv")),
    csv(path.join(directory, "calibration_by_fold.csv")),
  ]);
  const dateByFold = new Map(dates.map((row) => [row.fold_id, row.test_start]));
  model.folds = folds.map((fold) => ({ ...fold, period: dateByFold.get(fold.fold_id)?.slice(0, 4) ?? fold.Fold }));
  const bins = new Map<string, { x: number; y: number; count: number }>();
  for (const row of calibration) {
    const count = number(row.sample_count);
    const x = number(row.predicted_mean);
    const y = number(row.actual_up_hit_rate);
    if (!count || x === null || y === null) continue;
    const bin = bins.get(row.Prob_Bin) ?? { x: 0, y: 0, count: 0 };
    bins.set(row.Prob_Bin, { x: bin.x + x * count, y: bin.y + y * count, count: bin.count + count });
  }
  model.calibration = [...bins].map(([bin, { x, y, count }]) => ({ bin, x: x / count, y: y / count, count }))
    .sort((a, b) => a.x - b.x);
  return model;
}

export async function snapshot(): Promise<Snapshot> {
  const job = await activeJob();
  const entries = await files(runsRoot);
  const history = await Promise.all((await files(jobsRoot)).filter((entry) =>
    entry.isFile() && jobId.test(path.basename(entry.name, ".json")) && entry.name.endsWith(".json"),
  ).map(({ name }) => json<Job>(path.join(jobsRoot, name))));
  const newestByRun = new Map<string, Job>();
  for (const entry of history) {
    if (!entry || entry.kind !== "backtest") continue;
    if ((newestByRun.get(entry.run)?.started_at ?? "") < entry.started_at) newestByRun.set(entry.run, entry);
  }
  const results = await Promise.all(entries.filter((entry) =>
    entry.isDirectory() && runId.test(entry.name) && !entry.name.startsWith("synthetic_contract_smoke_"),
  ).map(async ({ name: id }) => {
    const directory = path.join(runsRoot, id);
    const [manifest, stored, info] = await Promise.all([
      json<{ config: Config & { experiment_name?: string }; predictions_hash?: string; feature_columns?: string[] }>(
        path.join(directory, "run_manifest.json"),
      ),
      json<Status>(path.join(directory, "backtest_status.json")),
      stat(path.join(directory, "backtest_metrics.json")).catch(() => null),
    ]);
    const latest = newestByRun.get(id);
    const current = job?.run === id && job.kind === "backtest" ? job : latest;
    if (!manifest && !stored) return null;
    if (!info && !stored && !current) {
      const summary = await file(path.join(directory, "ml_metrics_summary.json"));
      if (!summary) return null;
    }
    const status: Status = stored ?? {
      status: info ? "done" : current?.status === "running" ? "queued" : "done",
      pid: current?.pid ?? null, started_at: current?.started_at ?? null,
      finished_at: info?.mtime.toISOString() ?? null, code_commit: null,
      progress: { year: [0, 0], random: [0, 0] }, error: null,
    };
    if (["queued", "running"].includes(status.status) &&
        !(current && current.pid === status.pid ? ownsJob(current) : alive(status.pid))) {
      status.status = current?.status === "cancelled" ? "cancelled" : "failed";
      status.error = status.status === "failed"
        ? { reason: current?.error || "실행 프로세스가 종료되었습니다.", hint: null } : null;
    }
    const config = manifest?.config ?? {};
    const run: Run = {
      id, name: manifest?.config.experiment_name ?? id, config, hash: manifest?.predictions_hash ?? "",
      configPath: current?.config, jobId: current?.id, status, periods: await getPeriods(directory, config, status),
    };
    const model = run.hash ? await modelArtifacts(run, manifest?.feature_columns ?? []) : null;
    return { run, model };
  }));
  const runs: Run[] = [];
  const models = new Map<string, Model>();
  for (const entry of results) {
    if (!entry) continue;
    const { run, model } = entry;
    if (run.periods.length || run.status.status !== "done") runs.push(run);
    if (model && (!models.has(model.hash) || (!models.get(model.hash)?.summary && model.summary))) {
      models.set(model.hash, model);
    }
  }
  runs.sort((a, b) => (b.status.started_at ?? b.status.finished_at ?? "").localeCompare(a.status.started_at ?? a.status.finished_at ?? ""));
  return { runs, models: [...models.values()], job, observed_at: Date.now() };
}

export function runPython<T>(module: string, args: string[], input?: unknown): Promise<T> {
  return new Promise((resolve, reject) => {
    const child = spawn(python, ["-m", module, ...args], { cwd: chart, stdio: ["pipe", "pipe", "pipe"] });
    let stdout = "";
    let stderr = "";
    child.stdout.setEncoding("utf8").on("data", (data: string) => { stdout += data; });
    child.stderr.setEncoding("utf8").on("data", (data: string) => { stderr += data; });
    child.stdin.on("error", () => {});
    child.stdin.end(input === undefined ? undefined : JSON.stringify(input));
    child.once("error", reject);
    child.once("close", () => {
      try {
        resolve(JSON.parse(stdout) as T);
      } catch {
        reject(new Error(stderr.trim().split("\n").at(-1) || "Python 명령을 실행하지 못했습니다."));
      }
    });
  });
}

type Close = { date: string; close: number };
const dateOf = (row: Record<string, string>) => (row.Date || row.date || row[""] || row["Unnamed: 0"] || "").slice(0, 10);

async function closesFor(file: string, from: string, to: string) {
  const start = new Date(from);
  start.setUTCDate(start.getUTCDate() - 14);
  return runPython<Close[]>("experiments.lab_read", [
    "benchmark", "--file", file, "--start", start.toISOString().slice(0, 10), "--end", to,
  ]);
}

function benchmarkLine(closes: Close[], dates: string[]): Point[] {
  if (!dates.length) return [];
  const base = closes.findLast((point) => point.date < dates[0]);
  if (!base) return [];
  const byDate = new Map(closes.map(({ date, close }) => [date, close]));
  if (!dates.every((date) => byDate.has(date))) return [];
  return dates.map((date) => ({ date, value: byDate.get(date)! / base.close }));
}

async function periodRows(directory: string, key: string, name: string) {
  if (key === "all") return csv(path.join(directory, name));
  const rows = await csv(path.join(directory, "years", key, name));
  return rows.length ? rows : (await csv(path.join(directory, name))).filter((row) => row.year === key);
}

export async function readBenchmarkReturns(ids: string[], file: string) {
  const { runs } = await snapshot();
  const periods = await Promise.all(runs.filter((run) => ids.includes(run.id)).flatMap((run) =>
    run.periods.map(async ({ key }) => ({
      id: run.id, key, dates: (await periodRows(path.join(runsRoot, run.id), key, "daily_returns.csv"))
        .map(dateOf).filter(Boolean).sort(),
    })),
  ));
  const starts = periods.flatMap(({ dates }) => dates[0] ? [dates[0]] : []).sort();
  const ends = periods.flatMap(({ dates }) => dates.at(-1) ? [dates.at(-1)!] : []).sort();
  if (!starts.length) return {};
  const closes = await closesFor(file, starts[0], ends.at(-1)!);
  const values: Record<string, Record<string, number | null>> = {};
  for (const { id, key, dates } of periods) {
    const last = benchmarkLine(closes, dates).at(-1);
    (values[id] ??= {})[key] = last ? last.value - 1 : null;
  }
  return values;
}

async function readPeriod(id: string, key: string) {
  if (!runId.test(id) || !/^(all|\d{4})$/.test(key)) throw new Error("잘못된 실행 또는 기간입니다.");
  const directory = path.join(runsRoot, id);
  if (!(await lstat(directory).catch(() => null))?.isDirectory()) throw new Error("실행을 찾을 수 없습니다.");
  const current = key === "all" ? directory : path.join(directory, "years", key);
  const metrics = await json<Values>(path.join(current, "backtest_metrics.json"));
  const { years } = (await json<Values>(path.join(directory, "backtest_metrics.json"))) ?? {};
  const summary = metrics ?? (Array.isArray(years) ? years.find((year) => String(year.year) === key) : null);
  const capital = number(summary?.initial_cash);
  const [values, returns, random, report] = await Promise.all([
    periodRows(directory, key, "equity_curve.csv"), periodRows(directory, key, "daily_returns.csv"),
    csv(path.join(current, "random_baseline.csv")),
    json<{ exclusions: { reason: string }[] }>(path.join(current, "execution_report.json")),
  ]);
  const equity = values.flatMap((row) => {
    const value = number(row.Equity);
    return capital && value !== null && dateOf(row) ? [{ date: dateOf(row), value: value / capital }] : [];
  });
  let rebase = 1;
  const benchmark = returns.flatMap((row) => {
    const value = number(row.Benchmark);
    if (value === null || !dateOf(row)) return [];
    rebase *= 1 + value;
    return [{ date: dateOf(row), value: rebase }];
  });
  const counts = new Map<string, number>();
  for (const item of report?.exclusions ?? []) {
    counts.set(item.reason, (counts.get(item.reason) ?? 0) + 1);
  }
  const exclusions = [...counts].map(([reason, count]) => ({ reason, count })).sort((a, b) => b.count - a.count);
  return { equity, benchmark, random, exclusions };
}

export async function readPeriods(ids: string[], key: string, selectedBenchmark?: string) {
  const results = await Promise.all(ids.map(async (id) => ({ id, data: await readPeriod(id, key) })));
  if (selectedBenchmark) {
    const dates = results.flatMap(({ data }) => data.equity.map(({ date }) => date)).sort();
    const closes = dates.length ? await closesFor(selectedBenchmark, dates[0], dates.at(-1)!) : [];
    for (const { data } of results) {
      data.benchmark = benchmarkLine(closes, data.equity.map(({ date }) => date).sort());
    }
  }
  return Object.fromEntries(results.map(({ id, data }) => [id, data]));
}

export async function readLog(id: string) {
  return jobId.test(id) ? (await file(path.join(jobsRoot, id + ".log")))?.slice(-16000) ?? "" : "";
}
