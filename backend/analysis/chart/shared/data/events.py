"""Detect KRX observations and apply only officially verified share-unit changes."""

import numpy as np
import pandas as pd

from .actions import compatible_base

EVENT_COLUMNS = [
    "Code", "ExDate", "PriceFactor", "VolumeFactor", "Kind", "EventId", "Revision",
    "RatioEvidence", "DatesEvidence", "ImplementationEvidence", "AuctionEvidence",
    "PrevClose", "BasePrice", "SharesBefore", "SharesAfter",
]


def _observations(raw, expected_dates):
    expected = pd.DatetimeIndex(expected_dates)
    if not expected.is_unique or not expected.is_monotonic_increasing:
        raise ValueError("Expected KRX trading dates must be unique and sorted")
    observed = pd.DatetimeIndex(raw.Date)
    if not observed.equals(expected):
        raise ValueError("Raw bar dates must match expected KRX trading dates in order")
    base = raw.RawClose - raw.RawChange
    if not (base > 0).all():
        raise ValueError("KRX base price must be positive")

    moved = (base - raw.RawClose.shift()).abs().gt(0.5)
    paused = raw.RawVolume.shift().eq(0) | raw[["RawOpen", "RawHigh", "RawLow"]].shift().eq(0).all(axis=1)
    share_conversion_after_pause = paused & raw.ListedShares.ne(raw.ListedShares.shift())
    return observed, base, moved | share_conversion_after_pause


def verify_events(code, raw, expected_dates, actions):
    """Confirm official terms against KRX sessions and observations before use."""
    observed, base, candidates = _observations(raw, expected_dates)
    actions_by_date = {pd.Timestamp(action.ex_date): action for action in actions}
    if len(actions_by_date) != len(actions):
        raise ValueError(f"{code}: multiple verified actions on a KRX session")
    if missing := actions_by_date.keys() - set(observed):
        raise ValueError(f"{code}: official action date absent from KRX calendar: {sorted(missing)}")
    rows = []
    for at, day in enumerate(observed):
        if at == 0:
            continue
        action = actions_by_date.get(day)
        if action is None:
            if candidates.iloc[at]:
                raise ValueError(f"{code} {day:%Y-%m-%d}: KRX observation requires official evidence")
            continue
        previous, current = raw.iloc[at - 1], raw.iloc[at]
        current_base = base.iloc[at]
        shares = (previous.ListedShares, current.ListedShares)
        converted = float(previous.RawClose / action.factor)
        if action.kind in {"reduction", "reference_reset"}:
            auction = action.auction
            matches_base = (auction is not None and compatible_base(auction.evaluation, converted, action.ex_date, action.market)
                            and auction.low <= current_base <= auction.high and current.RawOpen == current_base)
        else:
            matches_base = compatible_base(current_base, converted, action.ex_date, action.market)
        if action.kind == "bonus":
            matches_base = matches_base and action.base == current_base and shares[0] == shares[1]
            if action.listing and pd.Timestamp(action.listing) in observed:
                listing_at = observed.get_loc(pd.Timestamp(action.listing))
                if listing_at <= at or observed[listing_at - 1] < day:
                    raise ValueError(f"{code} {day:%Y-%m-%d}: invalid official bonus listing sequence")
                before = raw.ListedShares.iloc[listing_at - 1]
                after = raw.ListedShares.iloc[listing_at]
                if before * action.factor != after:
                    raise ValueError(f"{code} {day:%Y-%m-%d}: bonus shares disagree at listing")
        if not matches_base or (action.shares is not None and shares != action.shares):
            raise ValueError(f"{code} {day:%Y-%m-%d}: KRX prices or shares disagree with official evidence")
        rows.append({
            "Code": code, "ExDate": day, "PriceFactor": float(1 / action.factor),
            "VolumeFactor": float(action.factor), "Kind": action.kind, "EventId": action.event_id,
            "Revision": action.revision, "RatioEvidence": action.ratio_evidence.source.sha256,
            "DatesEvidence": action.dates_evidence.source.sha256,
            "ImplementationEvidence": action.implementation_evidence.source.sha256,
            "AuctionEvidence": action.auction.evidence.source.sha256 if action.auction else None,
            "PrevClose": previous.RawClose, "BasePrice": current_base,
            "SharesBefore": shares[0], "SharesAfter": shares[1],
        })
    events = pd.DataFrame(rows, columns=EVENT_COLUMNS)
    events["ExDate"] = pd.to_datetime(events.ExDate)
    return events


def apply_events(raw: pd.DataFrame, events: pd.DataFrame, as_of=None) -> pd.DataFrame:
    """Adjust raw bars by every event with Date < ExDate <= as_of."""
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
