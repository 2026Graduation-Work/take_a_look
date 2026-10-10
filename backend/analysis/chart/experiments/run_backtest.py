import argparse
import json
import os
from pathlib import Path

import numpy as np
import pandas as pd
import yaml
from experiments.backtest.engine import VectorBTEngine, configured_benchmark, kospi_index_returns
from experiments.evaluation.backtest_metrics import calculate_trading_metrics
from experiments.evaluation.baselines import (
    generate_ma_breakout_signals,
    generate_momentum_signals,
    generate_random_top_k_signals,
    restrict_signals_to_test_folds,
)
from experiments.experiment_utils import (
    build_fold_alignment,
    find_processed_dir,
    generate_predictions_hash,
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


def _json_safe(value):
    if isinstance(value, (np.floating, np.integer)):
        return value.item()
    if pd.isna(value):
        return None
    return value


def _slice_trades(trades_df: pd.DataFrame, start: pd.Timestamp, end: pd.Timestamp) -> pd.DataFrame:
    if trades_df is None or trades_df.empty:
        return pd.DataFrame()

    entry_time_col = "Entry Timestamp" if "Entry Timestamp" in trades_df.columns else "entry_time"
    if entry_time_col not in trades_df.columns:
        return trades_df.iloc[0:0].copy()

    sliced = trades_df.copy()
    sliced[entry_time_col] = pd.to_datetime(sliced[entry_time_col]).dt.tz_localize(None)
    return sliced[(sliced[entry_time_col] >= start) & (sliced[entry_time_col] <= end)]


def _format_pct(value: float) -> str:
    return "N/A" if pd.isna(value) else f"{value * 100:.2f}%"


def _format_float(value: float) -> str:
    return "N/A" if pd.isna(value) else f"{value:.4f}"


def add_kospi_benchmark(out_dir, config):
    """Add the same KOSPI buy-and-hold comparison to a saved backtest."""
    returns_path = os.path.join(out_dir, "daily_returns.csv")
    comparison_path = os.path.join(out_dir, "benchmark_comparison.csv")
    metadata_path = os.path.join(out_dir, "benchmark_metadata.csv")
    summary_path = os.path.join(out_dir, "backtest_metrics_summary.json")
    daily = pd.read_csv(returns_path, index_col="Date", parse_dates=["Date"])
    index_file = config.get("evaluation", {}).get("kospi_index_file")
    kospi = kospi_index_returns(daily.index, index_file)
    metrics = calculate_trading_metrics(kospi)
    source = kospi.attrs["benchmark_source"]

    comparison = pd.read_csv(comparison_path, keep_default_na=False)
    comparison.loc[comparison["Win Rate"] == "", "Win Rate"] = "N/A"
    comparison = comparison[comparison["Strategy"] != "KOSPI Index Buy & Hold"].reset_index(
        drop=True
    )
    comparison.loc[len(comparison)] = {
        "Strategy": "KOSPI Index Buy & Hold",
        "Total Return": _format_pct(metrics["total_return"]),
        "Sharpe Ratio": _format_float(metrics["sharpe_ratio"]),
        "Max Drawdown": _format_pct(metrics["max_drawdown"]),
        "Win Rate": "N/A",
        "Benchmark Source": source,
    }
    metadata = pd.read_csv(metadata_path, keep_default_na=False)
    metadata = metadata[metadata["benchmark"] != "KOSPI Index Buy & Hold"].reset_index(drop=True)
    metadata.loc[len(metadata)] = {
        "benchmark": "KOSPI Index Buy & Hold",
        "source": source,
        "reason": "KOSPI price index close-to-close returns; no dividends or fees",
        "valid": True,
        "validity_reason": "full evaluation-date coverage",
    }
    with open(summary_path, encoding="utf-8") as f:
        summary = json.load(f)
    summary.update({f"benchmark_kospi_{key}": _json_safe(value) for key, value in metrics.items()})
    summary["benchmark_kospi_source"] = source

    daily["Benchmark_KOSPI"] = kospi
    daily.to_csv(returns_path)
    comparison.to_csv(comparison_path, index=False)
    metadata.to_csv(metadata_path, index=False)
    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=4, ensure_ascii=False)
    print(f"[*] KOSPI index benchmark added: {out_dir}")


