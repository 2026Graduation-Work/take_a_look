"""Causal feature construction and true VWAP are required for live inference."""

import pandas as pd
import pytest
from serving.internal.features import build_feature_frame
from serving.internal.prices import attach_actual_vwap


def test_feature_prefix_is_unchanged_by_future_prices_and_has_no_label():
    dates = pd.bdate_range("2024-01-02", periods=75)
    raw = pd.DataFrame(
        {
            "Date": dates,
            "Open": [100 + i for i in range(75)],
            "High": [102 + i for i in range(75)],
            "Low": [99 + i for i in range(75)],
            "Close": [101 + i for i in range(75)],
            "Volume": [1000 + i for i in range(75)],
            "VWAP": [100.5 + i for i in range(75)],
        }
    )
    full = build_feature_frame(raw, set(dates.date))
    prefix = build_feature_frame(raw.iloc[:70], set(dates[:70].date))
    pd.testing.assert_frame_equal(full.iloc[:70], prefix)
    assert "Y_Label" not in full
    assert full["vwap_0"].iloc[0] == pytest.approx(100.5 / (101 + 1e-8))
    assert full["Barrier_Up"].iloc[-1] == pytest.approx(
        full["Close"].iloc[-1] * (1 + 1.5 * full["Sigma"].iloc[-1])
    )
    assert full["Barrier_Down"].iloc[-1] == pytest.approx(
        full["Close"].iloc[-1] * (1 - 1.2 * full["Sigma"].iloc[-1])
    )


def test_missing_actual_vwap_fails_closed():
    raw = pd.DataFrame(
        {"Date": ["2024-01-02"], "Open": [100], "High": [101],
         "Low": [99], "Close": [100], "Volume": [1]}
    )
    with pytest.raises(ValueError, match="VWAP"):
        build_feature_frame(raw, {"2024-01-02"})


def test_adjusted_vwap_uses_actual_turnover_and_price_scale():
    dates = pd.to_datetime(["2024-01-02"])
    adjusted = pd.DataFrame({"Close": [50.0], "Volume": [100.0]}, index=dates)
    raw = pd.DataFrame(
        {"종가": [100.0], "거래량": [100.0], "거래대금": [10500.0]}, index=dates
    )
    result = attach_actual_vwap(adjusted, raw)
    assert result["AdjustmentFactor"].iloc[0] == 0.5
    assert result["VWAP"].iloc[0] == 52.5


def test_price_history_uses_observed_dates_and_rejects_duplicates():
    from serving.internal.prices import price_snapshot

    frame = pd.DataFrame({"Date": ["2026-01-02", "2026-01-05", "2026-01-07"],
                          "Close": [100, 110, 999], "Volume": [10, 20, 30]})
    row = price_snapshot(frame, "005930", "2026-01-06", "test")
    assert row["status"] == "stale" and row["data_asof"] == "2026-01-05"
    assert row["close"] == 110 and row["change_percent"] == pytest.approx(10)
    assert len(row["history"]) == 2
    with pytest.raises(ValueError, match="duplicate"):
        price_snapshot(pd.concat([frame, frame]), "005930", "2026-01-06", "test")
