import pandas as pd
import pytest
from experiments.export.samples import build_samples
from serving.internal.distribution import SampleIndex


def test_historical_returns_follow_traded_rows(tmp_path):
    predictions = pd.DataFrame({"Date": pd.to_datetime(["2020-01-01", "2020-01-02"]),
                                "Code": ["005930", "005930"], "Prob": [.5, .5]})
    predictions.to_parquet(tmp_path / "predictions.parquet", index=False)
    processed = tmp_path / "processed"
    processed.mkdir()
    pd.DataFrame({"Date": pd.date_range("2020-01-01", periods=8),
                  "Close": [100, 100, 100, 100, 100, 110, 120, 130],
                  "Trading_Halt": [0, 1, 0, 0, 0, 0, 0, 0],
                  "Sigma": [.02] * 8}).to_parquet(processed / "005930.parquet", index=False)
    samples, report = build_samples(tmp_path / "predictions.parquet", processed, 5)
    assert len(samples) == 1
    assert samples.iloc[0].outcome_date == pd.Timestamp("2020-01-07")
    assert samples.iloc[0].return_pct == pytest.approx(20)
    assert report["excluded"]["base_halted"] == 1


def test_distribution_boundaries_and_small_samples():
    rows = pd.DataFrame({"code": ["a", "b", "c", "d"],
                         "prediction_date": pd.to_datetime(["2020-01-01"] * 4),
                         "outcome_date": pd.to_datetime(["2020-01-10", "2020-01-10", "2020-01-10", "2025-01-10"]),
                         "horizon": [5] * 4, "fold": [0] * 4,
                         "score": [.62, .64, .63, .63],
                         "sigma": [.019, .021, .020, .020],
                         "return_pct": [-10, 20, 5, 100]})
    index = SampleIndex(rows)
    result = index.distribution(horizon=5, score=.63, sigma=.020, as_of="2021-01-01")
    assert result["sample_count"] == 3
    assert result["stock_count"] == 3
    assert sum(bucket["count"] for bucket in result["histogram"]["bins"]) == 3
    assert result["histogram"]["central_68"]["low"] < 5
    assert index.distribution(horizon=5, score=.63, sigma=0, as_of="2021-01-01")["status"] == "no_cases"
    one = index.distribution(horizon=5, score=.62, sigma=.019, as_of="2021-01-01")
    assert one["sample_count"] == 1 and len(one["histogram"]["bins"]) == 1
