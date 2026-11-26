import numpy as np
import pandas as pd
import pytest
from experiments.e0_range import grades, monthly_ranges, trailing_risk


def test_trailing_risk_uses_only_past_returns():
    dates = pd.bdate_range("2024-01-01", periods=70)
    close = np.r_[np.full(65, 100.0), [90, 90, 90, 90, 90]]
    risk = trailing_risk(pd.DataFrame({"Date": dates, "Code": "000010", "Close": close}))
    assert risk.vol.iloc[:60].isna().all()
    assert risk.semi.iloc[64] == 0 and risk.vol.iloc[64] == 0  # drop on day 65 not seen yet
    assert risk.semi.iloc[65] == pytest.approx(np.sqrt(0.1 ** 2 / 60))


def test_monthly_ranges_use_only_returns_realized_before_the_month():
    rng = np.random.default_rng(0)
    jan = pd.DataFrame({"Date": pd.Timestamp("2024-01-02"), "return_date": pd.Timestamp("2024-01-20"),
                        "forward_return": rng.normal(size=1000)})
    late = jan.assign(return_date=pd.Timestamp("2024-02-05"), forward_return=100.0)  # not known on 2/1
    feb = pd.DataFrame({"Date": pd.Timestamp("2024-02-01"), "return_date": pd.Timestamp("2024-02-10"),
                        "forward_return": [-5.0, 0.0, 5.0]})
    frame = pd.concat([jan, late, feb]).assign(grade="up", vol_q=1).reset_index(drop=True)
    ranged = monthly_ranges(frame, min_cell=200)
    assert ranged.Date.eq(pd.Timestamp("2024-02-01")).all()  # January has no history
    assert ranged.q90.iloc[0] == pytest.approx(np.quantile(jan.forward_return, 0.9))
    assert ranged.inside.tolist() == [False, True, False] and ranged.below.tolist() == [True, False, False]
    assert monthly_ranges(frame, min_cell=2000).empty  # too few past rows: no range rather than a noisy one


def test_lookback_window_drops_returns_older_than_36_months():
    old = pd.DataFrame({"Date": pd.Timestamp("2019-01-02"), "return_date": pd.Timestamp("2019-01-20"),
                        "forward_return": np.full(300, -1.0)})
    recent = old.assign(Date=pd.Timestamp("2022-06-01"), return_date=pd.Timestamp("2022-06-20"),
                        forward_return=np.linspace(0, 1, 300))
    target = pd.DataFrame({"Date": [pd.Timestamp("2022-07-01")], "return_date": [pd.Timestamp("2022-07-20")],
                           "forward_return": [0.5]})
    frame = pd.concat([old, recent, target]).assign(grade="up", vol_q=1).reset_index(drop=True)
    july = monthly_ranges(frame).loc[lambda f: f.Date.eq(pd.Timestamp("2022-07-01"))]
    assert july.q10.iloc[0] == pytest.approx(0.1)  # the 2019 -1.0 rows are outside the window
    assert monthly_ranges(frame, lookback_months=60).loc[lambda f: f.Date.eq(pd.Timestamp("2022-07-01"))].q10.iloc[0] < 0


def test_g1_splits_each_day_into_top_and_bottom_fifths():
    frame = pd.DataFrame({"Date": np.repeat(pd.bdate_range("2024-01-02", periods=2), 10),
                          "prob_up": np.tile(np.arange(10) / 10, 2)})
    g1 = grades(frame, "G1")
    assert (g1[:10] == ["down"] * 2 + ["neutral"] * 6 + ["up"] * 2).all()
