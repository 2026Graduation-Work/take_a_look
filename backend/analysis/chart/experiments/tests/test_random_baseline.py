import numpy as np
import pandas as pd
import pytest
from backtest_harness import config
from experiments.evaluation.random_baseline import compare_with_random, random_entries
from experiments.train_src.swing_strategy import SwingStrategy

CODES = ["000001", "000002", "000003", "000004", "000005", "000006"]
DAYS = pd.bdate_range("2024-01-02", periods=30)


def market(rising="000001", halted=("000006", 5)):
    rng = np.random.default_rng(7)
    rows = []
    for code in CODES:
        close = 100.0
        for number, day in enumerate(DAYS):
            previous = close
            close = previous * (1.01 if code == rising else np.exp(rng.normal(-0.002, 0.01)))
            rows.append({"Date": day, "Code": code, "Open": previous, "High": max(previous, close),
                         "Low": min(previous, close), "Close": close, "Sigma": 0.02,
                         "Trading_Halt": int((code, number) == halted), "Amount": 1e12})
    return pd.DataFrame(rows)


def model_config(top_n=2):
    cfg = config(top_n=top_n, initial_cash=1e6, up_mult=None, down_mult=None, hard_sl_mult=None)
    cfg["strategy"].update(score_column="prob_up", prob_threshold=0.8)
    return cfg


def predictions(scores):
    return pd.DataFrame([{"Date": day, "Code": code, "prob_up": scores(day, code)}
                         for day in DAYS for code in CODES])


def test_random_runs_take_as_many_picks_as_the_model_from_the_same_pool():
    cfg = model_config()
    rng = np.random.default_rng(3)
    preds = predictions(lambda day, code: rng.choice([0.5, 0.9]))
    prices = market()
    model = SwingStrategy(cfg).generate_signals(preds, prices)
    draws = [random_entries(cfg, preds, prices, model, seed) for seed in range(5)]
    for drawn in draws:
        pd.testing.assert_series_equal(drawn.sum(axis=1), model.sum(axis=1), check_names=False)
        assert not drawn.loc[DAYS[5], "000006"], "picked a halted stock"
        assert not drawn.iloc[0].any(), "entered without a lagged signal"
    pd.testing.assert_frame_equal(draws[0], random_entries(cfg, preds, prices, model, 0))
    assert not draws[0].equals(draws[1])


def test_a_model_that_ranks_the_winner_first_beats_every_random_run():
    cfg = model_config(top_n=1)
    preds = predictions(lambda day, code: 0.95 if code == "000001" else 0.85)
    prices = market()
    from experiments.backtest.local_execution import simulate
    from experiments.evaluation.backtest_metrics import calculate_trading_metrics

    model = SwingStrategy(cfg).generate_signals(preds, prices)
    result = simulate(cfg, model, prices)
    metrics = calculate_trading_metrics(result.returns(), result.trades)
    summary, distribution = compare_with_random(cfg, preds, prices, model, metrics, runs=20)
    assert len(distribution) == 20
    assert summary["random_runs"] == 20
    assert summary["total_return_percentile_vs_random"] == pytest.approx(1.0)
    assert metrics["total_return"] > summary["random_total_return_median"]
