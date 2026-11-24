from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from shared.data.actions import reconcile
from shared.data.events import apply_events, verify_events
from shared.data.training_prices import adjust_training_window
from shared.features.builder import build_feature_frame
from shared.tests.test_official_actions import action_case, snapshot_for

FIXTURES = Path(__file__).parent / "fixtures"


def _load_raw(code):
    return pd.read_csv(FIXTURES / f"{code}_2020.csv", comment="#", parse_dates=["Date"])


def _verified(code, raw, days, as_of):
    security, decisions, notice, sessions, auctions = action_case(code)
    actions, pending = reconcile(security, decisions, [notice], "2020-01-01", "2020-12-31", sessions, auctions)
    assert not pending
    snapshot = snapshot_for(security, days, actions)
    return adjust_training_window(code, raw, days, as_of, snapshot, listing=security.listing)


def test_confirmed_reverse_split_scales_shares_and_preserves_resumption_gap():
    raw = _load_raw("004920")
    days = pd.DatetimeIndex(raw.Date)
    original = raw.copy()
    adjusted, events = _verified("004920", raw, days, days[-1])
    prices = adjusted.set_index("Date")
    event = events.iloc[0]
    assert len(events) == 1
    assert (event.ExDate, event.PrevClose, event.BasePrice) == (pd.Timestamp("2020-03-20"), 295, 636)
    assert (event.SharesBefore, event.SharesAfter) == (54_212_316, 18_070_772)
    assert event.Kind == "reduction"
    assert (event.PriceFactor, event.VolumeFactor) == (3, 1 / 3)
    assert event.ImplementationEvidence and event.AuctionEvidence
    assert prices.loc["2020-03-19", "Close"] == 885
    assert prices.loc["2020-03-20", "Close"] == 623
    assert prices.loc["2020-03-20", "Change"] == pytest.approx(-29.604519774)
    assert prices.loc["2020-03-20", "ExchangeChange"] == pytest.approx(-2.044025157)
    assert prices.loc["2020-02-28", "Volume"] == pytest.approx(762_370 / 3)
    assert prices.loc["2020-03-20", "Volume"] == 1_042_826
    assert pd.isna(prices.Change.iloc[0])
    before = apply_events(raw, events, as_of="2020-03-19")
    np.testing.assert_array_equal(before.Close, raw.RawClose)
    np.testing.assert_array_equal(before.Volume, raw.RawVolume)
    pd.testing.assert_frame_equal(raw, original)
    features = build_feature_frame(adjusted.assign(Code="004920"), days).set_index("Date")
    resumed = features.loc["2020-03-20"]
    assert resumed.Change == pytest.approx(-29.604519774)
    assert resumed.Log_Ret == pytest.approx(np.log(623 / 885))


def test_confirmed_reference_reset_keeps_historical_price_and_volume():
    raw = _load_raw("003410")
    days = pd.DatetimeIndex(raw.Date)
    adjusted, events = _verified("003410", raw, days, days[-1])
    prices = adjusted.set_index("Date")
    event = events.iloc[0]
    assert len(events) == 1
    assert (event.ExDate, event.PrevClose, event.BasePrice) == (pd.Timestamp("2020-12-04"), 5550, 6080)
    assert event.Kind == "reference_reset"
    assert (event.PriceFactor, event.VolumeFactor) == (1, 1)
    assert event.ImplementationEvidence and event.AuctionEvidence
    assert prices.loc["2020-12-03", "Close"] == 5550
    assert prices.loc["2020-12-04", "Close"] == 6700
    assert prices.loc["2020-12-04", "Change"] == pytest.approx(20.720720721)
    assert prices.loc["2020-12-04", "ExchangeChange"] == pytest.approx(10.197368421)
    np.testing.assert_array_equal(prices.Volume, raw.RawVolume)


def test_learning_return_preserves_a_gap_outside_the_exchange_price_limit():
    raw = _load_raw("004920").loc[lambda frame: frame.Date.between("2020-03-19", "2020-03-20")].copy()
    raw.loc[raw.Date.eq("2020-03-20"), ["RawLow", "RawClose", "RawChange"]] = [600, 600, -36]
    days = pd.DatetimeIndex(raw.Date)
    adjusted, _ = _verified("004920", raw, days, days[-1])
    assert adjusted.Change.iloc[1] == pytest.approx((600 / 885 - 1) * 100)
    assert adjusted.Change.iloc[1] < -30 < adjusted.ExchangeChange.iloc[1]


@pytest.mark.parametrize("fixture", ["004920", "003410"])
def test_unregistered_reference_change_after_halt_requires_evidence(fixture):
    raw = _load_raw(fixture)
    with pytest.raises(ValueError, match=r"123456.*2020-.*evidence"):
        verify_events("123456", raw, pd.DatetimeIndex(raw.Date), [])


@pytest.mark.parametrize("shares_after", [27_106_158, 54_212_315])
def test_unregistered_share_conversion_after_pause_is_not_hidden_by_unchanged_base(shares_after):
    raw = _load_raw("004920").loc[lambda frame: frame.Date.between("2020-03-19", "2020-03-20")].copy()
    resumed = raw.Date.eq("2020-03-20")
    raw.loc[resumed, ["RawOpen", "RawHigh", "RawLow", "RawClose", "RawChange"]] = [295, 305, 290, 300, 5]
    raw.loc[resumed, "ListedShares"] = shares_after
    with pytest.raises(ValueError, match=r"123456.*2020-03-20.*evidence"):
        verify_events("123456", raw, pd.DatetimeIndex(raw.Date), [])


def test_confirmed_event_requires_matching_base_even_without_a_detected_change():
    raw = _load_raw("004920")
    resumed = raw.Date.eq("2020-03-20")
    raw.loc[resumed, "RawChange"] = raw.loc[resumed, "RawClose"] - 295
    with pytest.raises(ValueError, match="004920.*2020-03-20"):
        _verified("004920", raw, pd.DatetimeIndex(raw.Date), raw.Date.iloc[-1])


def test_confirmed_event_at_window_start_has_no_previous_bar_to_adjust():
    raw = _load_raw("004920").loc[lambda frame: frame.Date.ge("2020-03-20")].copy()
    days = pd.DatetimeIndex(raw.Date)
    adjusted, events = _verified("004920", raw, days, days[-1])
    assert events.empty
    np.testing.assert_array_equal(adjusted.Close, raw.RawClose)
    assert pd.isna(adjusted.Change.iloc[0])
