from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from shared.data.actions import reconcile
from shared.data.events import apply_events, verify_events
from shared.tests.official_fixtures import fake_split
from shared.tests.test_official_actions import action_case

FIXTURES = Path(__file__).parent / "fixtures"
SPLIT_DAY = pd.Timestamp("2018-05-04")
HALT_DAYS = pd.to_datetime(["2018-04-30", "2018-05-02", "2018-05-03"])
PRICE_LIMIT = 0.30
ALL_FIXTURES = ["005930_2018", "031820_2026"]


def load(name):
    frame = pd.read_csv(FIXTURES / f"{name}.csv", comment="#", parse_dates=["Date"])
    return frame.drop(columns="NaverClose", errors="ignore")


@pytest.fixture(scope="module")
def samsung():
    return load("005930_2018")


def verified_actions(code, raw):
    security, decisions, notice, sessions, auctions = action_case(code)
    result, pending = reconcile(security, decisions, [notice], "2018-01-01", "2026-12-31", sessions, auctions)
    assert not pending
    return [action for action in result if raw.Date.min() <= pd.Timestamp(action.ex_date) <= raw.Date.max()]


def bars(closes, shares, factors=()):
    dates = pd.bdate_range("2024-01-02", periods=len(closes))
    close = pd.Series(closes, dtype=float)
    base = close.shift().fillna(close[0]) * pd.Series(dict(factors), index=close.index).fillna(1.0)
    return pd.DataFrame({"Date": dates, "RawOpen": close, "RawHigh": close, "RawLow": close,
                         "RawClose": close, "RawChange": close - base, "RawVolume": 1000.0,
                         "Amount": close * 1000, "ListedShares": shares})


def test_samsung_2018_has_one_fifty_for_one_split(samsung):
    events = verify_events("005930", samsung, pd.DatetimeIndex(samsung.Date), verified_actions("005930", samsung))

    assert len(events) == 1
    event = events.iloc[0]
    assert (event.ExDate, event.PrevClose, event.BasePrice) == (SPLIT_DAY, 2_650_000, 53_000)
    assert event.PriceFactor == pytest.approx(0.02, rel=1e-12)
    assert event.Kind == "split"
    assert event.SharesAfter / event.SharesBefore == 50


def test_samsung_adjusted_close_matches_independent_naver_close(samsung):
    naver = pd.read_csv(FIXTURES / "005930_2018.csv", comment="#").NaverClose
    adjusted = apply_events(samsung, verify_events("005930", samsung, pd.DatetimeIndex(samsung.Date), verified_actions("005930", samsung)))

    assert np.abs(adjusted.Close.to_numpy() - naver.to_numpy()).max() <= 1


def test_samsung_volume_scales_by_split_ratio_and_halts_stay_zero(samsung):
    events = verify_events("005930", samsung, pd.DatetimeIndex(samsung.Date), verified_actions("005930", samsung))
    adjusted = apply_events(samsung, events).set_index("Date")

    assert adjusted.Volume["2018-04-27"] == 606_216 * 50
    assert (adjusted.Volume[HALT_DAYS] == 0).all()
    assert adjusted.VWAP[HALT_DAYS].isna().all()


def test_samsung_as_of_before_split_leaves_prices_unadjusted(samsung):
    events = verify_events("005930", samsung, pd.DatetimeIndex(samsung.Date), verified_actions("005930", samsung))
    adjusted = apply_events(samsung, events, as_of="2018-05-03")

    assert (adjusted.AdjustmentFactor == 1).all()
    assert adjusted.Close.equals(samsung.RawClose.astype(float))
    assert adjusted.Volume.equals(samsung.RawVolume.astype(float))


def test_2026_ten_to_one_reverse_split_is_the_only_event():
    code, ex_date = "031820", "2026-05-06"
    raw = load(f"{code}_2026")
    events = verify_events(code, raw, pd.DatetimeIndex(raw.Date), verified_actions(code, raw))

    assert len(events) == 1
    event = events.iloc[0]
    assert (event.ExDate, event.Kind) == (pd.Timestamp(ex_date), "merge")
    assert (event.PriceFactor, event.VolumeFactor) == (10, 0.1)


def test_2026_unverified_reverse_split_candidate_requires_official_notice():
    raw = load("004920_2026")
    with pytest.raises(ValueError, match=r"004920 2026-10-02.*evidence"):
        verify_events("004920", raw, pd.DatetimeIndex(raw.Date), [])


@pytest.mark.parametrize("name", ALL_FIXTURES)
def test_standard_split_fixtures_match_exchange_returns(name):
    raw = load(name)
    adjusted = apply_events(raw, verify_events(name[:6], raw, pd.DatetimeIndex(raw.Date), verified_actions(name[:6], raw)))

    krx_rate = raw.RawChange / (raw.RawClose - raw.RawChange)
    returns = adjusted.Close.pct_change()
    np.testing.assert_allclose(returns[1:], krx_rate[1:], rtol=0, atol=1e-12)
    assert krx_rate.abs().max() <= PRICE_LIMIT
    assert raw.RawClose.pct_change().abs().max() > PRICE_LIMIT


