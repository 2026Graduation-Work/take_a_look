import numpy as np
import pandas as pd
import pytest
from experiments.e0_safety import (
    brier,
    calibration_curve,
    expected_calibration_error,
    grade_rise_rates,
    investable,
    isotonic_from_prior_years,
    top_excess,
)


def test_calibration_metrics_on_known_values():
    rng = np.random.default_rng(0)
    p = rng.uniform(0.2, 0.6, 20000)
    y = rng.uniform(size=p.size) < p
    assert expected_calibration_error(calibration_curve(y, p)) < 0.02
    assert expected_calibration_error(calibration_curve(y, p + 0.1)) == pytest.approx(0.1, abs=0.02)
    assert brier([1, 0], [0.75, 0.25]) == pytest.approx(0.0625)
    assert calibration_curve(y, p).n.sum() == p.size


def test_isotonic_uses_only_earlier_years():
    year = np.repeat([2019, 2020, 2021], 4)
    p = np.tile([0.1, 0.2, 0.3, 0.4], 3)
    y = np.array([0, 0, 1, 1, 1, 1, 1, 1, 0, 0, 0, 0], float)
    out = isotonic_from_prior_years(year, p, y)
    assert np.isnan(out[:4]).all()
    assert out[4:8].tolist() == [0, 0, 1, 1]  # 2020 fitted on 2019 only, its own all-1 labels unseen
    assert np.allclose(out[8:], [0.5, 0.5, 1, 1])  # 2021 pools 2019-2020


def test_grade_rise_rates_and_ci():
    dates = pd.bdate_range("2024-01-02", periods=50)
    frame = pd.DataFrame({"Date": np.repeat(dates, 2), "grade": np.tile(["up", "down"], 50),
                          "forward_return": np.tile([0.01, -0.01], 50)})
    rates = grade_rise_rates(frame, n_boot=200).set_index("grade")
    assert rates.loc["up", "rise_rate"] == 1 and rates.loc["down", "rise_rate"] == 0
    assert "neutral" not in rates.index
    assert rates.loc["up", "ci_low"] == rates.loc["up", "ci_high"] == 1


def test_top_excess_rebalances_without_overlap_and_charges_turnover():
    dates = pd.bdate_range("2024-01-02", periods=10)
    frame = pd.DataFrame({"Date": np.repeat(dates, 20), "Code": np.tile([f"{i:06d}" for i in range(20)], 10),
                          "score": np.tile(np.arange(20), 10), "forward_return": np.tile(np.arange(20) / 100, 10)})
    periods = top_excess(frame, "score", horizon=5)
    assert list(periods.Date) == [dates[0], dates[5]]
    assert periods.top_n.eq(2).all() and periods.turnover.tolist() == [1, 0]
    gross = 0.185 - 0.095
    assert periods.gross_excess.tolist() == pytest.approx([gross, gross])
    assert periods.net_excess.tolist() == pytest.approx([gross - 0.003, gross])


def test_investable_drops_preferred_spac_reit_and_illiquid():
    dates = pd.bdate_range("2024-01-02", periods=25)
    codes = ["000010", "000020", "000030", "000040", "000050", "000060", "000065", "000070"]
    names = pd.DataFrame({"Code": codes, "Name": ["가", "나", "다", "라", "하나스팩1호", "롯데리츠", "가우", "메리츠증권"]})
    prices = pd.DataFrame([(d, c, 1000, 10 * (i + 1)) for d in dates for i, c in enumerate(codes)],
                          columns=["Date", "Code", "Close", "Volume"])
    frame = pd.DataFrame([(d, c) for d in dates[-2:] for c in codes], columns=["Date", "Code"])
    kept = investable(frame, prices, names)
    # 보통주 5개 중 거래대금 하위 20%(1개)를 뺀다
    assert sorted(kept.Code.unique()) == ["000020", "000030", "000040", "000070"]
    assert len(kept) == 8
