"""Random top-N control: the model's execution rules with the model's picks replaced by chance.

Each run picks, on every day, as many stocks as the model entered, uniformly from the
stocks the strategy could have entered that day. Everything else (lag, eligibility,
barriers, costs, sizing) is identical, so the gap to the model is the value of its ranking.
"""
from copy import deepcopy

import numpy as np
import pandas as pd
from experiments.backtest.local_execution import simulate
from experiments.evaluation.backtest_metrics import calculate_trading_metrics
from experiments.train_src.swing_strategy import SwingStrategy

COMPARED = ("total_return", "sharpe_ratio", "max_drawdown")


def random_entries(config, predictions, prices, model_entries, seed):
    rng = np.random.default_rng(seed)
    score = config["strategy"]["score_column"]
    shuffled = predictions.assign(**{score: rng.random(len(predictions))})
    pool_config = deepcopy(config)
    # No threshold and no top-N cut: the pool is every stock the strategy could enter.
    pool_config["strategy"].update(prob_threshold=0.0, top_n=predictions.Code.nunique())
    pool = SwingStrategy(pool_config).generate_signals(shuffled, prices)
    order = pd.DataFrame(rng.random(pool.shape), index=pool.index, columns=pool.columns)
    rank = order.where(pool).rank(axis=1, method="first")
    return rank.le(model_entries.sum(axis=1), axis=0)


def compare_with_random(config, predictions, prices, model_entries, model_metrics, runs):
    rows = []
    for seed in range(runs):
        entries = random_entries(config, predictions, prices, model_entries, seed)
        result = simulate(config, entries, prices)
        metrics = calculate_trading_metrics(result.returns(), result.trades)
        rows.append({"seed": seed, **{name: metrics[name] for name in COMPARED}})
    distribution = pd.DataFrame(rows)
    summary = {"random_runs": runs}
    for name in COMPARED:
        values = distribution[name]
        summary[f"random_{name}_median"] = float(values.median())
        # Share of random runs the model beat; drawdown is negative, so higher is better too.
        summary[f"{name}_percentile_vs_random"] = float((values < model_metrics[name]).mean())
    return summary, distribution
