import argparse
import ast
import json
import math
import os
import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

EXPERIMENTS_DIR = Path(__file__).resolve().parents[2]
if str(EXPERIMENTS_DIR) not in sys.path:
    sys.path.insert(0, str(EXPERIMENTS_DIR))

# These imports support direct execution via ``python run_horizon_final_analysis.py``.
from evaluation.backtest_metrics import calculate_trading_metrics  # noqa: E402, I001
from experiment_utils import (  # noqa: E402
    find_processed_dir,
    generate_predictions_hash,
    label_params_from_config,
    load_predictions,
    resolve_splits,
    test_date_bounds,
)  # noqa: E402
from train_src.loaders import load_parquet_data  # noqa: E402


FINAL_EXPERIMENTS = {
    "H5": {
        "result": "tb_lgbm_h5_u175_d150_alpha158_regime4",
        "multiplier": "u175/d150",
    },
    "H10": {
        "result": "tb_lgbm_h10_u250_d225_alpha158_current_sigma_selection2020_2022",
        "multiplier": "u250/d225",
    },
    "H20": {
        "result": "tb_lgbm_h20_u375_d300_alpha158_current_sigma_selection2020_2022",
        "multiplier": "u375/d300",
    },
}


@dataclass
class HorizonData:
    horizon: str
    result_name: str
    result_dir: str
    config: dict
    predictions: pd.DataFrame
    scored: pd.DataFrame
    daily_returns: pd.DataFrame
    trades: pd.DataFrame
    summary: dict


def _experiments_dir(anchor_file: str) -> str:
    return os.path.dirname(os.path.abspath(anchor_file))


def _results_root(anchor_file: str) -> str:
    return os.path.join(_experiments_dir(anchor_file), "results")


def _analysis_dir(anchor_file: str) -> str:
    path = os.path.join(_results_root(anchor_file), "horizon_final_analysis")
    os.makedirs(path, exist_ok=True)
    return path


def _analysis_cache_dir(anchor_file: str) -> str:
    path = os.path.join(_experiments_dir(anchor_file), "cache", "analysis")
    os.makedirs(path, exist_ok=True)
    return path


def _read_config(result_dir: str) -> dict:
    for filename in ["config_snapshot.yaml", "config.yaml"]:
        path = os.path.join(result_dir, filename)
        if os.path.exists(path):
            with open(path, encoding="utf-8") as f:
                return yaml.safe_load(f)
    raise FileNotFoundError(f"config_snapshot.yaml/config.yaml not found in {result_dir}")


def _read_json(path: str) -> dict:
    if not os.path.exists(path):
        return {}
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _fmt_pct(value) -> str:
    if value is None or pd.isna(value):
        return "N/A"
    return f"{float(value) * 100:.2f}%"


def _fmt_num(value, digits: int = 3) -> str:
    if value is None or pd.isna(value):
        return "N/A"
    return f"{float(value):.{digits}f}"


def _safe_div(num: float, den: float) -> float:
    return float(num / den) if den else np.nan


def _profit_metrics(returns: pd.Series) -> dict:
    returns = pd.to_numeric(returns, errors="coerce").dropna()
    if returns.empty:
        return {
            "sample_count": 0,
            "average_return": np.nan,
            "win_rate": np.nan,
            "average_win": np.nan,
            "average_loss": np.nan,
            "payoff_ratio": np.nan,
            "profit_factor": np.nan,
            "expectancy": np.nan,
        }
    wins = returns[returns > 0]
    losses = returns[returns <= 0]
    avg_win = wins.mean() if not wins.empty else 0.0
    avg_loss = losses.mean() if not losses.empty else 0.0
    total_loss = losses.sum()
    profit_factor = _safe_div(wins.sum(), abs(total_loss))
    win_rate = float((returns > 0).mean())
    return {
        "sample_count": int(len(returns)),
        "average_return": float(returns.mean()),
        "win_rate": win_rate,
        "average_win": float(avg_win),
        "average_loss": float(avg_loss),
        "payoff_ratio": _safe_div(avg_win, abs(avg_loss)),
        "profit_factor": profit_factor,
        "expectancy": float(win_rate * avg_win + (1.0 - win_rate) * avg_loss),
    }