def test_one_tick_reference_change_with_no_official_event_is_held():
    raw = bars([10_000, 9_990], 1_000_000, {1: 0.999})
    with pytest.raises(ValueError, match="requires official evidence"):
        verify_events("000006", raw, raw.Date, [])


def test_confirmed_split_uses_exact_exchange_terms_at_a_rounded_base():
    raw = bars([10_010, 5_000], [500_000, 1_000_000], {1: 5000 / 10010})
    action = fake_split(raw.Date.iloc[1].date(), 1, 2, (500_000, 1_000_000))
    events = verify_events("000006", raw, raw.Date, [action])
    assert events[["PriceFactor", "VolumeFactor"]].iloc[0].tolist() == [0.5, 2]
    assert apply_events(raw, events).Volume.tolist() == [2000, 1000]


def test_nonproportional_share_change_requires_documented_evidence():
    raw = bars([10_000, 9_700], [1_000_000, 1_200_000], {1: 0.97})

    with pytest.raises(ValueError, match=r"000006.*2024-01-03.*evidence"):
        verify_events("000006", raw, pd.DatetimeIndex(raw.Date), [])


def test_change_after_turnover_without_regular_hours_requires_documented_evidence():
    raw = bars([10_000, 9_700], 1_000_000, {1: 0.97})
    raw.loc[0, ["RawOpen", "RawHigh", "RawLow"]] = 0

    with pytest.raises(ValueError, match=r"000006.*2024-01-03.*evidence"):
        verify_events("000006", raw, pd.DatetimeIndex(raw.Date), [])


def test_two_verified_events_compose_multiplicatively():
    raw = bars([20_000, 20_000, 10_000, 10_000, 5000, 5000],
               [500_000, 500_000, 1_000_000, 1_000_000, 2_000_000, 2_000_000], {2: 0.5, 4: 0.5})
    actions = [fake_split(raw.Date.iloc[i].date(), 1, 2) for i in (2, 4)]
    events = verify_events("000003", raw, pd.DatetimeIndex(raw.Date), actions)
    assert events.Kind.tolist() == ["split", "split"]
    adjusted = apply_events(raw, events)
    assert adjusted.AdjustmentFactor.tolist() == pytest.approx([0.25, 0.25, 0.5, 0.5, 1, 1])
    assert adjusted.Volume.tolist() == pytest.approx([4000, 4000, 2000, 2000, 1000, 1000])
    assert adjusted.Close.tolist() == pytest.approx([5000] * 6)


def test_apply_events_leaves_raw_bars_untouched(samsung):
    snapshot = samsung.copy()

    apply_events(samsung, verify_events("005930", samsung, pd.DatetimeIndex(samsung.Date), verified_actions("005930", samsung)))

    pd.testing.assert_frame_equal(samsung, snapshot)


def test_derive_events_rejects_nonpositive_base_price():
    raw = bars([10_000, 10_100, 9_900], 1_000_000)
    raw.loc[2, "RawChange"] = 9_900

    with pytest.raises(ValueError):
        verify_events("000005", raw, pd.DatetimeIndex(raw.Date), [])


def test_derive_events_rejects_missing_samsung_trading_day(samsung):
    raw = samsung[samsung.Date != pd.Timestamp("2018-07-10")].reset_index(drop=True)

    with pytest.raises(ValueError):
        verify_events("005930", raw, pd.DatetimeIndex(samsung.Date), verified_actions("005930", samsung))


@pytest.mark.parametrize("positions", [
    pytest.param([1, 2], id="missing-first"),
    pytest.param([0, 1], id="missing-last"),
    pytest.param([0, 1, 1, 2], id="duplicate"),
    pytest.param([1, 0, 2], id="out-of-order"),
    pytest.param([0, 1, 3], id="unexpected"),
])
def test_derive_events_rejects_raw_dates_that_disagree_with_calendar(positions):
    raw = bars([10_000] * 4, 1_000_000)
    expected_dates = pd.DatetimeIndex(raw.Date.iloc[:3])

    with pytest.raises(ValueError):
        verify_events("000005", raw.iloc[positions], expected_dates, [])


@pytest.mark.parametrize("positions", [[0, 0, 1], [1, 0, 2]], ids=["duplicate", "out-of-order"])
def test_derive_events_rejects_invalid_calendar_even_if_raw_dates_match(positions):
    raw = bars([10_000] * 3, 1_000_000).iloc[positions]

    with pytest.raises(ValueError):
        verify_events("000005", raw, pd.DatetimeIndex(raw.Date), [])


def test_derive_events_accepts_krx_sessions_with_halts_and_nontrading_days(samsung):
    expected_dates = ["2018-04-27", "2018-04-30", "2018-05-02", "2018-05-03", "2018-05-04", "2018-05-08"]
    raw = samsung[samsung.Date.between(expected_dates[0], expected_dates[-1])].copy()
    raw.index *= 2

    events = verify_events("005930", raw, expected_dates, verified_actions("005930", raw))

    assert events.ExDate.tolist() == [SPLIT_DAY]
    assert events.PriceFactor.tolist() == [0.02]
