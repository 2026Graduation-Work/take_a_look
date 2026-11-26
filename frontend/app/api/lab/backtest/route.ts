import { spawn } from "node:child_process";
import { randomUUID } from "node:crypto";
import { lstat, realpath } from "node:fs/promises";
import path from "node:path";
import type { Base, Benchmark, Check } from "../../../lab/backtest/types";
import { activeJob, chart, ownsJob, python, readBenchmarkReturns, readLog, readPeriods, runId, runPython, runsRoot, snapshot } from "./artifacts";

export const runtime = "nodejs";

const basePath = /^(?:experiments\/configs|workspace\/experiments\/lab\/configs)\/[\p{L}\p{N}_.-]+\.yaml$/u;
const labConfigDir = "workspace/experiments/lab/configs";
const labConfigRoot = path.resolve(chart, labConfigDir);
const sourceConfigRoot = path.resolve(chart, "experiments/configs");
const localHost = /^(?:127\.0\.0\.1|localhost)(?::\d+)?$/;
const namePattern = /^[\p{L}\p{N}][\p{L}\p{N}_-]{0,63}$/u;

function guard(request: Request) {
  const host = request.headers.get("host") ?? "";
  const origin = request.headers.get("origin");
  if (process.env.NODE_ENV === "production" || process.env.BACKTEST_LAB_ENABLED !== "1" || !localHost.test(host)) {
    return new Response(null, { status: 404 });
  }
  if (origin && origin !== "http://" + host) return new Response(null, { status: 403 });
  return null;
}

function error(message: string, status = 400) {
  return Response.json({ error: message }, { status });
}

async function trustedConfig(id: unknown) {
  if (typeof id !== "string" || !basePath.test(id)) throw new Error("설정 파일을 찾을 수 없습니다.");
  const root = id.startsWith(labConfigDir + "/") ? labConfigRoot : sourceConfigRoot;
  const full = path.resolve(root, path.basename(id));
  if (!full.startsWith(root + path.sep)) throw new Error("설정 파일을 찾을 수 없습니다.");
  if (await realpath(root) !== root || await realpath(full) !== full || !(await lstat(full)).isFile()) {
    throw new Error("설정 파일을 찾을 수 없습니다.");
  }
  return id;
}

