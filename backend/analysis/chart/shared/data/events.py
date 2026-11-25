"""Corporate-action events derived from immutable KRX raw bars.

RawBars: one stock, columns Date (normalized, unique, sorted), RawOpen, RawHigh, RawLow,
RawClose, RawChange, RawVolume, Amount, ListedShares. RawChange is KRX's CMPPREVDD_PRC, the
close minus the day's base price. Halt rows repeat the previous close with RawChange 0,
RawVolume 0 and 0 as RawOpen/High/Low.

KRX sets each day's base price, the reference for its change rate and the ±30% price limit, to
the previous close unless a corporate action resets it. A base price that differs from the
previous close is therefore an event, and base / previous close is its exact price factor.

Events: one row per basis change, sorted by ExDate (the first trading day on the new basis).
PriceFactor multiplies every bar dated before ExDate; VolumeFactor is 1/PriceFactor for a
share-count change and 1.0 otherwise.
"""
import math
from collections.abc import Sequence
from datetime import date
from enum import StrEnum

import numpy as np
import pandas as pd

SOURCE = "krx_base_price"
SHARE_TOLERANCE = 1e-3
EVENT_COLUMNS = ["Code", "ExDate", "PriceFactor", "VolumeFactor", "Kind", "Source",
                 "PrevClose", "BasePrice", "SharesBefore", "SharesAfter"]


class EventKind(StrEnum):
    SHARE_CHANGE = "share_change"
    PRICE_ONLY = "price_only"


def _classify(price_factor: float, shares_before: float, shares_after: float) -> EventKind:
    if shares_before != shares_after and math.isclose(
            price_factor * shares_after / shares_before, 1.0, rel_tol=SHARE_TOLERANCE):
        return EventKind.SHARE_CHANGE
    return EventKind.PRICE_ONLY


def derive_events(code: str, raw: pd.DataFrame,
                  expected_dates: pd.DatetimeIndex | Sequence[date | str]) -> pd.DataFrame:
    """Record base-price changes after checking all KRX sessions in the requested range.

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
    prev = raw.RawClose.shift()
    moved = (base - prev).abs() > 0.5

    rows = []
    for at in np.flatnonzero(moved):
        prev_close, base_price = prev.iloc[at], base.iloc[at]
        price_factor = base_price / prev_close
        shares_before, shares_after = raw.ListedShares.iloc[at - 1], raw.ListedShares.iloc[at]
        kind = _classify(price_factor, shares_before, shares_after)
        rows.append({"Code": code, "ExDate": observed[at], "PriceFactor": price_factor,
                     "VolumeFactor": 1 / price_factor if kind is EventKind.SHARE_CHANGE else 1.0,
                     "Kind": kind.value, "Source": SOURCE, "PrevClose": prev_close, "BasePrice": base_price,
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
