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
        {"Date": ["2024-01-02", "2024-01-04"], "Close": [100, 110]}
    ).to_csv(closes, index=False)
    returns = kospi_index_returns(pd.to_datetime(["2024-01-03", "2024-01-04"]), str(closes))
    assert returns.tolist() == pytest.approx([0.0, 0.1])


def test_kospi_benchmark_requires_close_before_first_evaluation_date(tmp_path):
    closes = tmp_path / "kospi.csv"
    pd.DataFrame({"Date": ["2024-01-03"], "Close": [100]}).to_csv(closes, index=False)
    with pytest.raises(ValueError, match="before the first evaluation date"):
        kospi_index_returns(pd.to_datetime(["2024-01-03"]), str(closes))
