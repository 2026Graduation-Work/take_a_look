import json
import subprocess
import sys

import pytest
import yaml
from experiments import lab_read
from experiments import run_backtest as runner
from experiments.config import CHART_ROOT


def test_check_json_does_not_create_result_dir(tmp_path):
    source = CHART_ROOT / "experiments/configs/local_h5.yaml"
    config = yaml.safe_load(source.read_text())
    config["experiment_name"] = f"lab_check_{tmp_path.name}"
    config_path = tmp_path / "check.yaml"
    config_path.write_text(yaml.safe_dump(config))
    cache = tmp_path / "predictions.parquet"

    def check():
        result = subprocess.run(
            [sys.executable, "-m", "experiments.run_backtest", "--check", "--config",
             str(config_path), "--predictions-path", str(cache)],
            capture_output=True, text=True, cwd=CHART_ROOT,
        )
        assert len(result.stdout.splitlines()) == 1
        return result.returncode, json.loads(result.stdout)

    code, missing = check()
    assert code == 1
    assert missing == {
        "ok": False, "errors": missing["errors"], "result_dir": missing["result_dir"],
        "predictions_hash": missing["predictions_hash"], "cache_exists": False,
        "label_barrier_mismatch": False,
    }
    assert "experiments.train" in missing["errors"][0]
    cache.touch()
    code, ready = check()
    assert code == 0
    assert ready == {**missing, "ok": True, "errors": [], "cache_exists": True}
    assert not runner.Path(ready["result_dir"]).exists()
    config["backtest"]["up_mult"] *= 2
    config_path.write_text(yaml.safe_dump(config))
    code, mismatch = check()
    assert code == 1
    assert mismatch["label_barrier_mismatch"]
    assert not mismatch["ok"]


@pytest.mark.parametrize("malformed", ["key: [", "backtest: []\nlabels: []", "[]"])
def test_check_reports_invalid_yaml_as_a_failed_result(tmp_path, malformed):
    config = tmp_path / "bad.yaml"
    config.write_text(malformed)
    process = subprocess.run(
        [sys.executable, "-m", "experiments.run_backtest", "--check", "--config", str(config)],
        capture_output=True, text=True, cwd=CHART_ROOT,
    )
    assert process.returncode == 1
    assert len(process.stdout.splitlines()) == 1
    result = json.loads(process.stdout)
    assert not result["ok"]
    assert result["errors"]
    assert not result["label_barrier_mismatch"]


@pytest.mark.parametrize(("exception", "terminal"), [
    (None, "done"), (FileNotFoundError("missing cache; expected hash: ab"), "failed"),
    (KeyboardInterrupt(), "cancelled"),
])
def test_run_records_running_and_terminal_status(tmp_path, monkeypatch, exception, terminal):
    status_file = tmp_path / "backtest_status.json"
    monkeypatch.setattr(runner, "result_dir", lambda *_: tmp_path)

    def run(config, predictions, out, record):
        running = json.loads(status_file.read_text())
        assert running["status"] == "running"
        assert running["pid"] > 0
        assert running["finished_at"] is None
        record(progress={"year": [1, 2], "random": [2, 4]})
        if exception is not None:
            raise exception

    monkeypatch.setattr(runner, "_run_backtest", run)
    if exception is None:
        runner.run_local_backtest({}, config_path="local.yaml")
    else:
        with pytest.raises(type(exception)):
            runner.run_local_backtest({}, config_path="local.yaml")
    status = json.loads(status_file.read_text())
    assert status["status"] == terminal
    assert status["progress"] == {"year": [1, 2], "random": [2, 4]}
    assert status["finished_at"] >= status["started_at"]
    if terminal == "failed":
        assert status["error"] == {
            "reason": str(exception), "hint": "python -m experiments.train --config local.yaml",
        }


def test_benchmark_lists_allowed_files_and_returns_sorted_closes(tmp_path, monkeypatch):
    import pandas as pd

    monkeypatch.setattr(lab_read, "WORKSPACE", tmp_path)
    index = tmp_path / "datasets/test/benchmarks/KOSPI.parquet"
    index.parent.mkdir(parents=True)
    pd.DataFrame({"Date": ["2024-01-03", "2024-01-02", "2024-01-04"],
                  "Close": [105, 101, 107]}).to_parquet(index)
    assert lab_read.benchmarks() == [{"name": "KOSPI", "id": "datasets/test/benchmarks/KOSPI.parquet"}]
    assert lab_read.benchmark(lab_read.benchmarks()[0]["id"], "2024-01-02", "2024-01-03") == [
        {"date": "2024-01-02", "close": 101}, {"date": "2024-01-03", "close": 105},
    ]
    with pytest.raises(ValueError, match="Unknown benchmark"):
        lab_read.benchmark("../other.parquet", "2024-01-02", "2024-01-03")
