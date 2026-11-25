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
