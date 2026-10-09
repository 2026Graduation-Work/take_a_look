# ruff: noqa: I001

import pandas as pd

from experiments.evaluation.baselines import (
    generate_ma_breakout_signals,
    generate_momentum_signals,
    generate_random_top_k_signals,
    restrict_signals_to_test_folds,
)
from experiments.train_src.swing_strategy import SwingStrategy


def _market_frame() -> pd.DataFrame:
    dates = pd.date_range("2024-01-02", periods=4, freq="B")
    # 000002 is listed only on the final two dates.
    return pd.DataFrame(
        {
            "Date": [*dates, *dates[2:]],
            "Code": ["000001"] * 4 + ["000002"] * 2,
            "Open": [100.0, 101.0, 102.0, 103.0, 50.0, 51.0],
            "Close": [100.0, 101.0, 102.0, 103.0, 50.0, 51.0],
            "Trading_Halt": [0] * 6,
        }
    )


def test_baselines_never_enter_before_a_stock_is_listed() -> None:
    market = _market_frame()
    listing_date = pd.Timestamp("2024-01-04")

    for signals in (
        generate_random_top_k_signals(market, top_n=2, seed=1),
        generate_momentum_signals(market, top_n=2, horizon=1),
        generate_ma_breakout_signals(market, top_n=2, window=1),
    ):
        entries, _ = signals
        assert not entries.loc[entries.index < listing_date, "000002"].any()


def test_strategy_keeps_embargo_market_dates_so_shift_cannot_cross_fold_boundary() -> None:
    dates = pd.date_range("2024-01-02", periods=5, freq="B")
    market = pd.DataFrame(
        {
            "Date": dates,
            "Code": ["000001"] * len(dates),
            "Open": [100.0] * len(dates),
            "Trading_Halt": [0] * len(dates),
            "Sigma": [0.1] * len(dates),
        }
    )
    # Jan 3 is a fold's final prediction day. Jan 4/5 are embargo market days;
    # Jan 8 is the next fold's first prediction day.
    predictions = pd.DataFrame(
        {
            "Date": [dates[1], dates[4]],
            "Code": ["000001", "000001"],
            "Prob": [0.9, 0.0],
        }
    )

    entries, _ = SwingStrategy({"strategy": {"prob_threshold": 0.8, "top_n": 1}}).generate_signals(
        predictions, market
    )

    assert not entries.loc[dates[2], "000001"]
    assert not entries.loc[dates[3], "000001"]
    assert not entries.loc[dates[4], "000001"]


def test_baseline_entries_are_blocked_between_test_folds() -> None:
    dates = pd.date_range("2024-01-02", periods=6, freq="B")
    entries = pd.DataFrame(True, index=dates, columns=["000001"])
    weights = pd.DataFrame(1.0, index=dates, columns=["000001"])
    splits = [
        {"test_start": dates[0], "test_end": dates[1]},
        {"test_start": dates[4], "test_end": dates[5]},
    ]

    restricted_entries, restricted_weights = restrict_signals_to_test_folds(
        entries, weights, splits
    )

    assert restricted_entries.loc[dates[[0, 1, 4, 5]], "000001"].all()
    assert not restricted_entries.loc[dates[[2, 3]], "000001"].any()
    assert restricted_weights.loc[dates[[2, 3]], "000001"].isna().all()
