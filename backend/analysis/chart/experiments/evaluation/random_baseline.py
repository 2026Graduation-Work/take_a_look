"""Random top-N control: the model's execution rules with the model's picks replaced by chance.

Each run buys, on every day, as many stocks as the model actually bought that day (filled
orders, not signals). Candidates are every stock the strategy could enter that day, tried in
a random order; one that is already held or cannot be filled is skipped for the next. Days that
still fall short are counted in `random_unfilled_buys`. Lag, eligibility, barriers, costs and
sizing are identical, so the daily number of new positions matches the model; holding periods
and exits still follow each run's own prices, so exposure matches only approximately.
"""
from copy import deepcopy

import numpy as np
import pandas as pd
from experiments.backtest.local_execution import simulate
from experiments.evaluation.backtest_metrics import calculate_trading_metrics
from experiments.train_src.swing_strategy import SwingStrategy

COMPARED = ("total_return", "sharpe_ratio", "max_drawdown")


def daily_buy_counts(result):
    if result.events.empty:
        return pd.Series(dtype=int)
    buys = result.events.loc[result.events.side.eq("buy")]
    return pd.to_datetime(buys.date).dt.normalize().value_counts()


def random_run(config, predictions, prices, daily_buys, seed):
    rng = np.random.default_rng(seed)
    score = config["strategy"]["score_column"]
    shuffled = predictions.assign(**{score: rng.random(len(predictions))})
    pool_config = deepcopy(config)
    # No threshold and no top-N cut: the pool is every stock the strategy could enter.
    pool_config["strategy"].update(prob_threshold=0.0, top_n=predictions.Code.nunique())
    pool = SwingStrategy(pool_config).generate_signals(shuffled, prices)
    priority = pd.DataFrame(rng.random(pool.shape), index=pool.index, columns=pool.columns)
    return simulate(config, pool, prices, priority=priority, daily_buys=daily_buys)


def compare_with_random(config, predictions, prices, model_result, model_metrics, runs):
    daily_buys = daily_buy_counts(model_result)
    rows = []
    for seed in range(runs):
        result = random_run(config, predictions, prices, daily_buys, seed)
        metrics = calculate_trading_metrics(result.returns(), result.trades)
        rows.append({"seed": seed, "unfilled_buys": result.unfilled_buys,
                     **{name: metrics.get(name, np.nan) for name in COMPARED}})
    distribution = pd.DataFrame(rows, columns=["seed", "unfilled_buys", *COMPARED])
    summary = {"random_runs": runs, "random_unfilled_buys": int(distribution.unfilled_buys.sum())}
    for name in COMPARED:
        model_value = model_metrics.get(name, np.nan)
        values = distribution[name].astype(float)
        valid = values[np.isfinite(values)]
        summary[f"random_{name}_median"] = float(valid.median()) if len(valid) else np.nan
        # Runs actually compared with the model: none when the model's own value is undefined.
        compared = valid if np.isfinite(model_value) else valid.iloc[0:0]
        summary[f"{name}_valid_runs"] = len(compared)
        # Share of compared random runs the model beat; drawdown is negative, so higher is
        # better too. Undefined on either side (e.g. no volatility) is not a loss: it is NaN.
        summary[f"{name}_percentile_vs_random"] = (
            float((compared < model_value).mean()) if len(compared) else np.nan
        )
    return summary, distribution