def _extract_code(column_value) -> str:
    if not isinstance(column_value, str):
        return str(column_value).zfill(6)
    try:
        parsed = ast.literal_eval(column_value)
        if isinstance(parsed, tuple) and parsed:
            return str(parsed[0]).zfill(6)
    except (SyntaxError, ValueError):
        # Non-literal column labels use the manual normalization fallback below.
        pass
    return (
        column_value.replace("'", "")
        .replace('"', "")
        .replace("(", "")
        .replace(")", "")
        .split(",")[0]
        .strip()
        .zfill(6)
    )


def _load_market_map() -> dict:
    candidates = [
        os.path.abspath(os.path.join(_experiments_dir(__file__), "..", "..", "..", "..", "data", "financial", "metadata", "krx_stock_master.csv")),
        os.path.abspath(os.path.join(os.getcwd(), "data", "financial", "metadata", "krx_stock_master.csv")),
    ]
    for path in candidates:
        if not os.path.exists(path):
            continue
        df = pd.read_csv(path, dtype={"stock_code": str})
        if {"stock_code", "market"}.issubset(df.columns):
            df["stock_code"] = df["stock_code"].astype(str).str.zfill(6)
            return dict(zip(df["stock_code"], df["market"]))
    return {}


def _load_name_map(anchor_file: str) -> dict:
    candidates = [
        os.path.abspath(os.path.join(_experiments_dir(anchor_file), "..", "data", "ticker_metadata.csv")),
        os.path.abspath(os.path.join(os.getcwd(), "Stock_Prediction_v2", "analysis", "chart", "data", "ticker_metadata.csv")),
    ]
    for path in candidates:
        if not os.path.exists(path):
            continue
        df = pd.read_csv(path, dtype={"Code": str})
        if {"Code", "Name"}.issubset(df.columns):
            df["Code"] = df["Code"].astype(str).str.zfill(6)
            return dict(zip(df["Code"], df["Name"]))
    return {}


def _add_forward_returns(market_df: pd.DataFrame, horizon_days: int, fee: float) -> pd.DataFrame:
    market = market_df[["Date", "Code", "Close", "Open"]].copy()
    market["Date"] = pd.to_datetime(market["Date"]).dt.tz_localize(None)
    market["Code"] = market["Code"].astype(str).str.zfill(6)
    market = market.sort_values(["Code", "Date"])
    market["forward_return"] = market.groupby("Code")["Close"].shift(-horizon_days) / market["Close"] - 1.0
    market["realized_return_proxy"] = market["forward_return"] - (2.0 * fee)
    return market[["Date", "Code", "forward_return", "realized_return_proxy"]]


