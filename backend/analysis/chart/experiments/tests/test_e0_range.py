import numpy as np
import pandas as pd
import pytest
from experiments.e0_range import monthly_ranges, trailing_risk


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
