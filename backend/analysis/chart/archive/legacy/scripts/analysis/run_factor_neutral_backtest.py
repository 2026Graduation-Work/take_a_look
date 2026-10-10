import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

CURRENT_DIR = Path(__file__).resolve().parent
EXPERIMENTS_DIR = CURRENT_DIR.parents[1]
if str(EXPERIMENTS_DIR) not in sys.path:
    sys.path.insert(0, str(EXPERIMENTS_DIR))

# These imports support direct execution via ``python run_factor_neutral_backtest.py``.
from backtest.engine import VectorBTEngine, compute_custom_krx_composite  # noqa: E402, I001
from evaluation.backtest_metrics import calculate_trading_metrics  # noqa: E402
from experiment_utils import (  # noqa: E402
    build_fold_alignment,
    label_params_from_config,
    resolve_splits,
    test_date_bounds,
)
from run_factor_attribution import (  # noqa: E402
    CHART_ROOT,
    EXPERIMENTS_DIR,
    EXPOSURE_COLUMNS,
    add_exposures,
    load_final_experiments,
    load_metadata,
    load_panel,
    markdown_table,
    normalize_code,
)
from train_src.loaders import load_parquet_data  # noqa: E402
from train_src.swing_strategy import SwingStrategy  # noqa: E402


DEFAULT_OUTPUT_DIR = EXPERIMENTS_DIR / "results" / "factor_neutral_backtest"


def log(message: str) -> None:
    print(message, flush=True)


def cross_sectional_residuals(group: pd.DataFrame, xcols: list[str]) -> pd.Series:
    data = group[["Prob"] + xcols].replace([np.inf, -np.inf], np.nan).dropna()
    result = pd.Series(np.nan, index=group.index)
    if len(data) <= len(xcols) + 5:
        return result
    x = np.column_stack([np.ones(len(data)), data[xcols].to_numpy(dtype=float)])
    y = data["Prob"].to_numpy(dtype=float)
    beta = np.linalg.pinv(x.T @ x) @ x.T @ y
    result.loc[data.index] = y - x @ beta
    return result


def build_neutral_predictions(
    predictions_path: Path,
    panel: pd.DataFrame,
    output_path: Path,
    exposures: list[str],
    prob_threshold: float,
) -> pd.DataFrame:
    preds = pd.read_parquet(predictions_path, columns=["Date", "Code", "Prob"])
    preds["Date"] = pd.to_datetime(preds["Date"]).dt.tz_localize(None)
    preds["Code"] = preds["Code"].map(normalize_code)

    base = panel[["Date", "Code"] + exposures]
    merged = preds.merge(base, on=["Date", "Code"], how="inner")
    usable = [col for col in exposures if merged[col].notna().sum() > 100]
    if not usable:
        raise ValueError("No usable exposure columns for factor-neutral regression")

    log(f"  neutralizing {predictions_path.name} with exposures={usable}")
    merged["Residual"] = merged.groupby("Date", group_keys=False).apply(
        lambda group: cross_sectional_residuals(group, usable)
    )
    eligible = merged["Prob"] >= prob_threshold
    merged["NeutralProb"] = 0.0
    eligible_rank = merged[eligible].groupby("Date")["Residual"].rank(pct=True, method="first")
    # Preserve the raw model's threshold gate, then use residual ranks only to choose top-N.
    merged.loc[eligible_rank.index, "NeutralProb"] = prob_threshold + (1.0 - prob_threshold) * eligible_rank
    neutral = merged[["Date", "Code", "NeutralProb"]].rename(columns={"NeutralProb": "Prob"})
    neutral = neutral.dropna(subset=["Prob"]).sort_values(["Date", "Code"]).reset_index(drop=True)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    neutral.to_parquet(output_path, index=False)
    return neutral