def _load_horizon_data(anchor_file: str, horizon: str, spec: dict) -> HorizonData:
    result_dir = os.path.join(_results_root(anchor_file), spec["result"])
    config = _read_config(result_dir)
    splits = resolve_splits(config)
    pred_hash = generate_predictions_hash(config, splits)
    predictions = load_predictions(config, splits, anchor_file)
    predictions = predictions.rename(columns={"Prob": "prob_up"}).copy()
    predictions["Date"] = pd.to_datetime(predictions["Date"]).dt.tz_localize(None)
    predictions["Code"] = predictions["Code"].astype(str).str.zfill(6)
    scored_cache_path = os.path.join(_analysis_cache_dir(anchor_file), f"{pred_hash}_scored.parquet")
    if os.path.exists(scored_cache_path):
        scored = pd.read_parquet(scored_cache_path)
        scored["Date"] = pd.to_datetime(scored["Date"]).dt.tz_localize(None)
        scored["Code"] = scored["Code"].astype(str).str.zfill(6)
    else:
        start, end = test_date_bounds(splits)
        horizon_days = int(config.get("labels", {}).get("horizon", horizon.removeprefix("H")))
        extended_end = (pd.to_datetime(end) + pd.Timedelta(days=horizon_days * 3)).strftime("%Y-%m-%d")
        processed_dir = find_processed_dir(config, anchor_file)
        market_df = load_parquet_data(
            processed_dir,
            start,
            extended_end,
            columns_only=["Date", "Code", "Open", "Close"],
            tickers=config.get("data", {}).get("tickers"),
            label_params=None,
        )
        fee = float(config.get("backtest", {}).get("fee", 0.0))
        returns_df = _add_forward_returns(market_df, horizon_days, fee)
        scored = predictions.merge(returns_df, on=["Date", "Code"], how="left")

        labels = load_parquet_data(
            processed_dir,
            start,
            end,
            columns_only=["Date", "Code"],
            tickers=config.get("data", {}).get("tickers"),
            label_params=label_params_from_config(config),
        )[["Date", "Code", "Y_Label"]]
        labels["Date"] = pd.to_datetime(labels["Date"]).dt.tz_localize(None)
        labels["Code"] = labels["Code"].astype(str).str.zfill(6)
        scored = scored.merge(labels, on=["Date", "Code"], how="left")
        scored.to_parquet(scored_cache_path, index=False)

    daily_returns = pd.read_csv(os.path.join(result_dir, "daily_returns.csv"))
    daily_returns["Date"] = pd.to_datetime(daily_returns["Date"], utc=True).dt.tz_localize(None)
    trades_path = os.path.join(result_dir, "trades.csv")
    trades = pd.read_csv(trades_path) if os.path.exists(trades_path) else pd.DataFrame()
    summary = _read_json(os.path.join(result_dir, "backtest_metrics_summary.json"))
    summary["prediction_hash"] = summary.get("prediction_hash", pred_hash)
    return HorizonData(horizon, spec["result"], result_dir, config, predictions, scored, daily_returns, trades, summary)


def _benchmark_validity(daily_returns: pd.DataFrame, col: str) -> tuple[bool, str]:
    if col not in daily_returns:
        return False, f"{col} missing"
    series = pd.to_numeric(daily_returns[col], errors="coerce")
    if series.isna().all():
        return False, "all NaN"
    if series.fillna(0.0).abs().sum() == 0.0:
        return False, "all zero returns"
    total = (1.0 + series.fillna(0.0)).prod() - 1.0
    if abs(total) < 1e-12:
        return False, "0.00% total return"
    return True, "valid"


def build_summary_table(horizons: dict[str, HorizonData]) -> pd.DataFrame:
    rows = []
    for key, data in horizons.items():
        trades = data.trades
        trade_metrics = calculate_trading_metrics(
            data.daily_returns.set_index("Date")["Portfolio"], trades
        )
        benchmark_valid, reason = _benchmark_validity(data.daily_returns, "Benchmark_CustomKRX")
        bench_ret = np.nan
        excess = np.nan
        if "Benchmark_CustomKRX" in data.daily_returns:
            bench_series = data.daily_returns["Benchmark_CustomKRX"].fillna(0.0)
            bench_ret = (1.0 + bench_series).prod() - 1.0
            excess = trade_metrics.get("total_return", np.nan) - bench_ret
        rows.append(
            {
                "Horizon": key,
                "Multiplier": FINAL_EXPERIMENTS[key]["multiplier"],
                "Experiment": data.result_name,
                "Total Return": trade_metrics.get("total_return", np.nan),
                "CAGR": trade_metrics.get("cagr", np.nan),
                "Sharpe": trade_metrics.get("sharpe_ratio", np.nan),
                "Sortino": trade_metrics.get("sortino_ratio", np.nan),
                "MDD": trade_metrics.get("max_drawdown", np.nan),
                "Trades": trade_metrics.get("number_of_trades", 0),
                "Win Rate": trade_metrics.get("win_rate", np.nan),
                "Average Win": trade_metrics.get("average_win", np.nan),
                "Average Loss": trade_metrics.get("average_loss", np.nan),
                "Payoff Ratio": trade_metrics.get("payoff_ratio", np.nan),
                "Profit Factor": trade_metrics.get("profit_factor", np.nan),
                "Expectancy": data.trades["Return"].mean() if "Return" in data.trades else np.nan,
                "Benchmark Custom KRX Return": bench_ret,
                "Excess Return vs Custom KRX": excess,
                "Benchmark Valid": benchmark_valid,
                "Benchmark Validity Reason": reason,
                "Prediction Hash": data.summary.get("prediction_hash", ""),
            }
        )
    return pd.DataFrame(rows)


