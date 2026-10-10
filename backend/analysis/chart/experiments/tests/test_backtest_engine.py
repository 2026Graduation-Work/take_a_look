import json

import pandas as pd
from experiments.backtest import engine


def _series(values: list[float | bool], dates: pd.DatetimeIndex) -> pd.Series:
    return pd.Series(values, index=dates)


def test_rule_exits_use_open_price_for_stop_and_profit_gaps() -> None:
    dates = pd.date_range("2024-01-02", periods=2, freq="B")
    entries = _series([True, False], dates)
    common = {
        "entry_series": entries,
        "close_series": _series([100.0, 100.0], dates),
        "sigma_series": _series([0.1, 0.1], dates),
        "halt_series": _series([False, False], dates),
        "holding_days": 5,
        "down_mult": 1.0,
        "hard_sl_mult": 1.0,
    }

    stop_exits, stop_prices = engine.calculate_rule_exits(
        **common,
        open_series=_series([100.0, 85.0], dates),
        high_series=_series([100.0, 90.0], dates),
        low_series=_series([100.0, 80.0], dates),
        up_mult=1.0,
    )
    assert stop_exits.iloc[1]
    assert stop_prices.iloc[1] == 85.0

    profit_exits, profit_prices = engine.calculate_rule_exits(
        **common,
        open_series=_series([100.0, 115.0], dates),
        high_series=_series([100.0, 120.0], dates),
        low_series=_series([100.0, 114.0], dates),
        up_mult=1.0,
    )
    assert profit_exits.iloc[1]
    assert profit_prices.iloc[1] == 115.0


def test_legacy_soft_exit_wrapper_disables_hard_profit_exit() -> None:
    dates = pd.date_range("2024-01-02", periods=2, freq="B")
    exits = engine.calculate_soft_exits(
        _series([True, False], dates),
        _series([100.0, 120.0], dates),
        _series([100.0, 120.0], dates),
        _series([0.1, 0.1], dates),
        _series([False, False], dates),
        holding_days=5,
        down_mult=1.0,
    )
    assert not exits.iloc[1]


def test_cached_benchmark_requires_full_requested_date_coverage(tmp_path, monkeypatch) -> None:
    daily_path = tmp_path / "benchmark.parquet"
    metadata_path = tmp_path / "benchmark.json"
    monkeypatch.setattr(engine, "_benchmark_cache_paths", lambda: (str(daily_path), str(metadata_path)))

    dates = pd.date_range("2024-01-02", periods=2, freq="B")
    pd.DataFrame({"Date": [dates[0]], "Return": [0.01]}).to_parquet(daily_path, index=False)
    metadata_path.write_text(
        json.dumps({"weights_version": engine.BENCHMARK_WEIGHTS_VERSION}), encoding="utf-8"
    )
    assert engine._load_cached_benchmark(dates) is None

    pd.DataFrame({"Date": dates, "Return": [0.01, -0.02]}).to_parquet(daily_path, index=False)
    cached = engine._load_cached_benchmark(dates)
    assert cached is not None
    assert cached.tolist() == [0.01, -0.02]


def test_backtest_does_not_fill_pre_listing_prices_from_the_future(monkeypatch) -> None:
    dates = pd.date_range("2024-01-02", periods=2, freq="B")
    entries = pd.DataFrame({"000001": [True, False]}, index=dates)
    weights = pd.DataFrame({"000001": [1.0, 0.0]}, index=dates)
    price_df = pd.DataFrame(
        {
            "Date": [dates[1]],
            "Code": ["000001"],
            "Open": [100.0],
            "High": [101.0],
            "Low": [99.0],
            "Close": [100.0],
            "Trading_Halt": [0],
            "Sigma": [0.01],
        }
    )
    captured = {}

    def capture_exits(**kwargs):
        captured["entries"] = kwargs["entry_series"].copy()
        return pd.Series(False, index=dates), pd.Series(float("nan"), index=dates)

    class FakePortfolio:
        @staticmethod
        def from_signals(**kwargs):
            return object()

    monkeypatch.setattr(engine, "calculate_rule_exits", capture_exits)
    monkeypatch.setattr(engine.vbt, "Portfolio", FakePortfolio)

    result = engine.VectorBTEngine({}).run(entries, weights, price_df, generate_report=False)
    assert result is not None
    assert not captured["entries"].iloc[0]


def test_backtest_uses_max_holding_days_instead_of_label_horizon(monkeypatch) -> None:
    dates = pd.date_range("2024-01-02", periods=2, freq="B")
    entries = pd.DataFrame({"000001": [True, False]}, index=dates)
    weights = pd.DataFrame({"000001": [1.0, 0.0]}, index=dates)
    price_df = pd.DataFrame(
        {
            "Date": dates,
            "Code": ["000001", "000001"],
            "Open": [100.0, 101.0],
            "High": [101.0, 102.0],
            "Low": [99.0, 100.0],
            "Close": [100.0, 101.0],
            "Trading_Halt": [0, 0],
            "Sigma": [0.01, 0.01],
        }
    )
    captured = {}

    def capture_exits(**kwargs):
        captured["holding_days"] = kwargs["holding_days"]
        return pd.Series(False, index=dates), pd.Series(float("nan"), index=dates)

    class FakePortfolio:
        @staticmethod
        def from_signals(**kwargs):
            return object()

    monkeypatch.setattr(engine, "calculate_rule_exits", capture_exits)
    monkeypatch.setattr(engine.vbt, "Portfolio", FakePortfolio)

    engine.VectorBTEngine(
        {"labels": {"horizon": 5}, "backtest": {"max_holding_days": 10}}
    ).run(entries, weights, price_df, generate_report=False)
    assert captured["holding_days"] == 10
