"""Strict source, session and flow validation, with no inferred missing rows."""
import numpy as np
import pandas as pd

from shared.settings import PRICE_BASIS


def validate_index(frame, start, end):
    if frame is None or frame.empty:
        raise ValueError("Empty index response")
    frame = frame.rename(columns={"종가": "Close"}).copy()
    frame.index = pd.to_datetime(frame.index).normalize()
    frame = frame.loc[(frame.index >= start) & (frame.index <= end)]
    if frame.index.has_duplicates or frame.empty or "Close" not in frame:
        raise ValueError("Invalid index dates/columns")
    values = pd.to_numeric(frame.Close, errors="coerce")
    if not np.isfinite(values).all() or values.le(0).any():
        raise ValueError("Invalid index prices")
    return values.sort_index()

def expected_sessions(intervals, calendar):
    days = pd.DatetimeIndex(pd.to_datetime(calendar["trading_days"]))
    expected = pd.DatetimeIndex([])
    for row in intervals.itertuples():
        active = days >= row.ListingDate
        if pd.notna(row.DelistingDate):
            active &= days < row.DelistingDate
        expected = expected.union(days[active])
    return expected.sort_values()

def validate_prices(frame, expected):
    if "Date" not in frame:
        raise ValueError("Missing Date")
    frame = frame.copy()
    frame["Date"] = pd.to_datetime(frame.Date).dt.normalize()
    if frame.Date.duplicated().any() or not pd.DatetimeIndex(frame.Date).sort_values().equals(
        expected
    ):
        missing = expected.difference(pd.DatetimeIndex(frame.Date))
        raise ValueError(f"Price coverage mismatch; missing {missing[:5].tolist()}")
    required = [
        "Open",
        "High",
        "Low",
        "Close",
        "Volume",
        "Amount",
        "RawVolume",
        "RawClose",
        "RawOpen", "RawHigh", "RawLow",
        "AdjustmentFactor",
        "VWAP",
    ]
    if set(required) - set(frame):
        raise ValueError("Missing OHLC/VWAP source fields")
    frame[required] = frame[required].apply(pd.to_numeric, errors="coerce")
    if (
        not np.isfinite(frame[["Volume", "RawVolume", "Amount"]].to_numpy()).all()
        or frame[["Volume", "RawVolume", "Amount"]].lt(0).any().any()
    ):
        raise ValueError("Invalid volume/amount")
    traded = frame.Volume.gt(0)
    if not np.array_equal(frame.Volume.to_numpy(), frame.RawVolume.to_numpy()):
        raise ValueError("Volume disagrees with KRX RawVolume")
    unavailable = frame[["RawOpen", "RawHigh", "RawLow"]].eq(0).all(axis=1)
    regular = traded & ~unavailable
    turnover_fields = ["Close", "RawClose", "Volume", "RawVolume", "Amount", "AdjustmentFactor", "VWAP"]
    values = frame.loc[traded, turnover_fields].to_numpy(dtype=float)
    if not np.isfinite(values).all() or (values <= 0).any():
        raise ValueError("Non-positive/non-finite traded prices or VWAP source")
    values = frame.loc[regular, required].to_numpy(dtype=float)
    if not np.isfinite(values).all() or (values <= 0).any():
        raise ValueError("Non-positive/non-finite regular-session OHLC")
    row = frame.loc[regular]
    if (
        (row.Low > row[["Open", "Close"]].min(axis=1)).any()
        or (row.High < row[["Open", "Close"]].max(axis=1)).any()
        or (row.Low > row.High).any()
    ):
        raise ValueError("OHLC relationship invalid")
    row = frame.loc[traded]
    calculated = row.Amount / row.RawVolume * row.AdjustmentFactor
    if not np.allclose(row.VWAP, calculated, rtol=1e-8) or not np.allclose(
        row.AdjustmentFactor, row.Close / row.RawClose, rtol=1e-8
    ):
        raise ValueError("VWAP adjustment mismatch")
    for column in ("Open", "High", "Low", "Close"):
        if not np.allclose(row[column], row[f"Raw{column}"] * row.AdjustmentFactor, rtol=1e-10):
            raise ValueError("OHLC uniform adjustment mismatch")
    frame["RegularSessionUnavailable"] = unavailable
    frame["VWAPOutsideDailyRange"] = regular & ((frame.VWAP < frame.Low) | (frame.VWAP > frame.High))
    frame["VWAPScope"] = "KRX_amount_volume_scope_unverified"
    frame["PriceBasis"] = PRICE_BASIS
    halt = ~traded
    if (frame.loc[halt, ["RawVolume", "Amount"]] != 0).any().any():
        raise ValueError("Zero-volume row has inconsistent source amount")
    frame["Trading_Halt"] = halt.astype("int8")
    return frame.sort_values("Date").reset_index(drop=True)

def validate_flow(frame, day, columns):
    required = {"Date", "Code", *columns}
    if frame.empty or required - set(frame):
        raise ValueError("Incomplete flow cache schema")
    dates = pd.to_datetime(frame.Date).dt.normalize()
    if (
        not dates.eq(day).all()
        or frame.Code.duplicated().any()
        or not frame.Code.astype(str).str.fullmatch(r"[0-9A-Z]{6}").all()
    ):
        raise ValueError("Invalid flow cache date/code/duplicates")
    values = frame[columns].apply(pd.to_numeric, errors="coerce")
    # A partial investor response remains missing; never manufacture zero.
    if ((frame[columns].notna() & values.isna()).any().any()
            or np.isinf(values.to_numpy(dtype=float, na_value=np.nan)).any()
            or values.lt(0).any().any()):
        raise ValueError("Invalid flow values")
    frame = frame.copy()
    frame[columns] = values
    return frame

