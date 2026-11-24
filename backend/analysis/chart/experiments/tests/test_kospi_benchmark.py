import json

import pandas as pd
import pytest
from experiments.backtest.engine import kospi_index_returns
from experiments.run_backtest import add_kospi_benchmark


def test_kospi_benchmark_uses_previous_close_and_updates_saved_results(tmp_path):
    dates = pd.to_datetime(["2024-01-03", "2024-01-04"])
    closes = tmp_path / "kospi.csv"
    pd.DataFrame(
        {"Date": ["2024-01-02", "2024-01-03", "2024-01-04"], "Close": [100, 110, 99]}
    ).to_csv(closes, index=False)
    pd.DataFrame({"Date": dates, "Portfolio": [0.01, 0.02]}).to_csv(
        tmp_path / "daily_returns.csv", index=False
    )
    pd.DataFrame([{
        "Strategy": "LGBM Model", "Total Return": "3.02%", "Sharpe Ratio": "1.0",
        "Max Drawdown": "-1.0%", "Win Rate": "N/A", "Benchmark Source": "",
    }]).to_csv(
        tmp_path / "benchmark_comparison.csv", index=False
    )
    pd.DataFrame([{"benchmark": "Custom KRX Composite Index", "source": "cached"}]).to_csv(
        tmp_path / "benchmark_metadata.csv", index=False
    )
    (tmp_path / "backtest_metrics_summary.json").write_text("{}", encoding="utf-8")

    config = {"evaluation": {"kospi_index_file": str(closes)}}
    add_kospi_benchmark(str(tmp_path), config)
    add_kospi_benchmark(str(tmp_path), config)

    daily = pd.read_csv(tmp_path / "daily_returns.csv")
    assert daily["Benchmark_KOSPI"].tolist() == pytest.approx([0.1, -0.1])
    comparison = pd.read_csv(tmp_path / "benchmark_comparison.csv")
    kospi_rows = comparison[comparison["Strategy"] == "KOSPI Index Buy & Hold"]
    assert len(kospi_rows) == 1
    assert kospi_rows.iloc[0]["Total Return"] == "-1.00%"
    summary = json.loads((tmp_path / "backtest_metrics_summary.json").read_text())
    assert summary["benchmark_kospi_total_return"] == pytest.approx(-0.01)


def test_kospi_benchmark_is_flat_when_index_market_is_closed(tmp_path):
    closes = tmp_path / "kospi.csv"
    pd.DataFrame(
        {"Date": ["2023-12-28", "2024-01-02"], "Close": [100, 110]}
    ).to_csv(closes, index=False)
    returns = kospi_index_returns(pd.to_datetime(["2024-01-01", "2024-01-02"]), str(closes))
    assert returns.tolist() == pytest.approx([0.0, 0.1])


def test_kospi_benchmark_requires_close_before_first_evaluation_date(tmp_path):
    closes = tmp_path / "kospi.csv"
    pd.DataFrame({"Date": ["2024-01-03"], "Close": [100]}).to_csv(closes, index=False)
    with pytest.raises(ValueError, match="before the first evaluation date"):
        kospi_index_returns(pd.to_datetime(["2024-01-03"]), str(closes))


def test_kospi_benchmark_fetches_krx_and_ignores_legacy_fdr_cache(tmp_path, monkeypatch):
    from experiments.backtest import engine
    from shared.data import metadata

    days = pd.to_datetime(["2024-01-03", "2024-01-04"])
    monkeypatch.setattr(engine, "_benchmark_cache_paths", lambda: (str(tmp_path / "daily.parquet"), str(tmp_path / "daily.json")))
    pd.DataFrame({"Date": pd.to_datetime(["2024-01-02", *days]), "Close": [1, 1, 1]}).to_parquet(tmp_path / "kospi_index_close.parquet")
    calls = []

    def fetch(symbol, start, end):
        calls.append(symbol)
        return pd.DataFrame({"Close": [100, 110, 99]}, index=pd.to_datetime(["2024-01-02", *days]))

    monkeypatch.setattr(metadata, "fetch_index_prices", fetch)
    result = kospi_index_returns(days)
    assert calls == ["1001"]
    assert result.tolist() == pytest.approx([0.1, -0.1])
    assert result.attrs["benchmark_source"] == "pykrx KOSPI 1001"
    assert (tmp_path / "kospi_krx_index_close.parquet").exists()
    kospi_index_returns(days)
    assert calls == ["1001"]


def test_kospi_benchmark_rejects_stale_cache_instead_of_flat_trading_day(tmp_path, monkeypatch):
    from experiments.backtest import engine

    monkeypatch.setattr(engine, "_benchmark_cache_paths", lambda: (str(tmp_path / "daily.parquet"), str(tmp_path / "daily.json")))
    pd.DataFrame({"Date": pd.to_datetime(["2024-01-02", "2024-01-03"]), "Close": [100, 101]}).to_parquet(tmp_path / "kospi_krx_index_close.parquet")
    with pytest.raises(ValueError, match="missing trading sessions"):
        kospi_index_returns(pd.to_datetime(["2024-01-03", "2024-01-04"]))


def test_kospi_benchmark_requires_the_immediately_preceding_trading_close(tmp_path, monkeypatch):
    from experiments.backtest import engine

    monkeypatch.setattr(engine, "_benchmark_cache_paths", lambda: (str(tmp_path / "daily.parquet"), str(tmp_path / "daily.json")))
    pd.DataFrame({"Date": pd.to_datetime(["2024-01-02", "2024-01-04"]), "Close": [100, 110]}).to_parquet(tmp_path / "kospi_krx_index_close.parquet")
    with pytest.raises(ValueError, match="missing trading sessions"):
        kospi_index_returns(pd.to_datetime(["2024-01-04"]))


def test_partial_krx_download_is_not_cached_and_can_retry(tmp_path, monkeypatch):
    from experiments.backtest import engine
    from shared.data import metadata

    monkeypatch.setattr(engine, "_benchmark_cache_paths", lambda: (str(tmp_path / "daily.parquet"), str(tmp_path / "daily.json")))
    dates = pd.to_datetime(["2024-01-02", "2024-01-03", "2024-01-04"])
    complete = pd.DataFrame({"Close": [100, 110, 99]}, index=dates)
    monkeypatch.setattr(metadata, "fetch_index_prices", lambda *_: complete.drop(index=dates[1]))
    with pytest.raises(ValueError, match="missing trading sessions"):
        kospi_index_returns(dates[1:])
    assert not (tmp_path / "kospi_krx_index_close.parquet").exists()
    monkeypatch.setattr(metadata, "fetch_index_prices", lambda *_: complete)
    assert kospi_index_returns(dates[1:]).tolist() == pytest.approx([0.1, -0.1])
