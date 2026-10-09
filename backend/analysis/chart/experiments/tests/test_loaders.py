# ruff: noqa: I001

import pandas as pd
import pytest

from experiments.train_src import loaders


def test_listing_interval_is_start_inclusive_and_delisting_end_exclusive(monkeypatch) -> None:
    dates = pd.date_range("2024-01-01", periods=12, freq="B")
    source = pd.DataFrame(
        {
            "Date": dates,
            "Code": ["000001"] * len(dates),
            "Open": [100.0] * len(dates),
            "High": [100.0] * len(dates),
            "Low": [100.0] * len(dates),
            "Close": [100.0] * len(dates),
            "Volume": [1] * len(dates),
        }
    )
    monkeypatch.setattr(loaders.glob, "glob", lambda _: ["/fixtures/000001.parquet"])
    monkeypatch.setattr(loaders.pd, "read_parquet", lambda _: source.copy())
    intervals = pd.DataFrame(
        {
            "Code": ["000001"],
            "ListingDate": [dates[3]],
            "DelistingDate": [dates[8]],
        }
    )

    loaded = loaders.load_parquet_data("/fixtures", universe_intervals=intervals, universe_only=True)

    assert loaded["UniverseEligible"].all()
    assert loaded["Date"].tolist() == list(dates[3:8])


def test_label_loading_keeps_requested_last_horizon_rows_with_right_buffer(monkeypatch) -> None:
    source = pd.DataFrame(
        {
            "Date": pd.date_range("2024-01-01", periods=7, freq="B"),
            "Code": ["000001"] * 7,
            "Open": [100.0] * 7,
            "High": [100.0] * 7,
            "Low": [100.0] * 7,
            "Close": [100.0] * 7,
            "Volume": [1] * 7,
            "Trading_Halt": [0] * 7,
        }
    )
    monkeypatch.setattr(loaders.glob, "glob", lambda _: ["/fixtures/000001.parquet"])
    monkeypatch.setattr(loaders.pd, "read_parquet", lambda _: source.copy())

    loaded = loaders.load_parquet_data(
        "/fixtures",
        start_date="2024-01-01",
        end_date="2024-01-05",
        label_params={"type": "fixed", "horizon": 2, "tp": 3.5, "sl": 2.0},
    )

    # 1/4 and 1/5 need the source's 1/8 and 1/9 prices to form labels. They
    # must remain in the requested output while the buffer rows themselves do not.
    assert loaded["Date"].max() == pd.Timestamp("2024-01-05")
    assert loaded["Date"].tolist() == list(pd.date_range("2024-01-01", periods=5, freq="B"))
    assert loaded["Y_Label"].notna().all()


def test_label_observation_end_purges_anchors_that_need_later_prices(monkeypatch) -> None:
    source = pd.DataFrame(
        {
            "Date": pd.date_range("2024-01-01", periods=8, freq="B"),
            "Code": ["000001"] * 8,
            "Open": [100.0] * 8,
            "High": [100.0] * 8,
            "Low": [100.0] * 8,
            "Close": [100.0] * 8,
            "Volume": [1] * 8,
            "Trading_Halt": [0] * 8,
        }
    )
    monkeypatch.setattr(loaders.glob, "glob", lambda _: ["/fixtures/000001.parquet"])
    monkeypatch.setattr(loaders.pd, "read_parquet", lambda _: source.copy())

    loaded = loaders.load_parquet_data(
        "/fixtures",
        start_date="2024-01-01",
        end_date="2024-01-05",
        label_observation_end="2024-01-05",
        label_params={"type": "fixed", "horizon": 2, "tp": 3.5, "sl": 2.0},
    )

    assert loaded["Date"].max() == pd.Timestamp("2024-01-03")


def test_label_observation_end_can_precede_requested_end(monkeypatch) -> None:
    source = pd.DataFrame(
        {
            "Date": pd.date_range("2024-01-01", periods=8, freq="B"),
            "Code": ["000001"] * 8,
            "Open": [100.0] * 8,
            "High": [100.0] * 8,
            "Low": [100.0] * 8,
            "Close": [100.0] * 8,
            "Volume": [1] * 8,
            "Trading_Halt": [0] * 8,
        }
    )
    monkeypatch.setattr(loaders.glob, "glob", lambda _: ["/fixtures/000001.parquet"])
    monkeypatch.setattr(loaders.pd, "read_parquet", lambda _: source.copy())

    loaded = loaders.load_parquet_data(
        "/fixtures",
        start_date="2024-01-01",
        end_date="2024-01-05",
        label_observation_end="2024-01-04",
        label_params={"type": "fixed", "horizon": 2, "tp": 3.5, "sl": 2.0},
    )

    assert loaded["Date"].max() == pd.Timestamp("2024-01-02")


def test_live_top200_alias_is_rejected_for_reproducibility(monkeypatch) -> None:
    monkeypatch.setattr(loaders.glob, "glob", lambda _: ["/fixtures/005930.parquet"])

    with pytest.raises(ValueError, match="재현"):
        loaders.load_parquet_data("/fixtures", tickers="KOSPI_TOP200")
