import json
from pathlib import Path

import pandas as pd
import pytest
from serving.barriers import observe, observe_many
from serving.cohorts import POLICY_ID, matching_cases
from serving.contracts import validate_snapshot


def test_contract_examples():
    examples = Path(__file__).parents[1] / "contracts/examples"
    for name in ("normal", "both", "no_cases", "unavailable"):
        validate_snapshot(json.loads((examples / f"{name}.json").read_text()))


def test_independent_barriers_and_incomplete_observations():
    dates = pd.date_range("2025-01-01", periods=6)
    frame = pd.DataFrame({"Date": dates, "Close": [100, 100, 95, 101, 100, 100],
                          "High": [100, 105, 96, 104, 101, 101],
                          "Trading_Halt": [0, 0, 0, 1, 0, 0]})
    result = observe(frame, 0, 5, 0.02)
    assert result["complete"] is False  # four traded sessions, even though both hit
    frame.loc[3, "Trading_Halt"] = 0
    result = observe(frame, 0, 5, 0.02)
    assert result["up_hit"] and result["down_hit"] and result["outcome_class"] == 2
    frame.loc[1, "Close"] = 96
    assert observe(frame, 0, 5, 0.02)["outcome_class"] == 0  # same-day tie: down
    frame.loc[1, "High"] = 101
    assert observe(frame, 0, 5, 0.02)["outcome_class"] == 0  # down, then up
    later = pd.DataFrame({"Date": pd.date_range("2025-02-01", periods=7),
                          "Close": [100] * 7, "High": [100] * 6 + [106],
                          "Trading_Halt": [0] * 7})
    assert observe(later, 0, 5, 0.02)["up_hit"] is False  # H+1 is excluded


def test_three_distances_are_and_conditions_and_zero_is_valid():
    rows = pd.DataFrame([
        ("005930", "2020-01-01", 5, POLICY_ID, .51, .31, .022, True, False, "2020-01-09", 1),
        ("005930", "2020-01-02", 5, POLICY_ID, .51, .32, .020, True, False, "2020-01-10", 1),
        ("005930", "2020-01-03", 5, POLICY_ID, .52, .30, .020, True, False, "2020-01-11", 1),
        ("005930", "2020-01-04", 20, POLICY_ID, .50, .30, .020, True, False, "2020-01-12", 1),
        ("000660", "2020-01-05", 5, POLICY_ID, .50, .30, .020, True, False, "2020-01-13", 1),
        ("005930", "2020-01-06", 5, POLICY_ID, .50, .30, .020, True, True, "2022-01-13", 1),
    ], columns=["Code", "Date", "horizon", "policy_id", "p_up", "p_down", "Sigma",
                "up_hit", "down_hit", "observed_through", "fold"])
    selected, summary = matching_cases(rows, code="005930", horizon=5, up=.50,
                                       down=.30, sigma=.020, as_of="2021-01-01")
    assert len(selected) == 1 and summary["sample_count"] == 1
    assert summary["up_rate"] == 1 and summary["neither_count"] == 0
    _, empty = matching_cases(rows, code="005930", horizon=5, up=.50,
                              down=.30, sigma=0, as_of="2021-01-01")
    assert empty["status"] == "no_cases" and empty["up_rate"] is None
    zero_row = rows.iloc[[0]].copy()
    zero_row["Sigma"] = 1e-16
    _, zero = matching_cases(zero_row, code="005930", horizon=5, up=.51,
                             down=.31, sigma=0, as_of="2021-01-01")
    assert zero["sample_count"] == 0
    with pytest.raises(ValueError):
        matching_cases(rows, code="005930", horizon=5, up=.5, down=.3,
                       sigma=-1, as_of="2021-01-01")


def test_vectorized_observation_matches_single_case_rule():
    frame = pd.DataFrame({"Date": pd.date_range("2025-01-01", periods=20),
                          "Close": [100, 102, 99, 95, 105] * 4,
                          "High": [101, 104, 100, 96, 107] * 4,
                          "Trading_Halt": [0, 0, 1, 0, 0] * 4,
                          "Sigma": [.02] * 20})
    all_rows = observe_many(frame, 5)
    for index in range(len(frame)):
        single = observe(frame, index, 5, .02)
        many = all_rows.iloc[index]
        for key in ("complete", "reason", "up_hit", "down_hit", "outcome_class"):
            assert many[key] == single[key]
