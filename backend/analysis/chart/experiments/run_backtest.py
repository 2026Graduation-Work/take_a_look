import argparse
import json
import os
import shlex
import signal
import subprocess
import sys
from contextlib import redirect_stdout
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd
import yaml
from experiments.backtest.engine import configured_benchmark
from experiments.evaluation.backtest_metrics import calculate_trading_metrics
from experiments.evaluation.random_baseline import compare_with_random
from experiments.experiment_utils import (
    cache_dir,
    find_processed_dir,
    generate_predictions_hash,
    load_predictions,
    load_universe_intervals,
    resolve_splits,
    resolve_tickers,
    result_dir,
    result_path,
    test_date_bounds,
    validate_embargo,
)
from experiments.train_src.loaders import load_parquet_data
from experiments.train_src.swing_strategy import SwingStrategy
from shared.io import atomic_json


def _run_local_period(config, predictions, prices, out, on_progress=None):
    from experiments.backtest.local_execution import (
        PositionCrossesTrainingSegment,
        save_execution,
        simulate,
    )

    if predictions.empty or prices.empty:
        raise ValueError("Backtest period has no predictions/prices")
    Path(out).mkdir(parents=True, exist_ok=True)
    entries = SwingStrategy(config).generate_signals(predictions, prices)
    try:
        result = simulate(config, entries, prices)
        returns = result.returns()
        metrics = calculate_trading_metrics(returns, result.trades)
        metrics["turnover"] = result.turnover()
        benchmark = configured_benchmark(config, returns.index, prices)
        metrics["benchmark"] = calculate_trading_metrics(benchmark)
        metrics["initial_cash"] = config["backtest"]["initial_cash"]
        metrics["final_equity"] = float(result.value().iloc[-1])
        metrics["unclosed_positions"] = len(result.open_positions)
        runs = config.get("evaluation", {}).get("random_baseline_runs", 0)
        if runs:
            summary, distribution = compare_with_random(
                config, predictions, prices, result, metrics, runs, on_progress=on_progress,
            )
            metrics.update(summary)
    except PositionCrossesTrainingSegment as exc:
        atomic_json(Path(out) / "execution_error.json", {**exc.details, "message": str(exc)})
        raise
    except Exception as exc:
        atomic_json(Path(out) / "execution_error.json", {"reason": str(exc), "config": config})
        raise
    save_execution(result, out)
    if runs:
        distribution.to_csv(Path(out) / "random_baseline.csv", index=False)
    (Path(out) / "execution_error.json").unlink(missing_ok=True)
    pd.DataFrame({"Portfolio": returns, "Benchmark": benchmark}).to_csv(
        Path(out) / "daily_returns.csv"
    )
    atomic_json(Path(out) / "backtest_metrics.json", metrics)
    return metrics


def _stamp():
    return datetime.now(UTC).isoformat()


def _code_commit():
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=Path(__file__).resolve().parent,
            text=True, stderr=subprocess.DEVNULL,
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def run_local_backtest(config, predictions_path=None, *, config_path=None):
    out = Path(result_dir(config, __file__))
    status = {
        "status": "running", "pid": os.getpid(), "started_at": _stamp(), "finished_at": None,
        "code_commit": _code_commit(), "progress": {"year": [0, 0], "random": [0, 0]}, "error": None,
    }

    def record(**updates):
        status.update(updates)
        atomic_json(out / "backtest_status.json", status)

    record()
    try:
        _run_backtest(config, predictions_path, out, record)
    except KeyboardInterrupt:
        record(status="cancelled", finished_at=_stamp())
        raise
    except Exception as exc:
        hint = (
            f"python -m experiments.train --config {shlex.quote(str(config_path))}"
            if isinstance(exc, FileNotFoundError) and "expected hash:" in str(exc) and config_path
            else None
        )
        record(status="failed", finished_at=_stamp(), error={"reason": str(exc), "hint": hint})
        raise
    else:
        record(status="done", finished_at=_stamp())


