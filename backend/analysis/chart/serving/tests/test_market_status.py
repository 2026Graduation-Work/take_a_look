import pandas as pd
import pytest
from serving.internal.market import market_status_row, percentile_of_last


def _index(days, close):
    dates = pd.bdate_range(end=days, periods=320)
    values = [close + i for i in range(len(dates))]
    return pd.DataFrame({"종가": values, "거래대금": [1e12 + i for i in range(len(dates))]}, index=dates)


class FakeStock:
    def __init__(self, end):
        self.end = end

    def get_index_ohlcv_by_date(self, start, end, code, name_display=False):
        return _index(self.end, {"1001": 2500, "2001": 800, "1028": 340}[code])


def test_row_has_three_quotes_and_scores():
    row = market_status_row(FakeStock("2026-10-06"), "2026-10-06")
    assert [q["symbol"] for q in row["index_quotes"]] == ["KOSPI", "KOSDAQ", "KOSPI200"]
    assert row["index_quotes"][0]["change"] == 1.0
    assert row["volume_score"] == 100  # 거래대금이 매일 늘어나는 가짜 데이터라 최댓값
    assert 0 <= row["volatility_score"] <= 100 and row["condition"] in {"stable", "caution", "high_volatility"}


def test_missing_close_for_requested_day_fails():
    with pytest.raises(ValueError):
        market_status_row(FakeStock("2026-10-02"), "2026-10-06")


def test_percentile_counts_ties_half():
    assert percentile_of_last(pd.Series([1.0, 1.0, 1.0]), lookback=2) == 0.5
