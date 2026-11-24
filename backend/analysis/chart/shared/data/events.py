"""Corporate-action events derived from immutable KRX raw bars and a vendor adjusted close.

RawBars: one stock, columns Date (normalized, unique, sorted), RawOpen, RawHigh, RawLow,
RawClose, RawVolume, Amount, ListedShares. Halt rows keep RawVolume 0 and 0 as RawOpen/High/Low.

Events: one row per basis change, sorted by ExDate (the first trading day on the new basis).
PriceFactor multiplies every bar dated before ExDate; VolumeFactor is 1/PriceFactor for a
share-count change and 1.0 otherwise.

KRX's own adjusted series (adjStkPrc=2) leaves Samsung's 2018-05-04 50:1 split unadjusted,
so it is never an event source.
"""
import math
from enum import StrEnum

import numpy as np
import pandas as pd

SOURCE = "naver_close_ratio"
SHARE_TOLERANCE = 1e-3
EVENT_COLUMNS = ["Code", "ExDate", "PriceFactor", "VolumeFactor", "Kind", "Source",
                 "FactorBefore", "FactorAfter", "SharesBefore", "SharesAfter"]


class EventKind(StrEnum):
    SHARE_CHANGE = "share_change"
    PRICE_ONLY = "price_only"


def _classify(price_factor: float, shares_before: float, shares_after: float) -> EventKind:
    """A share-count change moves listed shares by exactly the inverse of the price factor."""
    if shares_before != shares_after and math.isclose(
            price_factor * shares_after / shares_before, 1.0, rel_tol=SHARE_TOLERANCE):
        return EventKind.SHARE_CHANGE
    return EventKind.PRICE_ONLY


def derive_events(code: str, raw: pd.DataFrame, vendor_close: pd.Series) -> pd.DataFrame:
    """Find where vendor_close / RawClose steps beyond integer rounding.

    vendor_close is indexed by date and must cover exactly the dates in raw.Date.
    """
    vendor = vendor_close.copy()
    vendor.index = pd.to_datetime(vendor.index).normalize()
    vendor = vendor.sort_index()
    if not vendor.index.equals(pd.DatetimeIndex(raw.Date)):
        raise ValueError("Vendor close dates differ from raw bar dates")
    if not (vendor > 0).all():
        raise ValueError("Vendor close must be positive")

    priced = (raw.RawClose > 0).to_numpy()
    bars = raw.loc[priced].reset_index(drop=True)
    close = pd.Series(vendor.to_numpy()[priced], dtype=float)
    factor = close / bars.RawClose.astype(float)
    tolerance = 0.5 / close + 0.5 / close.shift() + 1e-3
    starts = (factor / factor.shift() - 1).abs() > tolerance
    segment_factor = factor.groupby(starts.cumsum()).median()

    rows = []
    for segment, at in enumerate(starts[starts].index, start=1):
        before, after = segment_factor[segment - 1], segment_factor[segment]
        price_factor = before / after
        shares_before, shares_after = bars.ListedShares[at - 1], bars.ListedShares[at]
        kind = _classify(price_factor, shares_before, shares_after)
        rows.append({"Code": code, "ExDate": bars.Date[at], "PriceFactor": price_factor,
                     "VolumeFactor": 1 / price_factor if kind is EventKind.SHARE_CHANGE else 1.0,
                     "Kind": kind.value, "Source": SOURCE, "FactorBefore": before, "FactorAfter": after,
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
