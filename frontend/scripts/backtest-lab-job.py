import fcntl
import json
import os
import signal
import sys
from contextlib import redirect_stderr, redirect_stdout
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, os.getcwd())

from experiments import run_backtest
from experiments.run_ml_evaluation import main as evaluate
from shared.io import atomic_json


def now():
    return datetime.now(UTC).isoformat()


def job(job_id, kind, config, overwrite):
    jobs = Path("workspace/experiments/lab/jobs")
    jobs.mkdir(parents=True, exist_ok=True)
    with (jobs / "active.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return {"error": "이미 실행 중인 작업이 있습니다.", "status": 409}
        check = run_backtest.check_backtest(config)
        if not check["ok"]:
            return {"error": "\n".join(check["errors"]), "status": 400}
        result = Path(check["result_dir"])
        runs = (Path.cwd() / "workspace/experiments/runs").resolve()
        if result.resolve().parent != runs or result.is_symlink():
            return {"error": "실행 폴더가 올바르지 않습니다.", "status": 400}
        status_file = result / "backtest_status.json"
        if kind == "backtest":
            if status_file.is_file():
                old_status = json.loads(status_file.read_text())
                if old_status["status"] in {"queued", "running"}:
                    try:
                        os.kill(old_status["pid"], 0)
                    except ProcessLookupError:
                        pass
                    else:
                        return {"error": "이 결과 폴더에서 이미 실행 중입니다.", "status": 409}
            if any(path.exists() for path in (status_file, result / "backtest_metrics.json")) and not overwrite:
                return {"error": f"결과를 덮어쓰려면 확인이 필요합니다. {result.name}", "status": 409}

        metadata = {
            "id": job_id, "kind": kind, "run": result.name, "config": config,
            "pid": os.getpid(), "status": "running", "started_at": now(),
            "finished_at": None, "error": None,
        }
        job_file = jobs / f"{job_id}.json"
        atomic_json(job_file, metadata)
        atomic_json(jobs / "active.json", metadata)

        def interrupt(_signum, _frame):
            raise KeyboardInterrupt

        signal.signal(signal.SIGTERM, interrupt)
        try:
            if kind == "backtest":
                atomic_json(status_file, {
                    "status": "queued", "pid": metadata["pid"], "started_at": None,
                    "finished_at": None, "code_commit": None,
                    "progress": {"year": [0, 0], "random": [0, 0]}, "error": None,
                })
            print(json.dumps({"run": result.name}), flush=True)
            with (jobs / f"{job_id}.log").open("x", buffering=1) as log, redirect_stdout(log), redirect_stderr(log):
                os.dup2(log.fileno(), 1)
                os.dup2(log.fileno(), 2)
                try:
                    (run_backtest.main if kind == "backtest" else evaluate)(config)
                except BaseException:
                    import traceback

                    traceback.print_exc()
                    raise
            metadata["status"] = "done"
        except KeyboardInterrupt:
            metadata["status"] = "cancelled"
        except Exception as exc:
            metadata.update(status="failed", error=str(exc))
        finally:
            metadata["finished_at"] = now()
            if kind == "backtest" and status_file.is_file():
                previous = json.loads(status_file.read_text())
                if previous["status"] in {"queued", "running"}:
                    atomic_json(status_file, {
                        **previous, "status": metadata["status"], "finished_at": metadata["finished_at"],
                        "error": {"reason": metadata["error"], "hint": None} if metadata["error"] else None,
                    })
            atomic_json(job_file, metadata)
            atomic_json(jobs / "active.json", metadata)
        return None


if __name__ == "__main__":
    response = job(*sys.argv[1:4], overwrite=sys.argv[4] == "overwrite")
    if response is not None:
        print(json.dumps(response, ensure_ascii=False), flush=True)
