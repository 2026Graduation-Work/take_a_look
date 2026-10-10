import pandas as pd
from serving.supply import day_rows


def test_day_rows_merges_three_investors_for_master_stocks():
    data = {
        "개인": pd.DataFrame({"순매수거래량": [100, -5, 7]}, index=["005930", "000660", "999999"]),
        "외국인": pd.DataFrame({"순매수거래량": [-60, 3, 1]}, index=["005930", "000660", "999999"]),
        "기관합계": pd.DataFrame({"순매수거래량": [-40, 2, 0]}, index=["005930", "000660", "999999"]),
    }
    rows = day_rows(lambda day, investor: data[investor], "20261006", {"005930", "000660"})
    assert rows == [
        {"stock_code": "000660", "trade_date": "2026-10-06", "retail": -5, "foreign_investor": 3, "institution": 2},
        {"stock_code": "005930", "trade_date": "2026-10-06", "retail": 100, "foreign_investor": -60, "institution": -40},
    ]
