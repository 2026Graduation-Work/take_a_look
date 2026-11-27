"""Corporate-action events derived from immutable KRX raw bars.

RawBars: one stock, columns Date (normalized, unique, sorted), RawOpen, RawHigh, RawLow,
RawClose, RawChange, RawVolume, Amount, ListedShares. RawChange is KRX's CMPPREVDD_PRC, the
close minus the day's base price. Halt rows repeat the previous close with RawChange 0,
RawVolume 0 and 0 as RawOpen/High/Low.

A change in KRX base price relative to the previous close is a candidate event. The
confirmed events below distinguish share conversions from reference-price resets after a
halt. A reference reset records the raw KRX base price while preserving the market gap.

Events are sorted by ExDate. PriceFactor and VolumeFactor multiply bars before ExDate.
"""
import math
from collections.abc import Sequence
from datetime import date
from enum import StrEnum
from typing import NamedTuple

import numpy as np
import pandas as pd

SOURCE = "krx_base_price"
SHARE_TOLERANCE = 1e-3
EVENT_COLUMNS = ["Code", "ExDate", "PriceFactor", "VolumeFactor", "Kind", "Source",
                 "PrevClose", "BasePrice", "SharesBefore", "SharesAfter"]


class EventKind(StrEnum):
    SHARE_CHANGE = "share_change"
    PRICE_ONLY = "price_only"
    REFERENCE_RESET = "reference_reset"


class _ConfirmedEvent(NamedTuple):
    observed_close_base_shares: tuple[int, int, int, int]
    price_factor: float
    volume_factor: float
    kind: EventKind
    source: str


_CONFIRMED_EVENTS = {
    "004920": {
        pd.Timestamp("2020-03-20"): _ConfirmedEvent(
            (295, 636, 54_212_316, 18_070_772), 3, 1 / 3, EventKind.SHARE_CHANGE,
            "https://kind.krx.co.kr/external/2019/12/30/000788/20191230001882/11309.htm",
        ),
    },
    "003410": {
        pd.Timestamp("2020-12-04"): _ConfirmedEvent(
            (5550, 6080, 503_859_595, 503_859_595), 1, 1, EventKind.REFERENCE_RESET,
            "https://kind.krx.co.kr/external/2021/09/10/000502/20210910001141/10002.htm",
        ),
    },
}


def derive_events(code: str, raw: pd.DataFrame,
                  expected_dates: pd.DatetimeIndex | Sequence[date | str]) -> pd.DataFrame:
    """Resolve candidate events after checking all KRX sessions in the requested range.

    Supply expected_dates for the full range, including sessions when the stock was halted.
    """
    expected = pd.DatetimeIndex(expected_dates)
    if not expected.is_unique or not expected.is_monotonic_increasing:
        raise ValueError("Expected KRX trading dates must be unique and sorted")
    observed = pd.DatetimeIndex(raw.Date)
    if len(observed) != len(expected) or not (observed == expected).all():
        raise ValueError("Raw bar dates must match expected KRX trading dates in order")

    base = raw.RawClose - raw.RawChange
    if not (base > 0).all():
        raise ValueError("KRX base price must be positive")
    known_events = _CONFIRMED_EVENTS.get(code, {})
    moved = (base - raw.RawClose.shift()).abs().gt(0.5)
    previous_unavailable = raw.RawVolume.shift().eq(0) | raw[["RawOpen", "RawHigh", "RawLow"]].shift().eq(0).all(axis=1)
    changed_shares_after_pause = previous_unavailable & raw.ListedShares.ne(raw.ListedShares.shift())
    candidates = moved.to_numpy() | observed.isin(known_events) | changed_shares_after_pause.to_numpy()
    candidates[:1] = False

    rows = []
    for at in np.flatnonzero(candidates):
        ex_date = observed[at]
        previous = raw.iloc[at - 1]
        prev_close, base_price = previous.RawClose, base.iloc[at]
        shares_before, shares_after = previous.ListedShares, raw.ListedShares.iloc[at]
        confirmed = known_events.get(ex_date)
        price_factor = confirmed.price_factor if confirmed else base_price / prev_close
        source = SOURCE
        if confirmed:
            evidence = (prev_close, base_price, shares_before, shares_after)
            if evidence != confirmed.observed_close_base_shares:
                raise ValueError(f"{code} {ex_date:%Y-%m-%d}: KRX inputs disagree with confirmed event {confirmed.source}")
            volume_factor = confirmed.volume_factor
            kind, source = confirmed.kind, confirmed.source
        elif moved.iloc[at] and shares_before != shares_after and math.isclose(
                price_factor * shares_after / shares_before, 1.0, rel_tol=SHARE_TOLERANCE):
            kind, volume_factor = EventKind.SHARE_CHANGE, 1 / price_factor
        elif shares_before == shares_after and previous[["RawVolume", "RawOpen", "RawHigh", "RawLow"]].gt(0).all():
            kind, volume_factor = EventKind.PRICE_ONLY, 1.0
        else:
            raise ValueError(
                f"{code} {ex_date:%Y-%m-%d}: KRX base-price change requires evidence "
                "of the share conversion or reference-price reset"
            )
        rows.append({"Code": code, "ExDate": ex_date, "PriceFactor": price_factor,
                     "VolumeFactor": volume_factor, "Kind": kind.value, "Source": source,
                     "PrevClose": prev_close, "BasePrice": base_price,
                     "SharesBefore": shares_before, "SharesAfter": shares_after})
    events = pd.DataFrame(rows, columns=EVENT_COLUMNS)
    events["ExDate"] = pd.to_datetime(events.ExDate)
    return events


def apply_events(raw: pd.DataFrame, events: pd.DataFrame, as_of=None) -> pd.DataFrame:
    """Adjust raw bars by every event with Date < ExDate <= as_of (all events when as_of is None)."""
    active = events if as_of is None else events.loc[events.ExDate <= pd.Timestamp(as_of)]
    price = np.ones(len(raw))
    volume = np.ones(len(raw))
    for event in active.itertuples():
        before = (raw.Date < event.ExDate).to_numpy()
        price[before] *= event.PriceFactor
        volume[before] *= event.VolumeFactor
    adjusted = raw.copy()
    for column in ("Open", "High", "Low", "Close"):
        adjusted[column] = raw[f"Raw{column}"] * price
    adjusted["Volume"] = raw.RawVolume * volume
    adjusted["VWAP"] = raw.Amount / raw.RawVolume.where(raw.RawVolume > 0) * price
    adjusted["AdjustmentFactor"] = price
    return adjusted
