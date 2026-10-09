import argparse  # noqa: I001
import math
import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd


EXPERIMENTS_DIR = Path(__file__).resolve().parents[2]
CHART_ROOT = EXPERIMENTS_DIR.parent
ROOT = CHART_ROOT.parents[1]
if str(EXPERIMENTS_DIR) not in sys.path:
    sys.path.insert(0, str(EXPERIMENTS_DIR))
DEFAULT_OUTPUT_DIR = EXPERIMENTS_DIR / "results" / "factor_attribution"

FACTOR_COLUMNS = [
    "market",
    "size",
    "momentum_20",
    "momentum_60",
    "volatility",
    "liquidity",
    "distress",
    "preferred",
    "spac",
    "speculative_proxy",
]
EXPOSURE_COLUMNS = [
    "is_preferred",
    "is_spac",
    "is_distress",
    "size_pct",
    "momentum_20_pct",
    "momentum_60_pct",
    "volatility_pct",
    "liquidity_pct",
    "speculative_proxy",
]


def log(message: str) -> None:
    print(message, flush=True)


def normalize_code(value) -> str:
    if pd.isna(value):
        return np.nan
    text = str(value).strip()
    if text.endswith(".0"):
        text = text[:-2]
    return text.zfill(6) if re.fullmatch(r"\d+", text) else text


def markdown_table(df: pd.DataFrame, floatfmt: str = ".4f", index: bool = False) -> str:
    table = df.reset_index() if index else df.copy()
    if table.empty:
        return "_No rows._"
    formatted = table.astype("object")
    for col in formatted.columns:
        if pd.api.types.is_numeric_dtype(table[col]):
            formatted[col] = table[col].map(lambda x: "" if pd.isna(x) else format(float(x), floatfmt))
        else:
            formatted[col] = table[col].map(lambda x: "" if pd.isna(x) else str(x))
    headers = [str(c) for c in formatted.columns]
    rows = formatted.values.tolist()
    widths = [max(len(headers[i]), *(len(str(row[i])) for row in rows)) for i in range(len(headers))]
    lines = [
        "| " + " | ".join(headers[i].ljust(widths[i]) for i in range(len(headers))) + " |",
        "| " + " | ".join("-" * widths[i] for i in range(len(headers))) + " |",
    ]
    lines.extend(
        "| " + " | ".join(str(row[i]).ljust(widths[i]) for i in range(len(headers))) + " |"
        for row in rows
    )
    return "\n".join(lines)


def load_final_experiments(results_dir: Path, cache_dir: Path) -> list[dict]:
    summary_path = results_dir / "horizon_final_analysis" / "horizon_final_summary.csv"
    if not summary_path.exists():
        raise FileNotFoundError(f"Missing final horizon summary: {summary_path}")
    summary = pd.read_csv(summary_path)
    experiments = []
    for _, row in summary.iterrows():
        name = row["Experiment"]
        result_dir = results_dir / name
        pred_hash = str(row["Prediction Hash"])
        experiments.append(
            {
                "horizon_label": row["Horizon"],
                "horizon": int(str(row["Horizon"]).replace("H", "")),
                "multiplier": row["Multiplier"],
                "name": name,
                "prediction_hash": pred_hash,
                "returns_path": result_dir / "daily_returns.csv",
                "trades_path": result_dir / "trades.csv",
                "predictions_path": cache_dir / f"{pred_hash}_predictions.parquet",
                "top_n": 5,
                "prob_threshold": 0.65,
                "reported_total_return": row["Total Return"],
                "reported_cagr": row["CAGR"],
                "reported_sharpe": row["Sharpe"],
                "reported_mdd": row["MDD"],
                "reported_trades": row["Trades"],
            }
        )
    return experiments


def load_metadata(data_dir: Path) -> pd.DataFrame:
    meta = pd.read_csv(data_dir / "ticker_metadata.csv", dtype={"Code": "string"})
    meta["Code"] = meta["Code"].map(normalize_code)
    return meta.drop_duplicates("Code", keep="last")


