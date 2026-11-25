import argparse
from pathlib import Path

import pandas as pd
from experiments.backtest.engine import configured_benchmark
from experiments.evaluation.backtest_metrics import calculate_trading_metrics
from experiments.experiment_utils import (
    find_processed_dir,
    load_predictions,
    load_universe_intervals,
    resolve_splits,
    resolve_tickers,
    result_dir,
    test_date_bounds,
    validate_embargo,
)
from experiments.train_src.loaders import load_parquet_data
from experiments.train_src.swing_strategy import SwingStrategy


def _run_local_period(config, predictions, prices, out):
    from experiments.backtest.local_execution import save_execution, simulate
    from shared.io import atomic_json

    if predictions.empty or prices.empty:
        raise ValueError("Backtest period has no predictions/prices")
    Path(out).mkdir(parents=True, exist_ok=True)
    entries = SwingStrategy(config).generate_signals(predictions, prices)
    try:
        result = simulate(config, entries, prices)
    except Exception as exc:
        atomic_json(Path(out) / "execution_error.json", {"reason": str(exc), "config": config})
        raise
    save_execution(result, out)
    returns = result.returns()
    metrics = calculate_trading_metrics(returns, result.trades)
    metrics["turnover"] = result.turnover()
    benchmark = configured_benchmark(config, returns.index, prices)
    metrics["benchmark"] = calculate_trading_metrics(benchmark)
    metrics["initial_cash"] = config["backtest"]["initial_cash"]
    metrics["final_equity"] = float(result.value().iloc[-1])
    metrics["unclosed_positions"] = len(result.open_positions)
    atomic_json(Path(out) / "backtest_metrics.json", metrics)
    (Path(out) / "execution_error.json").unlink(missing_ok=True)
    pd.DataFrame({"Portfolio": returns, "Benchmark": benchmark}).to_csv(
        Path(out) / "daily_returns.csv"
    )
    return metrics


def run_local_backtest(config, predictions_path=None):
    from shared.io import atomic_json

    splits = resolve_splits(config)
    if not validate_embargo(splits, config["data"].get("embargo_days", 7)):
        raise ValueError("Invalid embargo")
    predictions = load_predictions(config, splits, __file__, predictions_path)
    start, end = test_date_bounds(splits)
    prices = load_parquet_data(
        find_processed_dir(config, __file__), start, end,
        columns_only=["Date", "Code", "Open", "High", "Low", "Close", "Sigma", "Trading_Halt"],
        tickers=resolve_tickers(config, __file__), strict=True,
        universe_intervals=load_universe_intervals(config),
    )
    out = Path(result_dir(config, __file__))
    if config["backtest"].get("capital_mode", "continuous") == "continuous":
        _run_local_period(config, predictions, prices, out)
    else:
        summaries = []
        # Generate signals separately within each calendar year. Lagged signals,
        # cash and open positions therefore cannot cross annual boundaries.
        for year in sorted(pd.to_datetime(predictions.Date).dt.year.unique()):
            period_predictions = predictions.loc[pd.to_datetime(predictions.Date).dt.year.eq(year)]
            period_prices = prices.loc[pd.to_datetime(prices.Date).dt.year.eq(year)]
            period_out = out / "years" / str(year)
            metrics = _run_local_period(config, period_predictions, period_prices, period_out)
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
    return run_local_backtest(config, predictions_path)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=str, required=True, help="Path to config yaml")
    parser.add_argument(
        "--predictions-path",
        type=str,
        default=None,
        help="Path to pre-computed predictions parquet file",
    )
    args = parser.parse_args()
    main(args.config, args.predictions_path)