def _run_local_period(config, predictions, prices, out):
    from experiments.backtest.local_execution import save_execution
    from shared.io import atomic_json

    if predictions.empty or prices.empty:
        raise ValueError("Backtest period has no predictions/prices")
    Path(out).mkdir(parents=True, exist_ok=True)
    entries, weights = SwingStrategy(config).generate_signals(predictions, prices)
    try:
        portfolio = VectorBTEngine(config).run(entries, weights, prices, generate_report=False)
    except Exception as exc:
        atomic_json(Path(out) / "execution_error.json", {"reason": str(exc), "config": config})
        raise
    save_execution(portfolio, out)
    closed = portfolio.trade_records().loc[lambda frame: frame.Status.eq("Closed")]
    returns = portfolio.returns()
    metrics = calculate_trading_metrics(returns, closed)
    benchmark = configured_benchmark(config, returns.index, prices)
    metrics["benchmark"] = calculate_trading_metrics(benchmark)
    metrics["initial_cash"] = config["backtest"]["initial_cash"]
    metrics["final_equity"] = float(portfolio.value().iloc[-1])
    metrics["unclosed_positions"] = len(portfolio.open_positions)
    metrics["execution_policy"] = {"quantity": "integer_floor_on_existing_adjusted_price_basis",
                                   "delisting": "zero_valuation_zero_cash_recovery"}
    metrics["unrealized_pnl"] = sum(
        row["unrealized_pnl_before_exit_fee"] for row in portfolio.open_positions
    )
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