def build_overlap_tables(horizons: dict[str, HorizonData]) -> tuple[pd.DataFrame, pd.DataFrame]:
    probs = []
    for key, data in horizons.items():
        probs.append(data.predictions.rename(columns={"prob_up": f"{key}_prob_up"}))
    merged = probs[0]
    for df in probs[1:]:
        merged = merged.merge(df, on=["Date", "Code"], how="inner")
    corr_rows = []
    for left, right in [("H5", "H10"), ("H5", "H20"), ("H10", "H20")]:
        lcol, rcol = f"{left}_prob_up", f"{right}_prob_up"
        daily_rank = (
            merged.groupby("Date")[[lcol, rcol]]
            .corr(method="spearman")
            .unstack()
            .iloc[:, 1]
            .dropna()
        )
        corr_rows.append(
            {
                "Pair": f"{left}-{right}",
                "Pearson Corr": merged[lcol].corr(merged[rcol]),
                "Daily Rank Corr Mean": daily_rank.mean(),
                "Daily Rank Corr Std": daily_rank.std(),
                "Daily Rank Corr Positive Ratio": (daily_rank > 0).mean(),
                "Days": int(daily_rank.shape[0]),
            }
        )
    corr_df = pd.DataFrame(corr_rows)

    overlap_rows = []
    for left, right in [("H5", "H10"), ("H5", "H20"), ("H10", "H20")]:
        lcol, rcol = f"{left}_prob_up", f"{right}_prob_up"
        for top_label, top_n, top_frac in [("top-5", 5, None), ("top-10", 10, None), ("top-10%", None, 0.10)]:
            daily = []
            for _, group in merged.groupby("Date", sort=False):
                if top_frac is not None:
                    n = max(1, int(math.ceil(len(group) * top_frac)))
                else:
                    n = top_n
                lset = set(group.nlargest(n, lcol)["Code"])
                rset = set(group.nlargest(n, rcol)["Code"])
                inter = len(lset & rset)
                union = len(lset | rset)
                daily.append(
                    {
                        "overlap": inter,
                        "overlap_ratio": inter / n if n else np.nan,
                        "jaccard": inter / union if union else np.nan,
                    }
                )
            daily_df = pd.DataFrame(daily)
            overlap_rows.append(
                {
                    "Pair": f"{left}-{right}",
                    "Set": top_label,
                    "Avg Overlap Count": daily_df["overlap"].mean(),
                    "Avg Overlap Ratio": daily_df["overlap_ratio"].mean(),
                    "Avg Jaccard": daily_df["jaccard"].mean(),
                }
            )
    overlap_df = pd.DataFrame(overlap_rows)

    h5 = horizons["H5"].scored[["Date", "Code", "prob_up", "Y_Label", "forward_return", "realized_return_proxy"]].rename(columns={"prob_up": "H5_prob_up"})
    h20 = horizons["H20"].predictions.rename(columns={"prob_up": "H20_prob_up"})
    group_df = h5.merge(h20, on=["Date", "Code"], how="inner")
    group_df["H5_high"] = group_df.groupby("Date")["H5_prob_up"].transform(lambda s: s >= s.quantile(0.9))
    group_df["H20_high"] = group_df.groupby("Date")["H20_prob_up"].transform(lambda s: s >= s.quantile(0.9))
    group_df["Group"] = np.select(
        [
            group_df["H5_high"] & group_df["H20_high"],
            group_df["H5_high"] & ~group_df["H20_high"],
            ~group_df["H5_high"] & group_df["H20_high"],
            ~group_df["H5_high"] & ~group_df["H20_high"],
        ],
        ["H5 high / H20 high", "H5 high / H20 low", "H5 low / H20 high", "H5 low / H20 low"],
        default="Unclassified",
    )
    group_rows = []
    for name, group in group_df.groupby("Group"):
        metrics = _profit_metrics(group["realized_return_proxy"])
        metrics.update(
            {
                "Group": name,
                "Label Hit Rate": (group["Y_Label"] == 2).mean(),
                "Average Forward Return": group["forward_return"].mean(),
            }
        )
        group_rows.append(metrics)
    group_perf = pd.DataFrame(group_rows)
    return corr_df, pd.concat([overlap_df, group_perf], ignore_index=True, sort=False)


