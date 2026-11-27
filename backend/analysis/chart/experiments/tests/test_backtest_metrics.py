"""Metric definitions pinned to hand-computed values (3 days: +1%, -2%, +3%)."""
import math

import pandas as pd
import pytest
from experiments.evaluation.backtest_metrics import calculate_trading_metrics

RETURNS = pd.Series([0.01, -0.02, 0.03])


def test_return_metrics_match_hand_computation() -> None:
    metrics = calculate_trading_metrics(RETURNS)
    mean = 0.02 / 3
    volatility = math.sqrt(((0.01 - mean) ** 2 + (-0.02 - mean) ** 2 + (0.03 - mean) ** 2) / 2)
    downside = math.sqrt(0.02**2 / 3)  # Zero target over all days, not the std of losing days.
    assert metrics["total_return"] == pytest.approx(1.01 * 0.98 * 1.03 - 1)
    assert metrics["annualized_volatility"] == pytest.approx(volatility * math.sqrt(252))
    assert metrics["sharpe_ratio"] == pytest.approx(mean / volatility * math.sqrt(252))
    assert metrics["sortino_ratio"] == pytest.approx(mean / downside * math.sqrt(252))
    assert metrics["sortino_ratio"] == pytest.approx(9.165151389911678)
    assert metrics["max_drawdown"] == pytest.approx(0.98 - 1)


def test_cagr_is_undefined_below_one_year_and_equals_total_return_at_one_year() -> None:
    assert math.isnan(calculate_trading_metrics(pd.Series([0.001] * 251))["cagr"])
    metrics = calculate_trading_metrics(pd.Series([0.001] * 252))
    assert metrics["cagr"] == pytest.approx(metrics["total_return"])
    metrics = calculate_trading_metrics(pd.Series([0.001] * 504))
    assert metrics["cagr"] == pytest.approx(1.001**252 - 1)


def test_constant_returns_have_no_volatility_and_no_sharpe() -> None:
    metrics = calculate_trading_metrics(pd.Series([0.001] * 252))
    assert metrics["annualized_volatility"] == 0.0
    assert math.isnan(metrics["sharpe_ratio"])


def test_max_drawdown_includes_loss_from_initial_equity() -> None:
    assert calculate_trading_metrics(pd.Series([-0.10, 0.05]))["max_drawdown"] == pytest.approx(-0.10)


def test_max_drawdown_continues_after_missing_return() -> None:
    metrics = calculate_trading_metrics(pd.Series([0.10, float("nan"), -0.50]))
    assert metrics["max_drawdown"] == pytest.approx(-0.50)


def test_trade_metrics_use_ledger_returns_and_sessions() -> None:
    trades = pd.DataFrame({"return": [0.1, -0.05, 0.0], "pnl": [100.0, -50.0, 0.0],
                           "holding_sessions": [1, 3, 5]})
    metrics = calculate_trading_metrics(RETURNS, trades)
    assert metrics["number_of_trades"] == 3
    assert metrics["win_rate"] == pytest.approx(1 / 3)
    assert metrics["average_loss"] == pytest.approx(-0.025)
    assert metrics["payoff_ratio"] == pytest.approx(4.0)
    assert metrics["profit_factor"] == pytest.approx(2.0)
    assert metrics["average_holding_sessions"] == pytest.approx(3.0)


def test_metrics_without_trades_report_no_trade_statistics() -> None:
    metrics = calculate_trading_metrics(RETURNS)
    assert metrics["number_of_trades"] == 0
    assert math.isnan(metrics["win_rate"])