def main(config_path, predictions_path=None, benchmarks_only=False):
    print(f"[*] Loading config from {config_path}...")
    from experiments.config import load_experiment_config

    config = load_experiment_config(config_path)
    if config.get("contract_version") == 3:
        if benchmarks_only:
            raise ValueError("Local pipeline evaluates its fixed benchmark with the strategy")
        return run_local_backtest(config, predictions_path)

    exp_name = config.get("experiment_name", "default_exp")
    if benchmarks_only:
        add_kospi_benchmark(result_dir(config, __file__), config)
        return
    print(f"\n📈 [*] Starting Trading Backtest: {exp_name}")

    splits = resolve_splits(config)
    if not splits:
        raise ValueError("분할 폴드(Splits) 목록이 비어 있습니다. 설정을 확인하세요.")

    embargo_days = config.get("data", {}).get("embargo_days", 7)
    if not validate_embargo(splits, embargo_days):
        raise ValueError("Embargo 검증 실패: train/test 기간 간격을 확인하세요.")

    predictions_hash = generate_predictions_hash(config, splits)
    print(f"[*] Target Predictions Cache Hash: {predictions_hash}")

    final_predictions = load_predictions(config, splits, __file__, predictions_path)

    processed_dir = find_processed_dir(config, __file__)
    print(f"[*] 데이터 소스 디렉토리: {processed_dir}")

    full_test_start, full_test_end = test_date_bounds(splits)
    tickers_cfg = resolve_tickers(config, __file__)
    universe_intervals = load_universe_intervals(config)

    price_cols = ["Date", "Code", "Open", "High", "Low", "Close", "Sigma", "Trading_Halt"]
    market_df = load_parquet_data(
        processed_dir,
        full_test_start,
        full_test_end,
        columns_only=price_cols,
        tickers=tickers_cfg,
        strict=config.get("data", {}).get("point_in_time", False),
        universe_intervals=universe_intervals,
    )
    market_df["Date"] = pd.to_datetime(market_df["Date"]).dt.tz_localize(None)

    alignment_df, alignment_status = build_fold_alignment(final_predictions, splits)
    if not alignment_status["is_exact_fold_match"]:
        raise ValueError(
            "예측 캐시가 config의 test fold들과 정확히 매칭되지 않습니다. "
            f"alignment={alignment_status}"
        )

    # 가격 로딩은 라벨 생성을 하지 않는다. 라벨은 미래 horizon 가격이 필요한 반면
    # 백테스트는 해당 날짜의 OHLC가 모두 필요하므로, label_params를 넘기면 마지막
    # horizon 거래일의 가격과 prediction이 inner join에서 조용히 사라질 수 있다.
    prediction_keys = final_predictions[["Date", "Code"]].copy()
    prediction_keys["Date"] = pd.to_datetime(prediction_keys["Date"]).dt.tz_localize(None)
    market_keys = market_df[["Date", "Code"]].drop_duplicates()
    uncovered = prediction_keys.merge(market_keys, on=["Date", "Code"], how="left", indicator=True)
    uncovered = uncovered[uncovered["_merge"] != "both"]
    if not uncovered.empty:
        examples = uncovered[["Date", "Code"]].head(5).to_dict("records")
        raise ValueError(
            "백테스트 가격 데이터에 대응하는 prediction 행이 없습니다. "
            f"누락 {len(uncovered)}건, 예시={examples}"
        )

    print("\n[1] 트레이딩 전략 매트릭스 변환 (Swing Strategy)...")
    strategy = SwingStrategy(config)
    entries, weights = strategy.generate_signals(final_predictions, market_df)
    strategy_keys = pd.MultiIndex.from_product(
        [entries.index, entries.columns], names=["Date", "Code"]
    )
    prediction_index = pd.MultiIndex.from_frame(prediction_keys)
    missing_strategy_keys = prediction_index.difference(strategy_keys)
    if len(missing_strategy_keys):
        examples = [tuple(map(str, key)) for key in missing_strategy_keys[:5]]
        raise ValueError(
            "전략 시그널 행렬에서 prediction key가 누락되었습니다. "
            f"누락 {len(missing_strategy_keys)}건, 예시={examples}"
        )

    print("\n[2] VectorBT 퀀트 시뮬레이터 가동 (Backtest Engine)...")
    bt_engine = VectorBTEngine(config)
    pf = bt_engine.run(entries, weights, market_df)

    daily_returns = pf.returns()
    daily_returns.index = pd.to_datetime(daily_returns.index).tz_localize(None)
    trades_all = pf.trades.records_readable if len(pf.trades.records) > 0 else pd.DataFrame()

    backtest_metrics = []
    for idx, split in enumerate(splits):
        fold_id = split.get("fold_id", idx)
        fold_name = split.get("name", f"Fold {fold_id}")
        test_start = pd.to_datetime(split["test_start"])
        test_end = pd.to_datetime(split["test_end"])

        fold_returns = daily_returns[
            (daily_returns.index >= test_start) & (daily_returns.index <= test_end)
        ]
        fold_trades = _slice_trades(trades_all, test_start, test_end)
        metrics = calculate_trading_metrics(fold_returns, fold_trades)
        metrics["fold_id"] = fold_id
        metrics["Fold"] = fold_name
        metrics["test_start"] = split["test_start"]
        metrics["test_end"] = split["test_end"]
        backtest_metrics.append(metrics)

    backtest_metrics_df = pd.DataFrame(backtest_metrics)

    yearly_metrics = []
    for year in sorted(daily_returns.index.year.unique()):
        year_returns = daily_returns[daily_returns.index.year == year]
        if trades_all.empty:
            year_trades = pd.DataFrame()
        else:
            year_start = pd.Timestamp(year=year, month=1, day=1)
            year_end = pd.Timestamp(year=year, month=12, day=31)
            year_trades = _slice_trades(trades_all, year_start, year_end)
        metrics = calculate_trading_metrics(year_returns, year_trades)
        metrics["Year"] = int(year)
        yearly_metrics.append(metrics)

    backtest_by_year_df = pd.DataFrame(yearly_metrics)

    print("\n[3] Baseline 벤치마크 전략 시뮬레이션...")
    top_n = config.get("strategy", {}).get("top_n", 5)
    random_seeds = config.get("evaluation", {}).get("random_baseline_seeds", 5)
    random_returns = []
    random_mdds = []
    random_sharpes = []

    for seed in range(100, 100 + random_seeds):
        random_entries, random_weights = generate_random_top_k_signals(
            market_df, top_n=top_n, seed=seed
        )
        random_entries, random_weights = restrict_signals_to_test_folds(
            random_entries, random_weights, splits
        )
        random_pf = bt_engine.run(random_entries, random_weights, market_df, generate_report=False)
        random_metrics = calculate_trading_metrics(
            random_pf.returns(),
            random_pf.trades.records_readable if len(random_pf.trades.records) > 0 else None,
        )
        random_returns.append(random_metrics.get("total_return", np.nan))
        random_mdds.append(random_metrics.get("max_drawdown", np.nan))
        random_sharpes.append(random_metrics.get("sharpe_ratio", np.nan))

    mom_entries, mom_weights = generate_momentum_signals(market_df, top_n=top_n, horizon=5)
    mom_entries, mom_weights = restrict_signals_to_test_folds(mom_entries, mom_weights, splits)
    mom_pf = bt_engine.run(mom_entries, mom_weights, market_df, generate_report=False)
    mom_metrics = calculate_trading_metrics(
        mom_pf.returns(), mom_pf.trades.records_readable if len(mom_pf.trades.records) > 0 else None
    )

    ma_entries, ma_weights = generate_ma_breakout_signals(market_df, top_n=top_n, window=20)
    ma_entries, ma_weights = restrict_signals_to_test_folds(ma_entries, ma_weights, splits)
    ma_pf = bt_engine.run(ma_entries, ma_weights, market_df, generate_report=False)
    ma_metrics = calculate_trading_metrics(
        ma_pf.returns(), ma_pf.trades.records_readable if len(ma_pf.trades.records) > 0 else None
    )

    krx_returns = configured_benchmark(config, daily_returns.index, market_df)
    krx_source = krx_returns.attrs.get("benchmark_source", "unknown")
    krx_reason = krx_returns.attrs.get("benchmark_reason", "")
    krx_valid = krx_returns.attrs.get("benchmark_valid", False)
    krx_validity_reason = krx_returns.attrs.get("benchmark_validity_reason", "")
    krx_metrics = calculate_trading_metrics(krx_returns)
    model_metrics = calculate_trading_metrics(daily_returns, trades_all)

    benchmark_comparison_df = pd.DataFrame(
        [
            {
                "Strategy": "LGBM Model",
                "Total Return": _format_pct(model_metrics.get("total_return", np.nan)),
                "Sharpe Ratio": _format_float(model_metrics.get("sharpe_ratio", np.nan)),
                "Max Drawdown": _format_pct(model_metrics.get("max_drawdown", np.nan)),
                "Win Rate": _format_pct(model_metrics.get("win_rate", np.nan)),
                "Benchmark Source": "",
            },
            {
                "Strategy": f"Random Top-{top_n} (Mean)",
                "Total Return": _format_pct(float(np.nanmean(random_returns))),
                "Sharpe Ratio": _format_float(float(np.nanmean(random_sharpes))),
                "Max Drawdown": _format_pct(float(np.nanmean(random_mdds))),
                "Win Rate": "N/A",
                "Benchmark Source": "",
            },
            {
                "Strategy": "5-Day Momentum",
                "Total Return": _format_pct(mom_metrics.get("total_return", np.nan)),
                "Sharpe Ratio": _format_float(mom_metrics.get("sharpe_ratio", np.nan)),
                "Max Drawdown": _format_pct(mom_metrics.get("max_drawdown", np.nan)),
                "Win Rate": _format_pct(mom_metrics.get("win_rate", np.nan)),
                "Benchmark Source": "",
            },
            {
                "Strategy": "20-Day MA Breakout",
                "Total Return": _format_pct(ma_metrics.get("total_return", np.nan)),
                "Sharpe Ratio": _format_float(ma_metrics.get("sharpe_ratio", np.nan)),
                "Max Drawdown": _format_pct(ma_metrics.get("max_drawdown", np.nan)),
                "Win Rate": _format_pct(ma_metrics.get("win_rate", np.nan)),
                "Benchmark Source": "",
            },
            {
                "Strategy": "Custom KRX Composite Index",
                "Total Return": _format_pct(krx_metrics.get("total_return", np.nan)),
                "Sharpe Ratio": _format_float(krx_metrics.get("sharpe_ratio", np.nan)),
                "Max Drawdown": _format_pct(krx_metrics.get("max_drawdown", np.nan)),
                "Win Rate": "N/A",
                "Benchmark Source": krx_source,
            },
        ]
    )

    summary = {f"trade_{key}": _json_safe(value) for key, value in model_metrics.items()}
    summary.update(
        {
            "prediction_hash": predictions_hash,
            "benchmark_custom_krx_source": krx_source,
            "benchmark_custom_krx_reason": krx_reason,
            "benchmark_custom_krx_valid": krx_valid,
            "benchmark_custom_krx_validity_reason": krx_validity_reason,
            **{
                f"benchmark_custom_krx_{key}": _json_safe(value)
                for key, value in krx_metrics.items()
            },
            "fold_alignment_exact": bool(alignment_status["is_exact_fold_match"]),
            **{
                f"fold_alignment_{key}": _json_safe(value)
                for key, value in alignment_status.items()
            },
        }
    )

    out_dir = result_dir(config, __file__)
    alignment_df.to_csv(os.path.join(out_dir, "fold_alignment.csv"), index=False)
    backtest_metrics_df.to_csv(os.path.join(out_dir, "backtest_metrics_by_fold.csv"), index=False)
    backtest_by_year_df.to_csv(os.path.join(out_dir, "backtest_metrics_by_year.csv"), index=False)
    benchmark_comparison_df.to_csv(os.path.join(out_dir, "benchmark_comparison.csv"), index=False)
    pd.DataFrame(
        [
            {
                "benchmark": "Custom KRX Composite Index",
                "source": krx_source,
                "reason": krx_reason,
                "valid": krx_valid,
                "validity_reason": krx_validity_reason,
            }
        ]
    ).to_csv(os.path.join(out_dir, "benchmark_metadata.csv"), index=False)
    with open(os.path.join(out_dir, "backtest_metrics_summary.json"), "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=4, ensure_ascii=False)
    with open(os.path.join(out_dir, "config_snapshot.yaml"), "w", encoding="utf-8") as f:
        yaml.dump(config, f, allow_unicode=True)
    add_kospi_benchmark(out_dir, config)

    print(
        f"\n🎉 백테스트 [{exp_name}] 완료. fold_alignment_exact={alignment_status['is_exact_fold_match']}"
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=str, required=True, help="Path to config yaml")
    parser.add_argument(
        "--predictions-path",
        type=str,
        default=None,
        help="Path to pre-computed predictions parquet file",
    )
    parser.add_argument(
        "--benchmarks-only",
        action="store_true",
        help="Add KOSPI index to an existing backtest without rerunning training or simulation",
    )
    args = parser.parse_args()
    main(args.config, args.predictions_path, args.benchmarks_only)
