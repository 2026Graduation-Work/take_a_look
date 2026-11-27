import argparse
import json
import math
import sys
from contextlib import redirect_stdout
from datetime import date

import pandas as pd
import yaml
from experiments.config import CHART_ROOT, load_experiment_config, read_yaml
from experiments.experiment_utils import resolve_splits

WORKSPACE = CHART_ROOT / "workspace/experiments"
CONFIG_ROOTS = (CHART_ROOT / "experiments/configs", WORKSPACE / "lab/configs")
EDITABLE = {
    "strategy": {"top_n", "prob_threshold", "score_column"},
    "backtest": {
        "max_holding_days", "up_mult", "down_mult", "hard_sl_mult", "capital_mode",
        "initial_cash", "fee", "slippage_bps", "max_participation",
    },
    "evaluation": {"random_baseline_runs", "benchmark_file"},
}


def benchmarks():
    parent = (WORKSPACE / "datasets").resolve()
    return [
        {"id": path.relative_to(WORKSPACE).as_posix(), "name": path.stem}
        for path in sorted((WORKSPACE / "datasets").glob("*/benchmarks/*.parquet"))
        if path.is_file() and path.resolve().is_relative_to(parent)
    ]


def benchmark(file, start, end):
    permitted = {entry["id"] for entry in benchmarks()}
    if file not in permitted:
        candidate = (CHART_ROOT / file).resolve()
        if candidate.is_relative_to(WORKSPACE.resolve()):
            file = candidate.relative_to(WORKSPACE.resolve()).as_posix()
    if file not in permitted:
        raise ValueError("Unknown benchmark file")
    start, end = date.fromisoformat(start), date.fromisoformat(end)
    if start > end:
        raise ValueError("Invalid benchmark date range")
    frame = pd.read_parquet(WORKSPACE / file, columns=["Date", "Close"])
    frame["Date"] = pd.to_datetime(frame["Date"]).dt.tz_localize(None).dt.normalize()
    if frame.Date.duplicated().any():
        raise ValueError("Duplicate benchmark dates")
    if not frame.Close.map(math.isfinite).all() or (frame.Close <= 0).any():
        raise ValueError("Invalid benchmark close")
    frame = frame.loc[frame.Date.between(pd.Timestamp(start), pd.Timestamp(end))]
    return [{"date": row.Date.strftime("%Y-%m-%d"), "close": row.Close}
            for row in frame.sort_values("Date").itertuples()]


def bases():
    entries = []
    for root in CONFIG_ROOTS:
        for path in sorted(root.glob("*.yaml")):
            if not path.resolve().is_relative_to(root.resolve()):
                continue
            try:
                config = load_experiment_config(path)
                splits = resolve_splits(config)
            except (OSError, ValueError, KeyError, TypeError, yaml.YAMLError):
                continue
            years = sorted({
                year for split in splits
                for year in range(int(str(split["test_start"])[:4]), int(str(split["test_end"])[:4]) + 1)
            })
            entries.append({
                "id": path.relative_to(CHART_ROOT).as_posix(),
                "name": config.get("experiment_name", path.stem),
                "config": {key: config[key] for key in ("data", "labels", "features", "model", "strategy",
                                                       "backtest", "evaluation")},
                "years": years,
            })
    return entries


def write_config(base, output, name, changes):
    base = CHART_ROOT / base
    path = CHART_ROOT / output
    if (
        base.parent.resolve() not in CONFIG_ROOTS or base.suffix != ".yaml"
        or not base.resolve().is_relative_to(base.parent.resolve())
    ):
        raise ValueError("Unknown base config")
    if path.parent.resolve() != CONFIG_ROOTS[1] or path.suffix != ".yaml":
        raise ValueError("Invalid config output")
    config = read_yaml(base)
    config["experiment_name"] = name
    for key, value in changes.items():
        section, _, field = key.partition(".")
        if field not in EDITABLE.get(section, set()):
            raise ValueError(f"Unsupported setting: {key}")
        if key == "evaluation.benchmark_file":
            if value not in {entry["id"] for entry in benchmarks()}:
                raise ValueError("Unknown benchmark file")
            value = f"workspace/experiments/{value}"
        config[section][field] = value
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as handle:
        yaml.safe_dump(config, handle, allow_unicode=True, sort_keys=False)
    return {"config": path.relative_to(CHART_ROOT).as_posix()}


def main():
    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("benchmarks")
    commands.add_parser("bases")
    index = commands.add_parser("benchmark")
    index.add_argument("--file", required=True)
    index.add_argument("--start", required=True)
    index.add_argument("--end", required=True)
    config = commands.add_parser("write-config")
    config.add_argument("--base", required=True)
    config.add_argument("--output", required=True)
    config.add_argument("--name", required=True)
    args = parser.parse_args()
    with redirect_stdout(sys.stderr):
        if args.command == "benchmarks":
            result = benchmarks()
        elif args.command == "benchmark":
            result = benchmark(args.file, args.start, args.end)
        elif args.command == "bases":
            result = bases()
        else:
            result = write_config(args.base, args.output, args.name, json.load(sys.stdin))
    print(json.dumps(result, ensure_ascii=False, default=str, allow_nan=False))


if __name__ == "__main__":
    main()