def build_probability_tables(horizons: dict[str, HorizonData]) -> pd.DataFrame:
    rows = []
    bins = [0.0, 0.2, 0.4, 0.6, 0.8, 1.0]
    labels = [f"{bins[i]:.1f}-{bins[i + 1]:.1f}" for i in range(len(bins) - 1)]
    for key, data in horizons.items():
        df = data.scored.copy()
        df["Bucket"] = pd.cut(df["prob_up"], bins=bins, labels=labels, include_lowest=True)
        for bucket, group in df.groupby("Bucket", observed=False):
            metrics = _profit_metrics(group["realized_return_proxy"])
            metrics.update(
                {
                    "Horizon": key,
                    "Bucket Type": "probability",
                    "Bucket": str(bucket),
                    "Predicted Mean": group["prob_up"].mean(),
                    "Label Hit Rate": (group["Y_Label"] == 2).mean(),
                    "Average Forward Return": group["forward_return"].mean(),
                    "Average Realized Return": group["realized_return_proxy"].mean(),
                }
            )
            rows.append(metrics)
        for q in [0.01, 0.05, 0.10]:
            cut = df.groupby("Date")["prob_up"].transform(
                lambda values, quantile=q: values.quantile(1.0 - quantile)
            )
            group = df[df["prob_up"] >= cut]
            metrics = _profit_metrics(group["realized_return_proxy"])
            metrics.update(
                {
                    "Horizon": key,
                    "Bucket Type": "top_quantile",
                    "Bucket": f"top {int(q * 100)}%",
                    "Predicted Mean": group["prob_up"].mean(),
                    "Label Hit Rate": (group["Y_Label"] == 2).mean(),
                    "Average Forward Return": group["forward_return"].mean(),
                    "Average Realized Return": group["realized_return_proxy"].mean(),
                }
            )
            rows.append(metrics)
    return pd.DataFrame(rows)


def build_concentration_tables(horizons: dict[str, HorizonData], anchor_file: str) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    name_map = _load_name_map(anchor_file)
    market_map = _load_market_map()
    monthly_rows = []
    ticker_rows = []
    market_rows = []
    for key, data in horizons.items():
        returns = data.daily_returns[["Date", "Portfolio"]].copy().set_index("Date")
        monthly = returns["Portfolio"].resample("ME").agg(
            monthly_return=lambda x: (1.0 + x).prod() - 1.0,
            trading_days="count",
        )
        monthly["monthly_mdd"] = returns["Portfolio"].resample("ME").apply(
            lambda x: (((1.0 + x).cumprod() / (1.0 + x).cumprod().cummax()) - 1.0).min()
        )
        trades = data.trades.copy()
        if not trades.empty and "Entry Timestamp" in trades:
            trades["Entry Timestamp"] = pd.to_datetime(trades["Entry Timestamp"]).dt.tz_localize(None)
            trades["Month"] = trades["Entry Timestamp"].dt.to_period("M").astype(str)
            monthly_trades = trades.groupby("Month").size()
            monthly["Month"] = monthly.index.to_period("M").astype(str)
            monthly["Trades"] = monthly["Month"].map(monthly_trades).fillna(0).astype(int)
        else:
            monthly["Month"] = monthly.index.to_period("M").astype(str)
            monthly["Trades"] = 0
        monthly["Horizon"] = key
        monthly_rows.extend(monthly.reset_index(drop=True).to_dict("records"))

        if not trades.empty:
            trades["Code"] = trades["Column"].map(_extract_code) if "Column" in trades else "Unknown"
            trades["Name"] = trades["Code"].map(name_map).fillna("")
            trades["Market"] = trades["Code"].map(market_map).fillna("Unknown")
            by_code = trades.groupby(["Code", "Name"], dropna=False).agg(
                total_pnl=("PnL", "sum"),
                average_return=("Return", "mean"),
                trades=("Return", "count"),
            ).reset_index()
            by_code["Horizon"] = key
            by_code["pnl_share_abs"] = by_code["total_pnl"].abs() / by_code["total_pnl"].abs().sum()
            ticker_rows.extend(by_code.to_dict("records"))

            by_market = trades.groupby("Market", dropna=False).agg(
                total_pnl=("PnL", "sum"),
                average_return=("Return", "mean"),
                trades=("Return", "count"),
                win_rate=("Return", lambda x: (x > 0).mean()),
            ).reset_index()
            by_market["Horizon"] = key
            market_rows.extend(by_market.to_dict("records"))
    return pd.DataFrame(monthly_rows), pd.DataFrame(ticker_rows), pd.DataFrame(market_rows)


