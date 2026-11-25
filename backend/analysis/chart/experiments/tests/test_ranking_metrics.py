import numpy as np
import pandas as pd
import pytest
from experiments.e0_baseline import attach_outcomes
from experiments.evaluation.metrics import (
    calculate_rank_ic,
    compare_daily_ic,
    daily_rank_ic,
    summarize_daily_ic,
    top_bottom_spread,
)


def _panel(days=60, stocks=30, seed=0):
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range("2024-01-02", periods=days)
    frame = pd.DataFrame([(d, f"{c:06d}") for d in dates for c in range(stocks)], columns=["Date", "Code"])
    frame["score"] = rng.normal(size=len(frame))
    frame["ret"] = 0.3 * frame.score + rng.normal(size=len(frame))
    return frame


def test_daily_ic_matches_existing_rank_ic_output():
    frame = _panel()
    daily = daily_rank_ic(frame, "score", "ret")
    summary = summarize_daily_ic(daily)
    legacy = calculate_rank_ic(frame, "score", "ret")
    assert summary["ic_mean"] == pytest.approx(legacy["ic_mean"])
    assert summary["icir"] == pytest.approx(summary["ic_mean"] / summary["ic_std"])
    assert summary["positive_day_ratio"] == pytest.approx(legacy["positive_day_ratio"])
    one_day = frame.loc[frame.Date.eq(frame.Date.iloc[0])]
    assert daily.iloc[0] == pytest.approx(one_day.score.corr(one_day.ret, method="spearman"))


def test_top_bottom_spread_uses_daily_deciles():
    dates = pd.bdate_range("2024-01-02", periods=2)
    frame = pd.DataFrame({"Date": np.repeat(dates, 20), "score": np.tile(np.arange(20), 2)})
    frame["ret"] = frame.score / 100
    result = top_bottom_spread(frame, "score", "ret", quantile=0.1)
    # top two (18, 19) minus bottom two (0, 1) each day
    assert result["spread_mean"] == pytest.approx((18.5 - 0.5) / 100)
    assert result["n_days"] == 2
    assert top_bottom_spread(frame.iloc[:5], "score", "ret")["n_days"] == 0


def test_block_bootstrap_detects_a_real_ic_gap_and_not_a_null_one():
    frame = _panel(days=250)
    good = daily_rank_ic(frame, "score", "ret")
    frame["noise"] = np.random.default_rng(1).normal(size=len(frame))
    useless = daily_rank_ic(frame, "noise", "ret")
    gap = compare_daily_ic(useless, good, n_boot=500, seed=3)
    assert gap["diff_mean"] > 0 and gap["ci_low"] > 0 and gap["t_stat"] > 3
    same = compare_daily_ic(good, good, n_boot=200)
    assert same["diff_mean"] == 0 and same["ci_low"] <= 0 <= same["ci_high"]
    assert gap["n_months"] == len(pd.DatetimeIndex(good.index).to_period("M").unique())
    with pytest.raises(ValueError):
        compare_daily_ic(good.iloc[:0], good)


def test_attach_outcomes_copies_returns_and_rejects_mismatched_rows():
    base = _panel(days=3, stocks=4).drop(columns="ret").assign(label_observed=True, fold_id=0, Trading_Halt=0,
                                           return_date=pd.Timestamp("2024-02-01"), forward_return=0.01,
                                           return_observed=True, horizon=5)
    raw = base[["Date", "Code", "score", "label_observed", "fold_id"]].sample(frac=1, random_state=0)
    attached = attach_outcomes(raw, base)
    assert list(attached.columns) == list(base.columns)
    assert attached.forward_return.eq(0.01).all()
    with pytest.raises(ValueError):
        attach_outcomes(raw.iloc[1:], base)
    with pytest.raises(ValueError):
        attach_outcomes(raw.assign(fold_id=1), base)