def load_panel(processed_dir: Path, start: pd.Timestamp | None, end: pd.Timestamp | None) -> pd.DataFrame:
    columns = [
        "Date",
        "Code",
        "Name",
        "Close",
        "Volume",
        "Change",
        "IsDelisted",
        "Trading_Halt",
        "roc_20",
        "roc_60",
        "Sigma",
    ]
    paths = sorted(processed_dir.glob("*.parquet"))
    frames = []
    for idx, path in enumerate(paths, start=1):
        df = pd.read_parquet(path, columns=columns)
        if start is not None:
            df = df[df["Date"] >= start]
        if end is not None:
            df = df[df["Date"] <= end]
        if not df.empty:
            frames.append(df)
        if idx % 300 == 0:
            log(f"Loaded {idx:,}/{len(paths):,} processed parquet files")
    if not frames:
        raise ValueError(f"No rows loaded from {processed_dir}")
    panel = pd.concat(frames, ignore_index=True).sort_values(["Code", "Date"])
    panel["Date"] = pd.to_datetime(panel["Date"])
    panel["Code"] = panel["Code"].map(normalize_code)
    return panel


def add_exposures(panel: pd.DataFrame, metadata: pd.DataFrame) -> pd.DataFrame:
    df = panel.merge(metadata[["Code", "Name", "IsDelisted"]], on="Code", how="left", suffixes=("", "_meta"))
    name = df["Name"].fillna(df["Name_meta"]).fillna("").astype(str)
    df["dollar_volume"] = df["Close"] * df["Volume"]
    df["is_preferred"] = (name.str.endswith("우") | name.str.contains("우선주", regex=False)).astype(float)
    df["is_spac"] = name.str.contains("스팩|SPAC", case=False, regex=True).astype(float)
    # Avoid look-ahead leakage from current/final delisting snapshots.
    # Distress exposure uses only the contemporaneously observed halt flag.
    df["is_distress"] = (df["Trading_Halt"].fillna(0).astype(float) > 0).astype(float)

    grouped = df.groupby("Code", sort=False)
    df["mcap_proxy_lag"] = grouped["Close"].shift(1)
    df["momentum_20_lag"] = grouped["roc_20"].shift(1)
    df["momentum_60_lag"] = grouped["roc_60"].shift(1)
    df["volatility_lag"] = grouped["Sigma"].shift(1)
    df["liquidity_lag"] = grouped["dollar_volume"].transform(
        lambda values: values.shift(1).rolling(20, min_periods=5).mean()
    )
    df["forward_return_1d"] = grouped["Change"].shift(-1)

    ranked = df.groupby("Date", sort=False)
    df["size_pct"] = ranked["mcap_proxy_lag"].rank(pct=True)
    df["momentum_20_pct"] = ranked["momentum_20_lag"].rank(pct=True)
    df["momentum_60_pct"] = ranked["momentum_60_lag"].rank(pct=True)
    df["volatility_pct"] = ranked["volatility_lag"].rank(pct=True)
    df["liquidity_pct"] = ranked["liquidity_lag"].rank(pct=True)
    df["speculative_proxy"] = (
        (df["size_pct"] <= 0.30) & (df["volatility_pct"] >= 0.70) & (df["liquidity_pct"] <= 0.30)
    ).astype(float)
    return df


def spread_return(df: pd.DataFrame, exposure: str, high_long: bool = True, q: float = 0.3) -> pd.DataFrame:
    valid = df[["Date", "Change", exposure]].replace([np.inf, -np.inf], np.nan).dropna()
    rows = []
    for date, group in valid.groupby("Date", sort=True):
        if len(group) < 20:
            continue
        low_cut = group[exposure].quantile(q)
        high_cut = group[exposure].quantile(1 - q)
        low = group[group[exposure] <= low_cut]["Change"]
        high = group[group[exposure] >= high_cut]["Change"]
        if len(low) == 0 or len(high) == 0:
            continue
        value = high.mean() - low.mean() if high_long else low.mean() - high.mean()
        rows.append(
            {
                "Date": date,
                exposure: value,
                f"{exposure}_long_n": len(high if high_long else low),
                f"{exposure}_short_n": len(low if high_long else high),
            }
        )
    return pd.DataFrame(rows)