def build_rule_sensitivity(horizons: dict[str, HorizonData]) -> pd.DataFrame:
    rows = []
    for key in ["H5", "H20"]:
        data = horizons[key]
        fee = float(data.config.get("backtest", {}).get("fee", 0.0))
        horizon_days = int(data.config.get("labels", {}).get("horizon", key.removeprefix("H")))
        df = data.scored.dropna(subset=["prob_up", "forward_return"]).copy()
        for top_n in [3, 5, 10]:
            for threshold in [0.55, 0.60, 0.65]:
                for weighting in ["equal_weight", "probability_weighted"]:
                    daily_returns = []
                    selected_returns = []
                    for _, group in df[df["prob_up"] >= threshold].groupby("Date", sort=False):
                        picks = group.nlargest(top_n, "prob_up")
                        if picks.empty:
                            daily_returns.append(0.0)
                            continue
                        if weighting == "probability_weighted":
                            weights = picks["prob_up"] / picks["prob_up"].sum()
                        else:
                            weights = pd.Series(1.0 / len(picks), index=picks.index)
                        selected_return = float((weights * picks["forward_return"]).sum() - (2.0 * fee))
                        selected_returns.append(selected_return)
                        daily_returns.append(selected_return / horizon_days)
                    series = pd.Series(daily_returns)
                    metrics = calculate_trading_metrics(series)
                    rows.append(
                        {
                            "Horizon": key,
                            "top_n": top_n,
                            "prob_threshold": threshold,
                            "weighting": weighting,
                            "proxy_total_return": metrics.get("total_return", np.nan),
                            "proxy_cagr": metrics.get("cagr", np.nan),
                            "proxy_sharpe": metrics.get("sharpe_ratio", np.nan),
                            "proxy_mdd": metrics.get("max_drawdown", np.nan),
                            "active_days": int((series != 0).sum()),
                            "avg_selected_horizon_return": float(np.mean(selected_returns))
                            if selected_returns
                            else np.nan,
                        }
                    )
    return pd.DataFrame(rows)


def _write_markdown(path: str, lines: list[str]) -> None:
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