function minuteStamp() {
  const now = new Date();
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${now.getFullYear()}${pad(now.getMonth() + 1)}${pad(now.getDate())}-${pad(now.getHours())}${pad(now.getMinutes())}`;
}

async function newConfig(base: unknown, name: unknown, changes: unknown) {
  const id = await trustedConfig(base);
  if (typeof name !== "string" || !namePattern.test(name)) {
    throw new Error("이름은 글자나 숫자로 시작하고 글자, 숫자, 밑줄, 하이픈만 쓸 수 있습니다.");
  }
  if (!changes || typeof changes !== "object" || Array.isArray(changes) ||
      !Object.values(changes).every((value) => value === null || typeof value === "string" || typeof value === "number")) {
    throw new Error("설정 값이 올바르지 않습니다.");
  }
  const stem = minuteStamp() + "-" + name;
  const candidate = path.resolve(labConfigRoot, stem + ".yaml");
  if (!candidate.startsWith(labConfigRoot + path.sep)) throw new Error("설정 파일을 저장할 수 없습니다.");
  const realRoot = await realpath(labConfigRoot).catch((cause: NodeJS.ErrnoException) => {
    if (cause.code === "ENOENT") return null;
    throw cause;
  });
  if (realRoot !== null && realRoot !== labConfigRoot) throw new Error("설정 폴더가 올바르지 않습니다.");
  const collision = realRoot !== null && await lstat(candidate).catch(() => null);
  const output = `${labConfigDir}/${collision ? `${stem}-${randomUUID().slice(0, 8)}` : stem}.yaml`;
  const result = await runPython<{ config: string }>("experiments.lab_read", [
    "write-config", "--base", id, "--output", output, "--name", name,
  ], changes);
  return result.config;
}

async function checkConfig(config: string): Promise<Check> {
  const check = await runPython<Omit<Check, "config" | "existing">>("experiments.run_backtest", ["--check", "--config", config]);
  const directory = check.result_dir;
  if (directory && (path.dirname(directory) !== runsRoot ||
      (await realpath(directory).catch(() => directory)) !== directory)) {
    return { ...check, ok: false, config, existing: false, errors: [...check.errors, "실행 폴더가 올바르지 않습니다."] };
  }
  const existing = directory !== null && (await Promise.all(["backtest_metrics.json", "backtest_status.json"].map(
    (filename) => lstat(path.join(directory, filename)).then((info) => info.isFile()).catch(() => false),
  ))).some(Boolean);
  return { ...check, config, existing };
}

function launch(kind: "backtest" | "ml", config: string, overwrite: boolean) {
  const script = path.resolve(process.cwd(), "scripts/backtest-lab-job.py");
  return new Promise<{ run?: string; error?: string; status?: number }>((resolve, reject) => {
    const child = spawn(python, [script, randomUUID(), kind, config, overwrite ? "overwrite" : "preserve"], {
      cwd: chart, detached: true, stdio: ["ignore", "pipe", "pipe"],
    });
    let stdout = "";
    let stderr = "";
    child.stdout.setEncoding("utf8").on("data", (chunk: string) => {
      stdout += chunk;
      const ending = stdout.indexOf("\n");
      if (ending === -1) return;
      try {
        resolve(JSON.parse(stdout.slice(0, ending)));
      } catch {
        reject(new Error("실행 프로세스가 올바른 응답을 보내지 않았습니다."));
      }
      child.unref();
      child.stdout.removeAllListeners("data");
      child.stdout.resume();
    });
    child.stderr.setEncoding("utf8").on("data", (chunk: string) => { stderr += chunk; });
    child.once("error", reject);
    child.once("close", () => reject(new Error(stderr.trim().split("\n").at(-1) || "실행 프로세스가 종료되었습니다.")));
  });
}

export async function GET(request: Request) {
  const denied = guard(request);
  if (denied) return denied;
  const search = new URL(request.url).searchParams;
  try {
    switch (search.get("read")) {
      case "catalog": {
        const [bases, benchmarks] = await Promise.all([
          runPython<Base[]>("experiments.lab_read", ["bases"]),
          runPython<Benchmark[]>("experiments.lab_read", ["benchmarks"]),
        ]);
        return Response.json({ bases, benchmarks });
      }
      case "periods": {
        const ids = search.getAll("run");
        const year = search.get("year") ?? "";
        if (ids.length === 0 || ids.length > 6 || !ids.every((id) => runId.test(id)) || !/^(all|\d{4})$/.test(year)) {
          return error("실행을 1개부터 6개까지 고르고 기간을 지정하세요.");
        }
        return Response.json(await readPeriods(ids, year, search.get("benchmark") || undefined));
      }
      case "benchmark-returns": {
        const ids = search.getAll("run");
        const benchmark = search.get("benchmark");
        if (!benchmark || ids.length === 0 || ids.length > 6) return error("비교할 지수와 실행을 골라 주세요.");
        return Response.json(await readBenchmarkReturns(ids, benchmark));
      }
      case "log":
        return Response.json({ log: await readLog(search.get("id") ?? "") });
      default:
        return Response.json(await snapshot());
    }
  } catch (cause) {
    return error(cause instanceof Error ? cause.message : "실험실 데이터를 읽을 수 없습니다.", 500);
  }
}

export async function POST(request: Request) {
  const denied = guard(request);
  if (denied) return denied;
  if (request.headers.get("origin") !== "http://" + request.headers.get("host")) return error("로컬 요청이 아닙니다.", 403);
  if (!request.headers.get("content-type")?.startsWith("application/json")) return error("JSON 요청이 필요합니다.", 415);
  try {
    const body = await request.json();
    if (body.action === "check") return Response.json(await checkConfig(await newConfig(body.base, body.name, body.changes)));
    if (body.action === "cancel") {
      const job = await activeJob();
      if (!job || job.id !== body.id || job.status !== "running" || !ownsJob(job)) {
        return error("취소할 실행이 없습니다.", 409);
      }
      process.kill(job.pid, "SIGTERM");
      return Response.json({ ok: true });
    }
    if (body.action !== "run" && body.action !== "ml") return error("지원하지 않는 작업입니다.");
    const config = await trustedConfig(body.config);
    if (body.action === "run" && !config.startsWith(labConfigDir + "/")) {
      return error("새 실행 화면에서 설정을 먼저 검사하세요.");
    }
    if (body.action === "ml") {
      const check = await checkConfig(config);
      if (!check.ok || !/^[0-9a-f]{8}$/.test(body.hash ?? "") || check.predictions_hash !== body.hash) {
        return error("이 모델의 예측 캐시와 일치하는 설정이 없습니다.");
      }
    }
    const result = await launch(body.action === "ml" ? "ml" : "backtest", config, body.overwrite === true);
    return result.error ? error(result.error, result.status) : Response.json(result, { status: 202 });
  } catch (cause) {
    return error(cause instanceof Error ? cause.message : "작업을 시작할 수 없습니다.");
  }
}
