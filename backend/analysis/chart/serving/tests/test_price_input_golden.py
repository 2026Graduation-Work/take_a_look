"""KRX responses -> adjusted OHLC, VWAP and adjustment factor, checked against fixed expectations (#522)."""
import pandas as pd
import pytest
from serving.internal import prices as serving_prices
from serving.tests.price_input_golden import compare, load_cases, run

CASES = load_cases()


@pytest.mark.parametrize("case", CASES, ids=[case["name"] for case in CASES])
def test_price_inputs_match_expected(case, tmp_path):
    compare(case["name"], case["expected"], run(case, tmp_path))


def test_cases_cover_factor_change_and_missing_regular_session():
    rows = {case["kind"]: pd.DataFrame(case["expected"]["rows"]) for case in CASES}
    split = rows["factor_change"]
    assert split.AdjustmentFactor.nunique() == 2 and split.Trading_Halt.eq(1).any()
    unavailable = rows["regular_session_unavailable"]
    assert (unavailable.RegularSessionUnavailable & unavailable.Volume.gt(0)).any()
    assert unavailable.VWAPOutsideDailyRange.any()


def test_fixed_responses_distinguish_raw_price_fields():
    case = next(case for case in CASES if case["kind"] == "regular_session_unavailable")
    columns = ["시가", "고가", "저가", "거래량", "거래대금"]
    raw, adjusted = case["raw"], case["adjusted"]
    regular = raw["시가"].gt(0)
    assert raw.loc[regular, columns].ne(adjusted.loc[regular, columns]).any(axis=0).all()


def test_vwap_regression_names_case_date_and_column(tmp_path, monkeypatch):
    case = next(case for case in CASES if case["kind"] == "factor_change")
    attach_actual_vwap = serving_prices.attach_actual_vwap

    def omit_adjustment_factor(adjusted, raw):
        prices = attach_actual_vwap(adjusted, raw)
        return prices.assign(VWAP=prices.Amount / prices.RawVolume)

    monkeypatch.setattr(serving_prices, "attach_actual_vwap", omit_adjustment_factor)
    with pytest.raises(AssertionError, match=r"split_with_halt:.*2018-04-02 VWAP"):
        compare(case["name"], case["expected"], run(case, tmp_path))