def write_backtest_config(
    source_config_path: Path, output_path: Path, experiment_name: str, description_suffix: str
) -> dict:
    with source_config_path.open(encoding="utf-8") as handle:
        config = yaml.safe_load(handle)
    config["experiment_name"] = experiment_name
    config.setdefault("description", "")
    config["description"] = (str(config["description"]) + f" | {description_suffix}").strip()
    config.setdefault("strategy", {})
    config["strategy"]["score_column"] = "Prob"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as handle:
        yaml.safe_dump(config, handle, allow_unicode=True, sort_keys=False)
    return config


def load_json(path: Path) -> dict:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def summarize_backtest_result(result_dir: Path, label: str, horizon: str, source_experiment: str) -> dict:
    metrics = load_json(result_dir / "backtest_metrics_summary.json")
    trades_path = result_dir / "trades.csv"
    trades = pd.read_csv(trades_path) if trades_path.exists() else pd.DataFrame()
    return {
        "horizon": horizon,
        "variant": label,
        "source_experiment": source_experiment,
        "result_dir": str(result_dir),
        "total_return": metrics.get("trade_total_return"),
        "cagr": metrics.get("trade_cagr"),
        "sharpe": metrics.get("trade_sharpe_ratio"),
        "max_drawdown": metrics.get("trade_max_drawdown"),
        "win_rate": metrics.get("trade_win_rate"),
        "num_trades": metrics.get("trade_num_trades", len(trades)),
        "benchmark_custom_krx_total_return": metrics.get("benchmark_custom_krx_total_return"),
        "fold_alignment_exact": metrics.get("fold_alignment_exact"),
    }


def run_engine_only_backtest(config_path: Path, predictions_path: Path, result_dir: Path) -> None:
    with config_path.open(encoding="utf-8") as handle:
        config = yaml.safe_load(handle)
    splits = resolve_splits(config)
    predictions = pd.read_parquet(predictions_path)
    predictions["Date"] = pd.to_datetime(predictions["Date"]).dt.tz_localize(None)
    predictions["Code"] = predictions["Code"].map(normalize_code)
    predictions = predictions.sort_values(["Date", "Code"]).reset_index(drop=True)

    alignment_df, alignment_status = build_fold_alignment(predictions, splits)
    if not alignment_status["is_exact_fold_match"]:
        raise ValueError(f"Neutral prediction fold alignment failed: {alignment_status}")

    full_test_start, full_test_end = test_date_bounds(splits)
    price_cols = ["Date", "Code", "Open", "High", "Low", "Close", "Sigma", "Trading_Halt"]
    market_df = load_parquet_data(
        str(CHART_ROOT / config.get("data", {}).get("price_dir", "data/processed")),
        full_test_start,
        full_test_end,
        columns_only=price_cols,
        tickers=config.get("data", {}).get("tickers", None),
        label_params=label_params_from_config(config),
    )
    market_df["Date"] = pd.to_datetime(market_df["Date"]).dt.tz_localize(None)

    strategy = SwingStrategy(config)
    entries, weights = strategy.generate_signals(predictions, market_df)
    engine = VectorBTEngine(config)
    pf = engine.run(entries, weights, market_df, generate_report=False)

    daily_returns = pf.returns()
    daily_returns.index = pd.to_datetime(daily_returns.index).tz_localize(None)
    trades = pf.trades.records_readable if len(pf.trades.records) > 0 else pd.DataFrame()
    ew_benchmark = pf.benchmark_returns()
    custom_krx = compute_custom_krx_composite(daily_returns.index, market_df)
    metrics = calculate_trading_metrics(daily_returns, trades)
    krx_metrics = calculate_trading_metrics(custom_krx)

    summary = {f"trade_{key}": value for key, value in metrics.items()}
    summary.update(
        {
            "fold_alignment_exact": bool(alignment_status["is_exact_fold_match"]),
            **{f"fold_alignment_{key}": value for key, value in alignment_status.items()},
            **{f"benchmark_custom_krx_{key}": value for key, value in krx_metrics.items()},
            "benchmark_custom_krx_source": custom_krx.attrs.get("benchmark_source", "unknown"),
            "benchmark_custom_krx_valid": custom_krx.attrs.get("benchmark_valid", False),
            "benchmark_custom_krx_validity_reason": custom_krx.attrs.get("benchmark_validity_reason", ""),
        }
    )

    result_dir.mkdir(parents=True, exist_ok=True)
    alignment_df.to_csv(result_dir / "fold_alignment.csv", index=False)
    trades.to_csv(result_dir / "trades.csv", index=False)
    pd.DataFrame(
        {
            "Portfolio": daily_returns,
            "Benchmark_EW": ew_benchmark,
            "Benchmark_CustomKRX": custom_krx,
        }
    ).to_csv(result_dir / "daily_returns.csv", index_label="Date")
    with (result_dir / "backtest_metrics_summary.json").open("w", encoding="utf-8") as handle:
        json.dump(summary, handle, ensure_ascii=False, indent=2, default=lambda x: x.item() if hasattr(x, "item") else x)
    with (result_dir / "config_snapshot.yaml").open("w", encoding="utf-8") as handle:
        yaml.safe_dump(config, handle, allow_unicode=True, sort_keys=False)