def binary_spread(df: pd.DataFrame, flag_col: str, factor_name: str) -> pd.DataFrame:
    valid = df[["Date", "Change", flag_col]].replace([np.inf, -np.inf], np.nan).dropna()
    rows = []
    for date, group in valid.groupby("Date", sort=True):
        long_side = group[group[flag_col] > 0]["Change"]
        short_side = group[group[flag_col] <= 0]["Change"]
        if len(long_side) == 0 or len(short_side) == 0:
            continue
        rows.append(
            {
                "Date": date,
                factor_name: long_side.mean() - short_side.mean(),
                f"{factor_name}_long_n": len(long_side),
                f"{factor_name}_short_n": len(short_side),
            }
        )
    return pd.DataFrame(rows)


def build_factor_returns(panel: pd.DataFrame) -> pd.DataFrame:
    out = panel.groupby("Date", sort=True)["Change"].mean().rename("market").reset_index()
    out = out.merge(panel.groupby("Date", sort=True)["Change"].size().rename("universe_n").reset_index(), on="Date")
    frames = [
        spread_return(panel, "size_pct", high_long=False).rename(columns={"size_pct": "size"}),
        spread_return(panel, "momentum_20_pct", high_long=True).rename(columns={"momentum_20_pct": "momentum_20"}),
        spread_return(panel, "momentum_60_pct", high_long=True).rename(columns={"momentum_60_pct": "momentum_60"}),
        spread_return(panel, "volatility_pct", high_long=True).rename(columns={"volatility_pct": "volatility"}),
        spread_return(panel, "liquidity_pct", high_long=False).rename(columns={"liquidity_pct": "liquidity"}),
        binary_spread(panel, "is_distress", "distress"),
        binary_spread(panel, "is_preferred", "preferred"),
        binary_spread(panel, "is_spac", "spac"),
        binary_spread(panel, "speculative_proxy", "speculative_proxy"),
    ]
    for frame in frames:
        out = out.merge(frame, on="Date", how="left")
    return out


def normal_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def ols_hac(y, x, lags: int = 5):
    y = np.asarray(y, dtype=float)
    x = np.asarray(x, dtype=float)
    valid = np.isfinite(y) & np.isfinite(x).all(axis=1)
    y = y[valid]
    x = x[valid]
    n = len(y)
    k = x.shape[1] + 1
    if n <= k + 2:
        raise ValueError("Not enough observations")
    x = np.column_stack([np.ones(n), x])
    xtx_inv = np.linalg.pinv(x.T @ x)
    beta = xtx_inv @ x.T @ y
    resid = y - x @ beta
    meat = np.zeros((k, k))
    for t in range(n):
        xt = x[t : t + 1].T
        meat += resid[t] ** 2 * (xt @ xt.T)
    max_lag = min(lags, n - 1)
    for lag in range(1, max_lag + 1):
        weight = 1.0 - lag / (max_lag + 1.0)
        gamma = np.zeros((k, k))
        for t in range(lag, n):
            gamma += resid[t] * resid[t - lag] * (x[t : t + 1].T @ x[t - lag : t - lag + 1])
        meat += weight * (gamma + gamma.T)
    cov = xtx_inv @ meat @ xtx_inv
    se = np.sqrt(np.maximum(np.diag(cov), 0.0))
    tstat = np.divide(beta, se, out=np.full_like(beta, np.nan), where=se > 0)
    pvalue = np.array([2.0 * (1.0 - normal_cdf(abs(t))) if np.isfinite(t) else np.nan for t in tstat])
    ss_res = float(np.sum(resid**2))
    ss_tot = float(np.sum((y - y.mean()) ** 2))
    r2 = 1.0 - ss_res / ss_tot if ss_tot > 0 else np.nan
    adjusted = beta[0] + resid
    residual_sharpe = adjusted.mean() / adjusted.std(ddof=1) * math.sqrt(252) if adjusted.std(ddof=1) > 0 else np.nan
    return beta, se, tstat, pvalue, r2, residual_sharpe, n


def calc_return_stats(returns: pd.Series) -> dict:
    returns = returns.dropna()
    if returns.empty:
        return {}
    curve = (1.0 + returns).cumprod()
    ann = curve.iloc[-1] ** (252.0 / len(returns)) - 1.0
    vol = returns.std(ddof=1) * math.sqrt(252)
    return {
        "total_return": curve.iloc[-1] - 1.0,
        "annual_return": ann,
        "annual_volatility": vol,
        "sharpe": ann / vol if vol > 0 else np.nan,
        "mdd": ((curve / curve.cummax()) - 1.0).min(),
        "observations": len(returns),
    }


