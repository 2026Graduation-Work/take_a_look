export type Values = Record<string, unknown>;
export type Config = Record<string, Values>;
export type RunState = "queued" | "running" | "done" | "failed" | "cancelled";
export interface Status {
  status: RunState;
  pid: number | null;
  started_at: string | null;
  finished_at: string | null;
  code_commit: string | null;
  progress: { year: [number, number]; random: [number, number] };
  error: { reason: string; hint: string | null } | null;
}
export interface Period {
  key: string;
  year: number | null;
  start: string | null;
  end: string | null;
  metrics: Values;
}
export interface Run {
  id: string;
  name: string;
  config: Config;
  hash: string;
  status: Status;
  periods: Period[];
  configPath?: string;
  jobId?: string;
}
export interface Model {
  hash: string;
  name: string;
  summary: Values | null;
  folds: Values[];
  calibration: { bin: string; x: number; y: number; count: number }[];
  featureColumns: string[];
}
export interface Benchmark {
  id: string;
  name: string;
}
export interface Base {
  id: string;
  name: string;
  config: Config;
  years: number[];
}
export interface Check {
  ok: boolean;
  errors: string[];
  result_dir: string | null;
  predictions_hash: string | null;
  cache_exists: boolean;
  label_barrier_mismatch: boolean;
  config: string;
  existing: boolean;
}
export interface Job {
  id: string;
  kind: "backtest" | "ml";
  run: string;
  config: string;
  pid: number;
  status: RunState;
  started_at: string;
  finished_at: string | null;
  error: string | null;
}
export interface Snapshot {
  runs: Run[];
  models: Model[];
  job: Job | null;
  observed_at: number;
}
export interface Point {
  date: string;
  value: number;
}
export interface PeriodData {
  equity: Point[];
  benchmark: Point[];
  random: Values[];
  exclusions: { reason: string; count: number }[];
}