def write_summary_report(summary: pd.DataFrame, output_dir: Path) -> None:
    pivot = summary.pivot_table(
        index="horizon",
        columns="variant",
        values=["total_return", "cagr", "sharpe", "max_drawdown", "num_trades"],
        aggfunc="first",
    )
    pivot.columns = [f"{metric}_{variant}" for metric, variant in pivot.columns]
    pivot = pivot.reset_index()
    if {"sharpe_raw", "sharpe_factor_neutral"}.issubset(pivot.columns):
        pivot["sharpe_delta_neutral_minus_raw"] = pivot["sharpe_factor_neutral"] - pivot["sharpe_raw"]
    if {"total_return_raw", "total_return_factor_neutral"}.issubset(pivot.columns):
        pivot["total_return_delta_neutral_minus_raw"] = (
            pivot["total_return_factor_neutral"] - pivot["total_return_raw"]
        )

    lines = [
        "# Factor-Neutral Backtest Report",
        "",
        "## Method",
        "",
        "- Raw rows are re-run with the same fixed project backtest engine used for factor-neutral rows.",
        "- Factor-neutral rows preserve the raw `Prob >= threshold` eligibility gate, regress `Prob` cross-sectionally by date on representative exposures, rank eligible names by residual score, then run the same `SwingStrategy` and `VectorBTEngine` rules.",
        "- Engine fixes in this run: close-based daily valuation, synchronized stop/soft/time exits, and no future delisting snapshot in distress exposure.",
        "- This is an actual backtest-engine run, not a next-day top-k approximation.",
        "",
        "## Summary",
        "",
        markdown_table(summary),
        "",
        "## Raw vs Factor-Neutral Pivot",
        "",
        markdown_table(pivot),
        "",
        "## Interpretation",
        "",
        interpret_summary(pivot),
    ]
    (output_dir / "factor_neutral_backtest_report.md").write_text("\n".join(lines), encoding="utf-8")