def run_attribution(experiments: list[dict], factor_returns: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    rows = []
    contrib_rows = []
    factors = [c for c in FACTOR_COLUMNS if c in factor_returns.columns]
    for exp in experiments:
        daily = pd.read_csv(exp["returns_path"], parse_dates=["Date"])
        merged = daily[["Date", "Portfolio"]].merge(factor_returns[["Date"] + factors], on="Date", how="inner")
        xcols = [c for c in factors if merged[c].notna().sum() >= 30]
        regression_df = merged[["Portfolio"] + xcols].dropna()
        beta, se, tstat, pvalue, r2, residual_sharpe, nobs = ols_hac(
            regression_df["Portfolio"], regression_df[xcols], lags=max(1, min(10, exp["horizon"]))
        )
        terms = ["alpha"] + xcols
        for i, term in enumerate(terms):
            rows.append(
                {
                    "horizon": exp["horizon_label"],
                    "experiment": exp["name"],
                    "term": term,
                    "coef_daily": beta[i],
                    "coef_annualized": beta[i] * 252 if term == "alpha" else beta[i],
                    "hac_se": se[i],
                    "t_stat": tstat[i],
                    "p_value": pvalue[i],
                    "r2": r2,
                    "residual_sharpe": residual_sharpe,
                    "n_obs": nobs,
                }
            )
        means = regression_df[xcols].mean()
        total_ann = regression_df["Portfolio"].mean() * 252
        for i, term in enumerate(xcols, start=1):
            value = beta[i] * means[term] * 252
            contrib_rows.append(
                {
                    "horizon": exp["horizon_label"],
                    "experiment": exp["name"],
                    "component": term,
                    "annualized_return_contribution": value,
                    "share_of_mean_return": value / total_ann if total_ann else np.nan,
                }
            )
        alpha_ann = beta[0] * 252
        contrib_rows.append(
            {
                "horizon": exp["horizon_label"],
                "experiment": exp["name"],
                "component": "unexplained_alpha",
                "annualized_return_contribution": alpha_ann,
                "share_of_mean_return": alpha_ann / total_ann if total_ann else np.nan,
            }
        )
    return pd.DataFrame(rows), pd.DataFrame(contrib_rows)


def parse_trade_code(value) -> str:
    match = re.search(r"[0-9A-Z]{6}", str(value))
    return match.group(0) if match else np.nan


def exposure_summary(selection: pd.DataFrame, panel: pd.DataFrame, label: str, exp: dict) -> list[dict]:
    if selection.empty:
        return []
    merged = selection.merge(panel[["Date", "Code"] + EXPOSURE_COLUMNS], on=["Date", "Code"], how="left")
    universe = panel.groupby("Date")[EXPOSURE_COLUMNS].agg(["mean", "std"]).reset_index()
    universe.columns = [c[0] if c[1] == "" else f"{c[0]}_{c[1]}" for c in universe.columns.to_flat_index()]
    rows = []
    for col in EXPOSURE_COLUMNS:
        selected_mean = merged[col].mean()
        date_means = selection[["Date"]].drop_duplicates().merge(
            universe[["Date", f"{col}_mean", f"{col}_std"]], on="Date", how="left"
        )
        universe_mean = date_means[f"{col}_mean"].mean()
        universe_std = date_means[f"{col}_std"].replace(0, np.nan).mean()
        rows.append(
            {
                "horizon": exp["horizon_label"],
                "experiment": exp["name"],
                "selection_type": label,
                "factor": col,
                "selected_mean": selected_mean,
                "selected_median": merged[col].median(),
                "matched_rows": merged[col].notna().sum(),
                "universe_date_mean": universe_mean,
                "universe_date_std": universe_std,
                "selected_z_vs_universe": (selected_mean - universe_mean) / universe_std
                if pd.notna(universe_std) and universe_std != 0
                else np.nan,
            }
        )
    return rows


def run_exposure_analysis(experiments: list[dict], panel: pd.DataFrame) -> pd.DataFrame:
    rows = []
    prediction_cache = {}
    for exp in experiments:
        log(f"Exposure analysis: {exp['horizon_label']}")
        trades = pd.read_csv(exp["trades_path"])
        trades["Date"] = pd.to_datetime(trades["Entry Timestamp"])
        trades["Code"] = trades["Column"].map(parse_trade_code)
        rows.extend(exposure_summary(trades[["Date", "Code"]], panel, "trades", exp))
        key = str(exp["predictions_path"])
        if key not in prediction_cache:
            preds = pd.read_parquet(exp["predictions_path"], columns=["Date", "Code", "Prob"])
            preds["Date"] = pd.to_datetime(preds["Date"])
            preds["Code"] = preds["Code"].map(normalize_code)
            prediction_cache[key] = preds
        preds = prediction_cache[key]
        filtered = preds[preds["Prob"] >= exp["prob_threshold"]]
        if filtered.empty:
            filtered = preds
        top = filtered.sort_values(["Date", "Prob"], ascending=[True, False]).groupby("Date", sort=False).head(exp["top_n"])
        rows.extend(exposure_summary(top[["Date", "Code"]], panel, "prediction_topk", exp))
    return pd.DataFrame(rows)


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


def topk_forward_return(df: pd.DataFrame, score_col: str, top_n: int, threshold: float | None = None) -> pd.Series:
    data = df.dropna(subset=[score_col, "forward_return_1d"])
    if threshold is not None:
        filtered = data[data[score_col] >= threshold]
        if not filtered.empty:
            data = filtered
    return (
        data.sort_values(["Date", score_col], ascending=[True, False])
        .groupby("Date", sort=False)
        .head(top_n)
        .groupby("Date")["forward_return_1d"]
        .mean()
    )


def run_factor_neutral_score(experiments: list[dict], panel: pd.DataFrame) -> pd.DataFrame:
    rows = []
    xcols = EXPOSURE_COLUMNS
    base = panel[["Date", "Code", "forward_return_1d"] + xcols]
    for exp in experiments:
        log(f"Factor-neutral score: {exp['horizon_label']}")
        preds = pd.read_parquet(exp["predictions_path"], columns=["Date", "Code", "Prob"])
        preds["Date"] = pd.to_datetime(preds["Date"])
        preds["Code"] = preds["Code"].map(normalize_code)
        merged = preds.merge(base, on=["Date", "Code"], how="inner")
        usable_cols = [c for c in xcols if merged[c].notna().sum() > 100]
        merged["neutral_score"] = merged.groupby("Date", group_keys=False).apply(
            lambda g, columns=usable_cols: cross_sectional_residuals(g, columns)
        )
        for score, series in [
            ("raw_prob", topk_forward_return(merged, "Prob", exp["top_n"], exp["prob_threshold"])),
            ("factor_neutral_residual", topk_forward_return(merged, "neutral_score", exp["top_n"])),
        ]:
            stats = calc_return_stats(series)
            stats.update(
                {
                    "horizon": exp["horizon_label"],
                    "experiment": exp["name"],
                    "score": score,
                    "top_n": exp["top_n"],
                    "prob_threshold": exp["prob_threshold"] if score == "raw_prob" else np.nan,
                    "prediction_hash": exp["prediction_hash"],
                }
            )
            rows.append(stats)
    return pd.DataFrame(rows)


def run_filter_ablation(experiments: list[dict], attribution: pd.DataFrame) -> pd.DataFrame:
    alpha = attribution[attribution["term"] == "alpha"][
        ["experiment", "coef_annualized", "t_stat", "p_value", "r2", "residual_sharpe"]
    ]
    rows = []
    for exp in experiments:
        daily = pd.read_csv(exp["returns_path"])
        stats = calc_return_stats(daily["Portfolio"])
        stats.update(
            {
                "horizon": exp["horizon_label"],
                "experiment": exp["name"],
                "reported_total_return": exp["reported_total_return"],
                "reported_cagr": exp["reported_cagr"],
                "reported_sharpe": exp["reported_sharpe"],
                "reported_mdd": exp["reported_mdd"],
                "reported_trades": exp["reported_trades"],
            }
        )
        rows.append(stats)
    return pd.DataFrame(rows).merge(alpha, on="experiment", how="left")


def factor_diagnostics(factor_returns: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    factors = [c for c in FACTOR_COLUMNS if c in factor_returns.columns]
    data = factor_returns[factors].dropna(how="all")
    corr = data.corr()
    vif_rows = []
    sub = data.dropna()
    for col in factors:
        y = sub[col].to_numpy(dtype=float)
        xcols = [c for c in factors if c != col]
        if len(sub) <= len(xcols) + 5:
            vif = np.nan
        else:
            x = np.column_stack([np.ones(len(sub)), sub[xcols].to_numpy(dtype=float)])
            beta = np.linalg.pinv(x.T @ x) @ x.T @ y
            resid = y - x @ beta
            ss_res = np.sum(resid**2)
            ss_tot = np.sum((y - y.mean()) ** 2)
            r2 = 1.0 - ss_res / ss_tot if ss_tot > 0 else np.nan
            vif = 1.0 / (1.0 - r2) if pd.notna(r2) and r2 < 1 else np.inf
        vif_rows.append({"factor": col, "vif": vif})
    return corr, pd.DataFrame(vif_rows)


def write_report(
    output_dir: Path,
    experiments: list[dict],
    factor_returns: pd.DataFrame,
    attribution: pd.DataFrame,
    contribution: pd.DataFrame,
    exposure: pd.DataFrame,
    neutral: pd.DataFrame,
    ablation: pd.DataFrame,
) -> None:
    corr, vif = factor_diagnostics(factor_returns)
    alpha = attribution[attribution["term"] == "alpha"].copy()
    beta = attribution[attribution["term"] != "alpha"].copy()
    contrib_pivot = contribution.pivot_table(
        index=["horizon", "experiment"],
        columns="component",
        values="annualized_return_contribution",
        aggfunc="first",
    ).reset_index()
    exposure_top = exposure.reindex(exposure["selected_z_vs_universe"].abs().sort_values(ascending=False).index)
    lines = [
        "# Representative Factor Attribution Report",
        "",
        "## Scope",
        "",
        f"- Experiments analyzed: {', '.join(exp['horizon_label'] + '=' + exp['name'] for exp in experiments)}",
        "- Universe-level market factor uses equal-weight processed universe returns.",
        "- KOSDAQ stock-level exposure is not included because this repo does not contain a point-in-time market master table.",
        "- Value/quality are excluded because point-in-time fundamentals are not part of these result artifacts.",
        "",
        "## Data Checks",
        "",
        f"- Factor return rows: {len(factor_returns):,}",
        f"- Date range: {factor_returns['Date'].min().date()} to {factor_returns['Date'].max().date()}",
        f"- Median universe size: {factor_returns['universe_n'].median():,.0f}",
        "",
        "## Returns-Based Alpha",
        "",
        markdown_table(alpha[["horizon", "experiment", "coef_annualized", "t_stat", "p_value", "r2", "residual_sharpe", "n_obs"]]),
        "",
        "## Largest Absolute Betas",
        "",
        markdown_table(
            beta.assign(abs_beta=beta["coef_daily"].abs())
            .sort_values("abs_beta", ascending=False)[["horizon", "experiment", "term", "coef_daily", "t_stat", "p_value", "r2"]]
            .head(20)
        ),
        "",
        "## Annualized Contribution Summary",
        "",
        markdown_table(contrib_pivot),
        "",
        "## Holdings/Prediction Exposure Highlights",
        "",
        markdown_table(
            exposure_top[
                [
                    "horizon",
                    "selection_type",
                    "factor",
                    "selected_mean",
                    "universe_date_mean",
                    "selected_z_vs_universe",
                    "matched_rows",
                ]
            ].head(30)
        ),
        "",
        "## Factor-Neutral Score Check",
        "",
        markdown_table(
            neutral[
                [
                    "horizon",
                    "score",
                    "annual_return",
                    "annual_volatility",
                    "sharpe",
                    "mdd",
                    "observations",
                ]
            ]
        ),
        "",
        "## Backtest Reproduction And Filter Summary",
        "",
        markdown_table(ablation),
        "",
        "## Factor Correlation",
        "",
        markdown_table(corr, floatfmt=".3f", index=True),
        "",
        "## VIF",
        "",
        markdown_table(vif, floatfmt=".3f"),
        "",
        "## Interpretation",
        "",
        make_interpretation(alpha, exposure_top, neutral),
    ]
    (output_dir / "factor_attribution_report.md").write_text("\n".join(lines), encoding="utf-8")


def make_interpretation(alpha: pd.DataFrame, exposure_top: pd.DataFrame, neutral: pd.DataFrame) -> str:
    best = alpha.sort_values("coef_annualized", ascending=False).iloc[0]
    significant = alpha[alpha["p_value"] < 0.05]
    exposure_lines = []
    for _, row in exposure_top.head(8).iterrows():
        exposure_lines.append(
            f"- {row['horizon']} {row['selection_type']} {row['factor']}: "
            f"selected_mean={row['selected_mean']:.3f}, universe={row['universe_date_mean']:.3f}, "
            f"z={row['selected_z_vs_universe']:.2f}"
        )
    neutral_pivot = neutral.pivot_table(index="horizon", columns="score", values="sharpe", aggfunc="first")
    neutral_lines = [
        f"- {idx}: raw Sharpe={row.get('raw_prob', np.nan):.2f}, neutral Sharpe={row.get('factor_neutral_residual', np.nan):.2f}"
        for idx, row in neutral_pivot.iterrows()
    ]
    conclusion = (
        "대표 팩터 제거 후 alpha는 양수이나 통계적으로 유의하다고 보기 어렵다."
        if significant.empty
        else "일부 horizon에서 대표 팩터 제거 후 alpha가 통계적으로 유의하다."
    )
    return "\n".join(
        [
            conclusion,
            "",
            f"- 가장 큰 annualized alpha는 {best['horizon']} ({best['coef_annualized']:.2%}, "
            f"t={best['t_stat']:.2f}, p={best['p_value']:.3f})다.",
            "- R2가 낮다면 대표 팩터가 전략 일별 수익률을 충분히 설명하지 못한다는 뜻이지만, 곧바로 순수 alpha를 입증하지는 않는다.",
            "- 종목 선택 노출은 아래 항목을 우선 점검해야 한다.",
            *exposure_lines,
            "- factor-neutral residual score 단순 next-day top-k 검증:",
            *neutral_lines,
            "- 최종 판정은 factor-neutral score를 원래 backtest engine의 threshold/top_n/청산 규칙으로 재실행한 뒤 내려야 한다.",
        ]
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Representative factor attribution for final horizon experiments")
    parser.add_argument("--processed-dir", type=Path, default=CHART_ROOT / "data" / "processed")
    parser.add_argument("--data-dir", type=Path, default=CHART_ROOT / "data")
    parser.add_argument("--results-dir", type=Path, default=EXPERIMENTS_DIR / "results")
    parser.add_argument("--cache-dir", type=Path, default=EXPERIMENTS_DIR / "cache")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--start-date", default=None)
    parser.add_argument("--end-date", default=None)
    args = parser.parse_args()

    args.output_dir.mkdir(parents=True, exist_ok=True)
    start = pd.to_datetime(args.start_date) if args.start_date else None
    end = pd.to_datetime(args.end_date) if args.end_date else None

    experiments = load_final_experiments(args.results_dir, args.cache_dir)
    log(f"Loaded final experiments: {', '.join(exp['horizon_label'] for exp in experiments)}")
    metadata = load_metadata(args.data_dir)
    log("Loading processed panel")
    panel = add_exposures(load_panel(args.processed_dir, start, end), metadata)
    log(f"Panel rows: {len(panel):,}")

    log("Building factor returns")
    factor_returns = build_factor_returns(panel)
    factor_returns.to_csv(args.output_dir / "factor_return_timeseries.csv", index=False)

    log("Running returns-based attribution")
    attribution, contribution = run_attribution(experiments, factor_returns)
    attribution.to_csv(args.output_dir / "factor_attribution_summary.csv", index=False)
    contribution.to_csv(args.output_dir / "factor_contribution_summary.csv", index=False)

    log("Running exposure analysis")
    exposure = run_exposure_analysis(experiments, panel)
    exposure.to_csv(args.output_dir / "factor_exposure_by_horizon.csv", index=False)

    log("Running factor-neutral score analysis")
    neutral = run_factor_neutral_score(experiments, panel)
    neutral.to_csv(args.output_dir / "factor_neutral_score_summary.csv", index=False)

    log("Running backtest reproduction/filter summary")
    ablation = run_filter_ablation(experiments, attribution)
    ablation.to_csv(args.output_dir / "filter_ablation_summary.csv", index=False)

    log("Writing report")
    write_report(args.output_dir, experiments, factor_returns, attribution, contribution, exposure, neutral, ablation)
    print(f"Wrote factor attribution outputs to {args.output_dir}")


if __name__ == "__main__":
    main()
