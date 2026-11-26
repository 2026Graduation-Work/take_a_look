import numpy as np
import pandas as pd
from experiments.train_src.swing_strategy import SwingStrategy


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

    entries = SwingStrategy({"strategy": {"prob_threshold": 0.8, "top_n": 1}}).generate_signals(
        predictions, market
    )

    assert not entries.loc[dates[2], "000001"]
    assert not entries.loc[dates[3], "000001"]
    assert not entries.loc[dates[4], "000001"]


def test_rank_only_selection_ignores_how_large_a_model_writes_its_scores() -> None:
    # Two models with the same ordering but different score scales must buy the same stocks.
    # An absolute threshold (0.65) would instead reward the model that writes larger numbers.
    dates = pd.date_range("2024-01-02", periods=6, freq="B")
    codes = [f"00000{i}" for i in range(1, 7)]
    market = pd.DataFrame([{"Date": day, "Code": code, "Open": 100.0, "Trading_Halt": 0,
                            "Sigma": 0.1} for day in dates for code in codes])
    rng = np.random.default_rng(0)
    modest = pd.DataFrame([{"Date": day, "Code": code, "prob_up": rng.uniform(0.2, 0.6)}
                           for day in dates for code in codes])
    confident = modest.assign(prob_up=modest.prob_up * 0.5 + 0.45)  # Same order, larger numbers.

    def picks(predictions, threshold):
        strategy = {"score_column": "prob_up", "prob_threshold": threshold, "top_n": 2}
        return SwingStrategy({"strategy": strategy}).generate_signals(predictions, market)

    pd.testing.assert_frame_equal(picks(modest, 0.0), picks(confident, 0.0))
    assert picks(modest, 0.65).sum().sum() == 0
    assert picks(confident, 0.65).sum().sum() > 0


def test_missing_prediction_does_not_take_a_slot_from_a_real_zero_score() -> None:
    dates = pd.date_range("2024-01-02", periods=2, freq="B")
    codes = [f"00000{i}" for i in range(1, 7)]
    market = pd.DataFrame([{"Date": day, "Code": code, "Open": 100.0, "Trading_Halt": 0,
                            "Sigma": 0.1} for day in dates for code in codes])
    scores = {"000002": 0.8, "000003": 0.8, "000004": 0.8, "000005": 0.8, "000006": 0.0}
    for unscored in ({}, {"000001": np.nan}):  # 000001 has no prediction row, or an empty score.
        predictions = pd.DataFrame([{"Date": day, "Code": code, "Prob": prob} for day in dates
                                    for code, prob in {**unscored, **scores}.items()])

        entries = SwingStrategy({"strategy": {"prob_threshold": 0.0, "top_n": 5}}).generate_signals(
            predictions, market
        )

        assert entries.loc[dates[1]][entries.loc[dates[1]]].index.tolist() == list(scores)