def interpret_summary(pivot: pd.DataFrame) -> str:
    rows = []
    for _, row in pivot.iterrows():
        horizon = row["horizon"]
        raw_sharpe = row.get("sharpe_raw", np.nan)
        neutral_sharpe = row.get("sharpe_factor_neutral", np.nan)
        raw_return = row.get("total_return_raw", np.nan)
        neutral_return = row.get("total_return_factor_neutral", np.nan)
        if pd.isna(neutral_sharpe):
            verdict = "neutral result unavailable"
        elif neutral_sharpe > 0.8 * raw_sharpe and neutral_return > 0:
            verdict = "factor-neutral signal largely survives"
        elif neutral_sharpe > 0 and neutral_return > 0:
            verdict = "factor-neutral signal weakens but remains positive"
        else:
            verdict = "factor-neutral signal does not survive"
        rows.append(
            f"- {horizon}: raw Sharpe={raw_sharpe:.2f}, neutral Sharpe={neutral_sharpe:.2f}, "
            f"raw return={raw_return:.2%}, neutral return={neutral_return:.2%}. {verdict}."
        )
    return "\n".join(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run actual engine backtests for factor-neutral scores")
    parser.add_argument("--processed-dir", type=Path, default=CHART_ROOT / "data" / "processed")
    parser.add_argument("--data-dir", type=Path, default=CHART_ROOT / "data")
    parser.add_argument("--results-dir", type=Path, default=EXPERIMENTS_DIR / "results")
    parser.add_argument("--cache-dir", type=Path, default=EXPERIMENTS_DIR / "cache")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--skip-existing", action="store_true")
    args = parser.parse_args()

    args.output_dir.mkdir(parents=True, exist_ok=True)
    neutral_prediction_dir = args.output_dir / "predictions"
    neutral_config_dir = args.output_dir / "configs"

    experiments = load_final_experiments(args.results_dir, args.cache_dir)
    min_start = min(pd.read_csv(exp["returns_path"], parse_dates=["Date"])["Date"].min() for exp in experiments)
    max_end = max(pd.read_csv(exp["returns_path"], parse_dates=["Date"])["Date"].max() for exp in experiments)

    log(f"Loading processed panel for {min_start.date()} ~ {max_end.date()}")
    metadata = load_metadata(args.data_dir)
    panel = add_exposures(load_panel(args.processed_dir, min_start, max_end), metadata)
    exposures = EXPOSURE_COLUMNS

    summary_rows = []
    for exp in experiments:
        horizon = exp["horizon_label"]
        source_result_dir = args.results_dir / exp["name"]
        source_config_path = source_result_dir / "config_snapshot.yaml"
        if not source_config_path.exists():
            raise FileNotFoundError(f"Missing config snapshot: {source_config_path}")

        raw_fixed_name = f"{exp['name']}_engine_fixed_raw"
        raw_config_path = neutral_config_dir / f"{raw_fixed_name}.yaml"
        raw_result_dir = args.results_dir / raw_fixed_name
        write_backtest_config(
            source_config_path,
            raw_config_path,
            raw_fixed_name,
            "engine-fixed raw score backtest",
        )

        log(f"\n[{horizon}] Running actual VectorBTEngine for raw score with fixed engine")
        if not (
            args.skip_existing
            and (raw_result_dir / "backtest_metrics_summary.json").exists()
            and (raw_result_dir / "daily_returns.csv").exists()
        ):
            run_engine_only_backtest(raw_config_path, exp["predictions_path"], raw_result_dir)
        summary_rows.append(summarize_backtest_result(raw_result_dir, "raw", horizon, exp["name"]))

        neutral_name = f"{exp['name']}_factor_neutral"
        neutral_pred_path = neutral_prediction_dir / f"{exp['prediction_hash']}_factor_neutral_predictions.parquet"
        neutral_config_path = neutral_config_dir / f"{neutral_name}.yaml"
        neutral_result_dir = args.results_dir / neutral_name

        log(f"\n[{horizon}] Building factor-neutral predictions")
        if not (args.skip_existing and neutral_pred_path.exists()):
            build_neutral_predictions(
                exp["predictions_path"],
                panel,
                neutral_pred_path,
                exposures,
                prob_threshold=exp["prob_threshold"],
            )
        write_backtest_config(
            source_config_path,
            neutral_config_path,
            neutral_name,
            "factor-neutral residual percentile score backtest",
        )

        log(f"[{horizon}] Running actual VectorBTEngine for factor-neutral score")
        if not (
            args.skip_existing
            and (neutral_result_dir / "backtest_metrics_summary.json").exists()
            and (neutral_result_dir / "daily_returns.csv").exists()
        ):
            run_engine_only_backtest(neutral_config_path, neutral_pred_path, neutral_result_dir)
        summary_rows.append(
            summarize_backtest_result(neutral_result_dir, "factor_neutral", horizon, exp["name"])
        )

    summary = pd.DataFrame(summary_rows)
    summary.to_csv(args.output_dir / "factor_neutral_backtest_summary.csv", index=False)
    write_summary_report(summary, args.output_dir)
    print(f"Wrote factor-neutral backtest outputs to {args.output_dir}")


if __name__ == "__main__":
    main()
