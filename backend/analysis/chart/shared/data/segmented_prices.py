"""Apply official price factors inside a single verified training segment."""

import pandas as pd

from .events import apply_events
from .market_resolutions import adjustment_events
from .resolution_snapshot import SEGMENT_COLUMN, segment_id
from .training_prices import PRICE_SOURCE
from .validation import validate_krx_raw, validate_prices

ADJUSTMENT_COLUMNS = ["Code", "ExDate", "PriceFactor", "VolumeFactor", SEGMENT_COLUMN]


def adjust_training_window(security, raw, days, as_of, snapshot, *, source=None):
    days = pd.DatetimeIndex(days)
    cutoff = pd.Timestamp(as_of)
    if pd.isna(cutoff) or cutoff.tzinfo is not None:
        raise ValueError("Training prices require a valid as_of date")
    if days.empty or days[-1] > cutoff:
        raise ValueError("KRX raw price dates exceed the dataset as_of")
    raw = validate_krx_raw(raw, days)
    ledger = snapshot.window(security, raw, days, source=source)
    starts = snapshot.segment_starts(security)
    intervals = pd.DatetimeIndex(starts).searchsorted(raw.Date, side="right") - 1
    events = adjustment_events(ledger.resolutions)
    parts, applied = [], []
    excluded = snapshot.excluded_segment_ids(security)
    for index, bars in raw.groupby(intervals, sort=True):
        key = segment_id(security, starts[index])
        segment_events = events.loc[events.ExDate.between(bars.Date.iloc[0], bars.Date.iloc[-1])]
        if key in excluded:
            segment_events = segment_events.iloc[:0]
        prices = apply_events(bars, segment_events, as_of=cutoff)
        prices["SegmentId"] = key
        prices["Change"] = prices.Close.pct_change(fill_method=None) * 100
        parts.append(prices)
        applied.append(segment_events.assign(SegmentId=key))
    adjusted = pd.concat(parts, ignore_index=True)
    adjusted["ExchangeChange"] = 100 * raw.RawChange / (raw.RawClose - raw.RawChange)
    adjusted["PriceProvider"] = PRICE_SOURCE
    return validate_prices(adjusted, days, event_adjusted=True), pd.concat(applied, ignore_index=True)


def adjust_price_history(windows, raw, expected, as_of, snapshot, *, source=None):
    price_parts, event_parts = [], []
    for security, name in windows:
        days = snapshot.days(security).intersection(expected)
        bars = raw.loc[raw.Date.isin(days)].reset_index(drop=True)
        prices, events = adjust_training_window(security, bars, days, as_of, snapshot, source=source)
        price_parts.append(prices.assign(Code=security.code, Name=name, IsDelisted=security.delisting is not None))
        if not events.empty:
            event_parts.append(events)
    frame = validate_prices(pd.concat(price_parts, ignore_index=True), expected, event_adjusted=True)
    validate_segments(frame, required=True)
    return frame, event_parts


def validate_segments(frame, *, required=False):
    if SEGMENT_COLUMN not in frame:
        if required:
            raise ValueError("SegmentId is missing from segmented training data")
        return
    segment = frame[SEGMENT_COLUMN]
    if not segment.map(lambda value: isinstance(value, str) and bool(value)).all():
        raise ValueError("Invalid SegmentId in training data")
    columns = ["Code", SEGMENT_COLUMN] if "Code" in frame else [SEGMENT_COLUMN]
    order = ["Code", "Date"] if "Code" in frame else ["Date"]
    keys = frame.sort_values(order)[columns]
    changes = keys.ne(keys.shift()).any(axis=1)
    if keys.loc[changes].duplicated().any():
        raise ValueError("A training SegmentId reappears after another segment")


def request_history(security, start, end):
    from pykrx.website.krx.market.core import 개별종목시세

    from .training_prices import parse_krx_fields
    from .validation import KRX_RAW_COLUMNS

    rows = 개별종목시세().fetch(start.strftime("%Y%m%d"), end.strftime("%Y%m%d"), security.isin, 1)
    frame = parse_krx_fields(rows)
    frame["Date"] = pd.to_datetime(frame["TRD_DD"], format="%Y/%m/%d")
    return frame[KRX_RAW_COLUMNS]


def fetch_raw_window(security, sessions, *, source, progress):
    import time

    parts = []
    remaining = sessions
    while len(remaining):
        stop = remaining[0] + pd.DateOffset(years=2)
        days, remaining = remaining[remaining < stop], remaining[remaining >= stop]
        for attempt in range(1, 4):
            try:
                with source._krx_request_timeout():
                    raw = request_history(security, days[0], days[-1])
                parts.append(validate_krx_raw(raw, days))
                break
            except Exception as exc:
                progress({"state": "request_failed", "stage": "prices", "code": security.code,
                          "provider": PRICE_SOURCE, "attempt": attempt, "reason": str(exc),
                          "exception_type": type(exc).__name__, **getattr(exc, "details", {})})
                if attempt == 3:
                    raise
                time.sleep(attempt)
    return pd.concat(parts, ignore_index=True)