def write_reports(output_dir: str, summary: pd.DataFrame, corr: pd.DataFrame, overlap: pd.DataFrame, prob: pd.DataFrame, monthly: pd.DataFrame, tickers: pd.DataFrame, markets: pd.DataFrame, sensitivity: pd.DataFrame) -> None:
    summary.to_csv(os.path.join(output_dir, "horizon_final_summary.csv"), index=False)
    corr.to_csv(os.path.join(output_dir, "horizon_signal_correlation.csv"), index=False)
    overlap.to_csv(os.path.join(output_dir, "horizon_signal_overlap_groups.csv"), index=False)
    prob.to_csv(os.path.join(output_dir, "probability_return_calibration.csv"), index=False)
    monthly.to_csv(os.path.join(output_dir, "monthly_concentration.csv"), index=False)
    tickers.to_csv(os.path.join(output_dir, "ticker_contribution.csv"), index=False)
    markets.to_csv(os.path.join(output_dir, "market_contribution.csv"), index=False)
    sensitivity.to_csv(os.path.join(output_dir, "portfolio_rule_sensitivity.csv"), index=False)

    md = ["# H별 확정 Multiplier 최종 요약", "", "확정 multiplier는 H5 u175/d150, H10 u250/d225, H20 u375/d300으로 유지했다. 아래 지표는 기존 CSV/JSON 결과에서 재계산했다.", ""]
    show = summary.copy()
    for col in ["Total Return", "CAGR", "MDD", "Win Rate", "Average Win", "Average Loss", "Expectancy", "Benchmark Custom KRX Return", "Excess Return vs Custom KRX"]:
        if col in show:
            show[col] = show[col].map(_fmt_pct)
    for col in ["Sharpe", "Sortino", "Payoff Ratio", "Profit Factor"]:
        if col in show:
            show[col] = show[col].map(_fmt_num)
    md.append(show.to_markdown(index=False))
    md.append("")
    invalid = summary[~summary["Benchmark Valid"]]
    if not invalid.empty:
        md.append("## Benchmark validity")
        md.append("")
        md.append(invalid[["Horizon", "Benchmark Validity Reason"]].to_markdown(index=False))
    _write_markdown(os.path.join(output_dir, "horizon_multiplier_final_summary.md"), md)

    md = ["# Horizon Signal Overlap Report", "", "확률 예측 상관, 일별 rank correlation, top-k overlap, H5/H20 agreement/conflict group 성과를 기존 prediction cache에서 계산했다.", "", "## Prediction Correlation", "", corr.to_markdown(index=False), "", "## Overlap and H5/H20 Groups", "", overlap.to_markdown(index=False)]
    _write_markdown(os.path.join(output_dir, "horizon_signal_overlap_report.md"), md)

    md = ["# Probability Return Calibration Report", "", "기존 label hit-rate calibration에 forward return 및 거래비용 차감 realized-return proxy 수익성 지표를 추가했다.", "", prob.to_markdown(index=False)]
    _write_markdown(os.path.join(output_dir, "probability_return_calibration_report.md"), md)

    top_winners = tickers.sort_values("total_pnl", ascending=False).head(20)
    top_losers = tickers.sort_values("total_pnl").head(20)
    md = ["# Trade Concentration Report", "", "월별 성과, 종목별 PnL 기여도, KOSPI/KOSDAQ별 성과를 기존 trades.csv와 daily_returns.csv에서 집계했다.", "", "## Monthly Performance", "", monthly.to_markdown(index=False), "", "## Market Contribution", "", markets.to_markdown(index=False), "", "## Top PnL Contributors", "", top_winners.to_markdown(index=False), "", "## Bottom PnL Contributors", "", top_losers.to_markdown(index=False), "", "## Portfolio Rule Sensitivity", "", sensitivity.to_markdown(index=False)]
    _write_markdown(os.path.join(output_dir, "trade_concentration_report.md"), md)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", default=None)
    args = parser.parse_args()

    output_dir = args.output_dir or _analysis_dir(__file__)
    horizons = {
        key: _load_horizon_data(__file__, key, spec)
        for key, spec in FINAL_EXPERIMENTS.items()
    }
    summary = build_summary_table(horizons)
    corr, overlap = build_overlap_tables(horizons)
    prob = build_probability_tables(horizons)
    monthly, tickers, markets = build_concentration_tables(horizons, __file__)
    sensitivity = build_rule_sensitivity(horizons)
    write_reports(output_dir, summary, corr, overlap, prob, monthly, tickers, markets, sensitivity)
    print(f"analysis written to {output_dir}")


if __name__ == "__main__":
    main()