def _run_backtest(config, predictions_path, out, record):

    splits = resolve_splits(config)
    if not validate_embargo(splits, config["data"].get("embargo_days", 7)):
        raise ValueError("Invalid embargo")
    predictions = load_predictions(config, splits, __file__, predictions_path)
    start, end = test_date_bounds(splits)
    prices = load_parquet_data(
        find_processed_dir(config, __file__), start, end,
        columns_only=["Date", "Code", "Open", "High", "Low", "Close", "Sigma", "Trading_Halt",
                      "Amount", "SegmentId"],
        tickers=resolve_tickers(config, __file__), strict=True,
        universe_intervals=load_universe_intervals(config),
    )
    runs = config.get("evaluation", {}).get("random_baseline_runs", 0)

    def run_period(index, count, period_predictions, period_prices, period_out):
        def progress(done, total):
            record(progress={"year": [index, count], "random": [done, total]})

        progress(0, runs)
        return _run_local_period(config, period_predictions, period_prices, period_out, progress)

    if config["backtest"].get("capital_mode", "continuous") == "continuous":
        run_period(1, 1, predictions, prices, out)
    else:
        summaries = []
        # Generate signals separately within each calendar year. Lagged signals,
        # cash and open positions therefore cannot cross annual boundaries.
        years = sorted(pd.to_datetime(predictions.Date).dt.year.unique())
        if not years:
            raise ValueError("Backtest period has no predictions/prices")
        for index, year in enumerate(years, start=1):
            period_predictions = predictions.loc[pd.to_datetime(predictions.Date).dt.year.eq(year)]
            period_prices = prices.loc[pd.to_datetime(prices.Date).dt.year.eq(year)]
            period_out = out / "years" / str(year)
            metrics = run_period(index, len(years), period_predictions, period_prices, period_out)
            summaries.append({"year": int(year), "start": str(period_prices.Date.min().date()),
                              "end": str(period_prices.Date.max().date()),
                              "prediction_rows": len(period_predictions),
                              "fold_ids": sorted(period_predictions.fold_id.unique().tolist()),
                              **metrics})
        pd.DataFrame([{k: v for k, v in row.items() if k not in {"benchmark", "fold_ids"}}
                      for row in summaries]).to_csv(out / "backtest_metrics_by_year.csv", index=False)
        atomic_json(out / "backtest_metrics.json", {
            "capital_mode": "independent_year", "initial_cash_per_year": config["backtest"]["initial_cash"],
            "years": summaries, "end_valuation": "each year final close",
            "cash_and_positions_carried": False,
        })
        for filename in ["orders.csv", "trades.csv", "equity_curve.csv", "daily_returns.csv"]:
            parts = []
            for row in summaries:
                try:
                    frame = pd.read_csv(out / "years" / str(row["year"]) / filename)
                except pd.errors.EmptyDataError:
                    frame = pd.DataFrame()
                frame.insert(0, "year", row["year"])
                parts.append(frame)
            pd.concat(parts, ignore_index=True).to_csv(out / filename, index=False)
    print(f"Backtest results: {out}")


def main(config_path, predictions_path=None):
    print(f"[*] Loading config from {config_path}...")
    from experiments.config import load_experiment_config

    config = load_experiment_config(config_path)
    return run_local_backtest(config, predictions_path, config_path=config_path)


def check_backtest(config_path, predictions_path=None):
    from experiments.config import (
        load_experiment_config,
        read_yaml,
        validate_backtest_label_alignment,
    )

    result = {
        "ok": False, "errors": [], "result_dir": None, "predictions_hash": None,
        "cache_exists": False, "label_barrier_mismatch": False,
    }
    try:
        config = load_experiment_config(config_path)
    except Exception as exc:
        result["errors"].append(str(exc))
        try:
            source = read_yaml(config_path)
            validate_backtest_label_alignment(source["backtest"], source["labels"])
        except ValueError as alignment_error:
            result["label_barrier_mismatch"] = "must equal labels." in str(alignment_error)
        except (AttributeError, KeyError, TypeError, OSError, yaml.YAMLError):
            pass
        return result
    try:
        splits = resolve_splits(config)
        result["result_dir"] = str(result_path(config, __file__))
        if not splits or not validate_embargo(splits, config["data"].get("embargo_days", 7)):
            result["errors"].append("Invalid or empty evaluation splits")
        pred_hash = generate_predictions_hash(config, splits)
        result["predictions_hash"] = pred_hash
        cache = Path(predictions_path) if predictions_path else (
            Path(cache_dir(__file__, create=False)) / f"{pred_hash}_predictions.parquet"
        )
        result["cache_exists"] = cache.is_file()
        if not result["cache_exists"]:
            result["errors"].append(
                f"예측 결과 캐시를 찾을 수 없습니다. python -m experiments.train --config "
                f"{shlex.quote(str(config_path))}"
            )
    except Exception as exc:
        result["errors"].append(str(exc))
    result["ok"] = not result["errors"]
    return result


def _cancel(_signum, _frame):
    raise KeyboardInterrupt


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=str, required=True, help="Path to config yaml")
    parser.add_argument("--check", action="store_true", help="Check config and prediction cache only")
    parser.add_argument(
        "--predictions-path",
        type=str,
        default=None,
        help="Path to pre-computed predictions parquet file",
    )
    args = parser.parse_args()
    if args.check:
        with redirect_stdout(sys.stderr):
            check = check_backtest(args.config, args.predictions_path)
        print(json.dumps(check, ensure_ascii=False))
        sys.exit(0 if check["ok"] else 1)
    signal.signal(signal.SIGTERM, _cancel)
    main(args.config, args.predictions_path)
