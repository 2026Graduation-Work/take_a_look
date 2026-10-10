from datetime import date

import pandas as pd
import pytest
from experiments.dataset import preprocess as preprocess_data
from experiments.train_src import legacy_features as features
from shared.data import trading_calendar


@pytest.fixture
def raw_prices():
    return pd.DataFrame(
        {
            "Date": pd.to_datetime(["2026-09-24", "2026-09-29"]),
            "Open": [100.0, 102.0],
            "High": [101.0, 103.0],
            "Low": [99.0, 101.0],
            "Close": [100.0, 102.0],
            "Volume": [1000.0, 1200.0],
            "VWAP": [99.5, 101.5],
            "Code": ["005930", "005930"],
        }
    )


@pytest.mark.parametrize(
    "normalizer",
    [preprocess_data.normalize_trading_halts, features.normalize_trading_halts],
)
def test_normalizer_rejects_unverified_missing_session(raw_prices, normalizer):
    market_days = {date(2026, 9, 24), date(2026, 9, 25), date(2026, 9, 29)}
    with pytest.raises(ValueError, match="Unverified missing sessions"):
        normalizer(raw_prices, market_days)


def test_reindex_rejects_raw_row_on_non_trading_day(raw_prices):
    invalid = raw_prices.copy()
    invalid.loc[1, "Date"] = pd.Timestamp("2026-09-28")
    market_days = {date(2026, 9, 24), date(2026, 9, 25), date(2026, 9, 29)}

    with pytest.raises(trading_calendar.TradingCalendarError, match="2026-09-28"):
        trading_calendar.reindex_to_krx_trading_days(invalid, market_days)


def test_batch_calendar_covers_all_files_with_one_request(tmp_path, monkeypatch):
    first = tmp_path / "first.parquet"
    second = tmp_path / "second.parquet"
    pd.DataFrame({"Date": pd.to_datetime(["2024-01-02", "2024-01-03"])}).to_parquet(
        first, index=False
    )
    pd.DataFrame({"Date": pd.to_datetime(["2025-12-29", "2025-12-30"])}).to_parquet(
        second, index=False
    )
    calls = []

    def fake_calendar(start_date, end_date):
        calls.append((start_date, end_date))
        return {date(2024, 1, 2), date(2025, 12, 30)}

    monkeypatch.setattr(preprocess_data, "get_krx_trading_days", fake_calendar)

    result = preprocess_data._load_trading_days_for_files([str(first), str(second)])

    assert calls == [("2024-01-02", "2025-12-30")]
    assert result == {date(2024, 1, 2), date(2025, 12, 30)}


@pytest.mark.parametrize(
    "feature_generator",
    [preprocess_data.generate_full_alpha158_features, features.generate_full_alpha158_features],
)
def test_alpha158_uses_actual_vwap_column(feature_generator):
    frame = pd.DataFrame(
        {
            "Open": [99.0, 101.0],
            "High": [101.0, 103.0],
            "Low": [98.0, 100.0],
            "Close": [100.0, 102.0],
            "Volume": [1000.0, 1200.0],
            "VWAP": [105.0, 99.0],
        }
    )

    generated = feature_generator(frame)

    assert generated["vwap_0"].tolist() == pytest.approx([1.05, 99.0 / 102.0])


@pytest.mark.parametrize(
    "feature_generator",
    [preprocess_data.generate_full_alpha158_features, features.generate_full_alpha158_features],
)
def test_alpha158_rejects_hlc3_fallback(feature_generator):
    frame = pd.DataFrame(
        {"Open": [99.0], "High": [101.0], "Low": [98.0], "Close": [100.0], "Volume": [1.0]}
    )

    with pytest.raises(ValueError, match="실제 VWAP"):
        feature_generator(frame)


@pytest.mark.parametrize(
    "normalizer",
    [preprocess_data.normalize_trading_halts, features.normalize_trading_halts],
)
def test_normalizer_does_not_hide_missing_vwap_on_traded_row(raw_prices, normalizer):
    raw_prices.loc[1, "VWAP"] = pd.NA
    market_days = {date(2026, 9, 24), date(2026, 9, 29)}

    with pytest.raises(ValueError, match="positive finite OHLC/VWAP"):
        normalizer(raw_prices, market_days)


def test_processed_vwap_marker_distinguishes_legacy_file(tmp_path):
    legacy_path = tmp_path / "legacy.parquet"
    current_path = tmp_path / "current.parquet"
    pd.DataFrame({"vwap_0": [1.0]}).to_parquet(legacy_path, index=False)
    pd.DataFrame({"VWAP": [100.0], "vwap_0": [1.0]}).to_parquet(current_path, index=False)

    assert not preprocess_data._processed_has_actual_vwap(str(legacy_path))
    assert preprocess_data._processed_has_actual_vwap(str(current_path))
