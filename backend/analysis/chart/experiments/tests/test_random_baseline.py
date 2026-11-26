import math

import numpy as np
import pandas as pd
import pytest
from backtest_harness import check_ledger, config
from experiments.backtest.local_execution import simulate
from experiments.evaluation.backtest_metrics import calculate_trading_metrics
from experiments.evaluation.random_baseline import (
    compare_with_random,
    daily_buy_counts,
    random_run,
)
from experiments.train_src.swing_strategy import SwingStrategy

CODES = ["000001", "000002", "000003", "000004", "000005", "000006"]
DAYS = pd.bdate_range("2024-01-02", periods=30)


def market(rising="000001", halted=("000006", 5), days=DAYS, codes=CODES, flat=False):
    rng = np.random.default_rng(7)
    rows = []
    for code in codes:
        close = 100.0
        for number, day in enumerate(days):
            previous = close
            if not flat:
                close = previous * (1.01 if code == rising else np.exp(rng.normal(-0.002, 0.01)))
            rows.append({"Date": day, "Code": code, "Open": previous, "High": max(previous, close),
                         "Low": min(previous, close), "Close": close, "Sigma": 0.02,
                         "Trading_Halt": int((code, number) == halted), "Amount": 1e12})
    return pd.DataFrame(rows)


def model_config(top_n=2, **backtest):
    cfg = config(**{"top_n": top_n, "initial_cash": 1e6, "up_mult": None, "down_mult": None,
                    "hard_sl_mult": None, **backtest})
    cfg["strategy"].update(score_column="prob_up", prob_threshold=0.8)
    return cfg


def predictions(scores, days=DAYS, codes=CODES):
    return pd.DataFrame([{"Date": day, "Code": code, "prob_up": scores(day, code)}
                         for day in days for code in codes])


def run_model(cfg, preds, prices):
    result = simulate(cfg, SwingStrategy(cfg).generate_signals(preds, prices), prices)
    return result, calculate_trading_metrics(result.returns(), result.trades)


def test_random_runs_buy_as_many_stocks_as_the_model_actually_bought_each_day():
    # The model signals A every day but, holding it for 3 sessions, only buys on days 1 and 4.
    days, codes = DAYS[:7], ["000001", "000002", "000003"]
    prices = market(days=days, codes=codes, halted=None, flat=True)
    cfg = model_config(top_n=1, initial_cash=3000.0)
    preds = predictions(lambda day, code: 0.9 if code == "000001" else 0.5, days, codes)
    model, _ = run_model(cfg, preds, prices)
    target = daily_buy_counts(model)
    assert target.to_dict() == {days[1]: 1, days[4]: 1}
    for seed in range(5):
        result = random_run(cfg, preds, prices, target, seed)
        check_ledger(result, cfg, prices)
        assert daily_buy_counts(result).to_dict() == target.to_dict()
        assert result.unfilled_buys == 0


def test_random_runs_buy_nothing_when_the_model_bought_nothing():
    prices = market()
    cfg = model_config(initial_cash=1.0)  # Signals exist, but no order is affordable.
    preds = predictions(lambda day, code: 0.9)
    model, _ = run_model(cfg, preds, prices)
    assert model.events.empty
    result = random_run(model_config(), preds, prices, daily_buy_counts(model), 0)
    assert result.events.empty


def test_random_runs_skip_halted_stocks_and_repeat_with_the_same_seed():
    prices = market()
    cfg = model_config()
    rng = np.random.default_rng(3)
    preds = predictions(lambda day, code: rng.choice([0.5, 0.9]))
    model, _ = run_model(cfg, preds, prices)
    target = daily_buy_counts(model)
    first = random_run(cfg, preds, prices, target, 0)
    buys = first.events.loc[first.events.side.eq("buy")]
    assert not ((buys.code == "000006") & (pd.to_datetime(buys.date).dt.normalize() == DAYS[5])).any()
    pd.testing.assert_frame_equal(first.events, random_run(cfg, preds, prices, target, 0).events)
    assert not first.events.equals(random_run(cfg, preds, prices, target, 1).events)


def test_a_model_that_ranks_the_winner_first_beats_every_random_run():
    cfg = model_config(top_n=1)
    preds = predictions(lambda day, code: 0.95 if code == "000001" else 0.85)
    prices = market()
    model, metrics = run_model(cfg, preds, prices)
    summary, distribution = compare_with_random(cfg, preds, prices, model, metrics, runs=20)
    assert len(distribution) == 20
    assert summary["random_unfilled_buys"] == 0
    assert summary["total_return_percentile_vs_random"] == pytest.approx(1.0)
    assert metrics["total_return"] > summary["random_total_return_median"]


def test_undefined_metrics_are_not_counted_as_losses():
    # Flat prices and no trades: Sharpe is undefined for the model and every random run.
    prices = market(flat=True, halted=None)
    cfg = model_config()
    preds = predictions(lambda day, code: 0.5)
    model, metrics = run_model(cfg, preds, prices)
    summary, _ = compare_with_random(cfg, preds, prices, model, metrics, runs=2)
    assert math.isnan(metrics["sharpe_ratio"])
    assert math.isnan(summary["sharpe_ratio_percentile_vs_random"])
    assert summary["sharpe_ratio_valid_runs"] == 0


def test_reporting_progress_preserves_the_random_result():
    prices = market()
    cfg = model_config()
    preds = predictions(lambda day, code: 0.9)
    model, metrics = run_model(cfg, preds, prices)
    expected, expected_distribution = compare_with_random(cfg, preds, prices, model, metrics, 3)
    steps = []
    actual, distribution = compare_with_random(
        cfg, preds, prices, model, metrics, 3, on_progress=lambda i, n: steps.append((i, n)),
    )
    assert steps == [(1, 3), (2, 3), (3, 3)]
    assert actual == expected
    pd.testing.assert_frame_equal(distribution, expected_distribution)


def test_valid_runs_counts_only_runs_actually_compared_with_the_model():
    # The model always buys a stock that never moves, so its Sharpe is undefined, while random
    # runs buy moving stocks and get a finite Sharpe. Nothing is compared, so 0 and NaN.
    flat_code = "000009"
    prices = pd.concat([market(halted=None), market(codes=[flat_code], halted=None, flat=True)])
    cfg = model_config(top_n=1)
    preds = predictions(lambda day, code: 0.95 if code == flat_code else 0.85,
                        codes=[*CODES, flat_code])
    model, metrics = run_model(cfg, preds, prices)
    assert not model.events.empty and math.isnan(metrics["sharpe_ratio"])
    summary, distribution = compare_with_random(cfg, preds, prices, model, metrics, runs=4)
    assert np.isfinite(distribution.sharpe_ratio).any()
    assert summary["sharpe_ratio_valid_runs"] == 0
    assert math.isnan(summary["sharpe_ratio_percentile_vs_random"])
    assert np.isfinite(summary["random_sharpe_ratio_median"])
