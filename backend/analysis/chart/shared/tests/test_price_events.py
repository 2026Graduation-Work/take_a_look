from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from shared.data.events import EventKind, apply_events, derive_events

FIXTURE = Path(__file__).parent / "fixtures" / "005930_2018.csv"
SPLIT_DAY = pd.Timestamp("2018-05-04")
HALT_DAYS = pd.to_datetime(["2018-04-30", "2018-05-02", "2018-05-03"])
PRICE_LIMIT = 0.30


@pytest.fixture(scope="module")
def samsung():
    frame = pd.read_csv(FIXTURE, comment="#", parse_dates=["Date"])
    return frame.drop(columns="NaverClose"), frame.set_index("Date").NaverClose


def bars(closes, shares):
    dates = pd.bdate_range("2024-01-02", periods=len(closes))
    closes = np.asarray(closes, dtype=float)
    return pd.DataFrame({"Date": dates, "RawOpen": closes, "RawHigh": closes, "RawLow": closes,
                         "RawClose": closes, "RawVolume": 1000.0, "Amount": closes * 1000,
                         "ListedShares": shares})


def vendor(raw, factors):
    return pd.Series(raw.RawClose.to_numpy() * np.asarray(factors), index=raw.Date)


def test_samsung_2018_has_one_fifty_for_one_split(samsung):
    events = derive_events("005930", *samsung)

    assert len(events) == 1
    event = events.iloc[0]
    assert event.ExDate == SPLIT_DAY
    assert event.PriceFactor == pytest.approx(0.02, rel=1e-6)
    assert event.Kind == EventKind.SHARE_CHANGE
    assert event.SharesAfter / event.SharesBefore == 50


def test_samsung_adjusted_close_matches_naver(samsung):
    raw, naver = samsung
    adjusted = apply_events(raw, derive_events("005930", raw, naver))

    assert np.abs(adjusted.Close.to_numpy() - naver.to_numpy()).max() <= 1


def test_samsung_volume_scales_by_split_ratio_and_halts_stay_zero(samsung):
    raw, naver = samsung
    adjusted = apply_events(raw, derive_events("005930", raw, naver)).set_index("Date")

    assert adjusted.Volume["2018-04-27"] == 606_216 * 50
    assert (adjusted.Volume[HALT_DAYS] == 0).all()
    assert adjusted.VWAP[HALT_DAYS].isna().all()


def test_samsung_adjusted_returns_stay_inside_krx_price_limit(samsung):
    raw, naver = samsung
    adjusted = apply_events(raw, derive_events("005930", raw, naver)).set_index("Date")

    assert adjusted.Close.pct_change().abs().max() <= PRICE_LIMIT + 1e-3
    raw_returns = raw.set_index("Date").RawClose.pct_change()
    assert raw_returns[SPLIT_DAY] == pytest.approx(51_900 / 2_650_000 - 1)
    assert raw_returns.abs().max() > PRICE_LIMIT


def test_samsung_as_of_before_split_leaves_prices_unadjusted(samsung):
    raw, naver = samsung
    adjusted = apply_events(raw, derive_events("005930", raw, naver), as_of="2018-05-03")

    assert (adjusted.AdjustmentFactor == 1).all()
    assert adjusted.Close.equals(raw.RawClose.astype(float))
    assert adjusted.Volume.equals(raw.RawVolume.astype(float))


def test_dividend_is_price_only_and_keeps_volume():
    raw = bars([10_000, 10_100, 9_900, 9_950], 1_000_000)
    events = derive_events("000001", raw, vendor(raw, [0.98, 0.98, 1, 1]))

    assert len(events) == 1
    event = events.iloc[0]
    assert (event.ExDate, event.Kind) == (raw.Date[2], EventKind.PRICE_ONLY)
    assert event.PriceFactor == pytest.approx(0.98)
    assert event.VolumeFactor == 1.0
    adjusted = apply_events(raw, events)
    assert adjusted.Close.tolist() == pytest.approx([9_800, 9_898, 9_900, 9_950])
    assert adjusted.Volume.tolist() == [1000] * 4


def test_rights_offering_adds_shares_but_stays_price_only():
    raw = bars([10_000, 10_000, 9_700, 9_700], [1_000_000, 1_000_000, 1_200_000, 1_200_000])
    event = derive_events("000006", raw, vendor(raw, [0.97, 0.97, 1, 1])).iloc[0]

    assert (event.Kind, event.VolumeFactor) == (EventKind.PRICE_ONLY, 1.0)
    assert event.SharesAfter / event.SharesBefore == pytest.approx(1.2)


def test_ten_to_one_reverse_split_multiplies_price_and_divides_volume():
    raw = bars([1_000, 1_020, 10_100, 10_000], [1_000_000, 1_000_000, 100_000, 100_000])
    events = derive_events("000002", raw, vendor(raw, [10, 10, 1, 1]))

    assert len(events) == 1
    event = events.iloc[0]
    assert (event.Kind, event.PriceFactor, event.VolumeFactor) == (EventKind.SHARE_CHANGE, 10, 0.1)
    adjusted = apply_events(raw, events)
    assert adjusted.Close.tolist() == pytest.approx([10_000, 10_200, 10_100, 10_000])
    assert adjusted.Volume.tolist() == pytest.approx([100, 100, 1000, 1000])


def test_two_events_compose_multiplicatively():
    raw = bars([20_000, 20_000, 10_000, 10_000, 9_800, 9_800],
               [500_000, 500_000, 1_000_000, 1_000_000, 1_000_000, 1_000_000])
    events = derive_events("000003", raw, vendor(raw, [0.49, 0.49, 0.98, 0.98, 1, 1]))

    assert events.Kind.tolist() == [EventKind.SHARE_CHANGE, EventKind.PRICE_ONLY]
    adjusted = apply_events(raw, events)
    assert adjusted.AdjustmentFactor.tolist() == pytest.approx([0.49, 0.49, 0.98, 0.98, 1, 1])
    assert adjusted.Volume.tolist() == pytest.approx([2000, 2000, 1000, 1000, 1000, 1000])
    assert adjusted.Close.tolist() == pytest.approx([9_800, 9_800, 9_800, 9_800, 9_800, 9_800])


def test_events_round_trip_through_their_own_adjusted_close():
    raw = bars([31_150, 30_900, 15_600, 15_450, 15_300, 15_480, 15_520],
               [800_000, 800_000, 1_600_000, 1_600_000, 1_600_000, 1_600_000, 1_600_000])
    rounded = vendor(raw, [0.485, 0.485, 0.97, 0.97, 1, 1, 1]).round()
    events = derive_events("000004", raw, rounded)
    snapshot = raw.copy()

    adjusted = apply_events(raw, events)

    pd.testing.assert_frame_equal(raw, snapshot)
    pd.testing.assert_frame_equal(derive_events("000004", raw, adjusted.set_index("Date").Close), events)


@pytest.mark.parametrize("break_vendor", [
    lambda close: close.iloc[1:],
    lambda close: close.set_axis(pd.bdate_range("2025-01-02", periods=len(close))),
    lambda close: close.where(close.index != close.index[2], 0.0),
])
def test_derive_events_rejects_misaligned_or_nonpositive_vendor(break_vendor):
    raw = bars([10_000, 10_100, 9_900], 1_000_000)

    with pytest.raises(ValueError):
        derive_events("000005", raw, break_vendor(vendor(raw, [1, 1, 1])))
