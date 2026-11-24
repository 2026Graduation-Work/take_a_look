from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from shared.data.events import EventKind, apply_events, derive_events

FIXTURES = Path(__file__).parent / "fixtures"
SPLIT_DAY = pd.Timestamp("2018-05-04")
HALT_DAYS = pd.to_datetime(["2018-04-30", "2018-05-02", "2018-05-03"])
PRICE_LIMIT = 0.30
REVERSE_SPLITS = [("004920", "2026-10-02"), ("031820", "2026-05-06")]
ALL_FIXTURES = ["005930_2018", "004920_2026", "031820_2026"]


def load(name):
    frame = pd.read_csv(FIXTURES / f"{name}.csv", comment="#", parse_dates=["Date"])
    return frame.drop(columns="NaverClose", errors="ignore")


@pytest.fixture(scope="module")
def samsung():
    return load("005930_2018")


def bars(closes, shares, factors=()):
    """Synthetic KRX bars whose base price is prev close × factor on each {index: factor} day."""
    dates = pd.bdate_range("2024-01-02", periods=len(closes))
    close = pd.Series(closes, dtype=float)
    base = close.shift().fillna(close[0]) * pd.Series(dict(factors), index=close.index).fillna(1.0)
    return pd.DataFrame({"Date": dates, "RawOpen": close, "RawHigh": close, "RawLow": close,
                         "RawClose": close, "RawChange": close - base, "RawVolume": 1000.0,
                         "Amount": close * 1000, "ListedShares": shares})


def test_samsung_2018_has_one_fifty_for_one_split(samsung):
    events = derive_events("005930", samsung)

    assert len(events) == 1
    event = events.iloc[0]
    assert (event.ExDate, event.PrevClose, event.BasePrice) == (SPLIT_DAY, 2_650_000, 53_000)
    assert event.PriceFactor == pytest.approx(0.02, rel=1e-12)
    assert event.Kind == EventKind.SHARE_CHANGE
    assert event.SharesAfter / event.SharesBefore == 50


def test_samsung_adjusted_close_matches_independent_naver_close(samsung):
    naver = pd.read_csv(FIXTURES / "005930_2018.csv", comment="#").NaverClose
    adjusted = apply_events(samsung, derive_events("005930", samsung))

    assert np.abs(adjusted.Close.to_numpy() - naver.to_numpy()).max() <= 1


def test_samsung_volume_scales_by_split_ratio_and_halts_stay_zero(samsung):
    adjusted = apply_events(samsung, derive_events("005930", samsung)).set_index("Date")

    assert adjusted.Volume["2018-04-27"] == 606_216 * 50
    assert (adjusted.Volume[HALT_DAYS] == 0).all()
    assert adjusted.VWAP[HALT_DAYS].isna().all()


def test_samsung_as_of_before_split_leaves_prices_unadjusted(samsung):
    adjusted = apply_events(samsung, derive_events("005930", samsung), as_of="2018-05-03")

    assert (adjusted.AdjustmentFactor == 1).all()
    assert adjusted.Close.equals(samsung.RawClose.astype(float))
    assert adjusted.Volume.equals(samsung.RawVolume.astype(float))


@pytest.mark.parametrize(("code", "ex_date"), REVERSE_SPLITS)
def test_2026_ten_to_one_reverse_split_is_the_only_event(code, ex_date):
    events = derive_events(code, load(f"{code}_2026"))

    assert len(events) == 1
    event = events.iloc[0]
    assert (event.ExDate, event.Kind) == (pd.Timestamp(ex_date), EventKind.SHARE_CHANGE)
    assert (event.PriceFactor, event.VolumeFactor) == (10, 0.1)


@pytest.mark.parametrize("name", ALL_FIXTURES)
def test_adjusted_returns_are_krx_change_rates_inside_the_price_limit(name):
    raw = load(name)
    adjusted = apply_events(raw, derive_events(name[:6], raw))

    krx_rate = raw.RawChange / (raw.RawClose - raw.RawChange)
    returns = adjusted.Close.pct_change()
    np.testing.assert_allclose(returns[1:], krx_rate[1:], rtol=0, atol=1e-12)
    assert returns.abs().max() <= PRICE_LIMIT
    assert raw.RawClose.pct_change().abs().max() > PRICE_LIMIT


def test_price_only_event_keeps_volume_when_shares_do_not_match():
    raw = bars([10_000, 10_000, 9_700, 9_700], [1_000_000, 1_000_000, 1_200_000, 1_200_000], {2: 0.97})
    events = derive_events("000006", raw)

    event = events.iloc[0]
    assert (event.Kind, event.PriceFactor, event.VolumeFactor) == (EventKind.PRICE_ONLY, 0.97, 1.0)
    adjusted = apply_events(raw, events)
    assert adjusted.Close.tolist() == pytest.approx([9_700, 9_700, 9_700, 9_700])
    assert adjusted.Volume.tolist() == [1000] * 4


def test_two_events_compose_multiplicatively():
    raw = bars([20_000, 20_000, 10_000, 10_000, 9_800, 9_800],
               [500_000, 500_000, 1_000_000, 1_000_000, 1_000_000, 1_000_000], {2: 0.5, 4: 0.98})
    events = derive_events("000003", raw)

    assert events.Kind.tolist() == [EventKind.SHARE_CHANGE, EventKind.PRICE_ONLY]
    adjusted = apply_events(raw, events)
    assert adjusted.AdjustmentFactor.tolist() == pytest.approx([0.49, 0.49, 0.98, 0.98, 1, 1])
    assert adjusted.Volume.tolist() == pytest.approx([2000, 2000, 1000, 1000, 1000, 1000])
    assert adjusted.Close.tolist() == pytest.approx([9_800] * 6)


def test_apply_events_leaves_raw_bars_untouched(samsung):
    snapshot = samsung.copy()

    apply_events(samsung, derive_events("005930", samsung))

    pd.testing.assert_frame_equal(samsung, snapshot)


def test_derive_events_rejects_nonpositive_base_price():
    raw = bars([10_000, 10_100, 9_900], 1_000_000)
    raw.loc[2, "RawChange"] = 9_900

    with pytest.raises(ValueError):
        derive_events("000005", raw)
