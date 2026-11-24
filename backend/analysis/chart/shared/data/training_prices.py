import re
import tempfile
import time
from pathlib import Path

import numpy as np
import pandas as pd

from shared.io import atomic_parquet, sha256

from .events import apply_events, derive_events
from .validation import KRX_RAW_COLUMNS, validate_krx_raw, validate_prices

KRX_FIELDS = {
    "TDD_OPNPRC": "RawOpen", "TDD_HGPRC": "RawHigh", "TDD_LWPRC": "RawLow",
    "TDD_CLSPRC": "RawClose", "CMPPREVDD_PRC": "RawChange", "ACC_TRDVOL": "RawVolume",
    "ACC_TRDVAL": "Amount", "LIST_SHRS": "ListedShares",
}
PRICE_SOURCE = "KRX raw"


def parse_krx_fields(rows):
    if rows.empty or set(KRX_FIELDS) - set(rows):
        raise ValueError("Empty or incomplete KRX raw price response")
    frame = rows.rename(columns=KRX_FIELDS).copy()
    for column in KRX_FIELDS.values():
        frame[column] = pd.to_numeric(frame[column].astype(str).str.replace(",", ""), errors="raise")
    return frame


def request_history(code, start, end, *, is_delisted):
    from pykrx.website.krx.market.core import 개별종목시세
    from pykrx.website.krx.market.ticker import StockTicker

    tickers = StockTicker()
    market = tickers.delisted if is_delisted else tickers.listed
    candidates = market.loc[market.index == code, "ISIN"].drop_duplicates()
    securities = [
        isin for isin in candidates if isinstance(isin, str)
        and not isin.startswith("KRA") and re.fullmatch(r"[A-Z]{2}[0-9A-Z]{9}[0-9]", isin)
    ]
    if len(securities) != 1:
        raise ValueError(f"{code}: expected one KRX security identifier, found {len(securities)}")
    rows = 개별종목시세().fetch(start.strftime("%Y%m%d"), end.strftime("%Y%m%d"), securities[0], 1)
    frame = parse_krx_fields(rows)
    frame["Date"] = pd.to_datetime(frame["TRD_DD"], format="%Y/%m/%d")
    return frame[KRX_RAW_COLUMNS]


def fetch_raw_window(code, days, *, is_delisted, source, progress=None):
    parts = []
    remaining = days
    while len(remaining):
        end = remaining[0] + pd.DateOffset(years=2)
        window = remaining[remaining < end]
        remaining = remaining[remaining >= end]
        for attempt in range(1, 4):
            try:
                with source._krx_request_timeout():
                    raw = request_history(code, window[0], window[-1], is_delisted=is_delisted)
                parts.append(validate_krx_raw(raw, window))
                break
            except Exception as exc:
                if progress:
                    progress({"state": "request_failed", "stage": "prices", "code": code,
                              "provider": PRICE_SOURCE, "attempt": attempt, "reason": str(exc),
                              "exception_type": type(exc).__name__, **getattr(exc, "details", {})})
                if attempt == 3:
                    raise
                time.sleep(attempt)
    return pd.concat(parts, ignore_index=True)


def check_raw_overlap(previous, current):
    columns = [col for col in KRX_RAW_COLUMNS[1:] if col in previous]
    overlap = previous.set_index("Date")[columns].join(
        current.set_index("Date")[columns], how="inner", lsuffix="_old", rsuffix="_new", validate="one_to_one"
    )
    for column in columns:
        old, new = overlap[f"{column}_old"], overlap[f"{column}_new"]
        equal = old.eq(new).fillna(False) | (old.isna() & new.isna())
        if not equal.all():
            date = equal.index[~equal][0]
            raise ValueError(f"KRX raw {column} differs from preserved data on {date:%Y-%m-%d}")


def load_training_raw(path, days, digest=None):
    if not path.exists() and digest is None:
        return None
    if digest is not None and sha256(path) != digest:
        raise ValueError(f"Preserved KRX raw hash mismatch: {path.name}")
    return validate_krx_raw(pd.read_parquet(path), days)


def preserve_training_raw(path, frame):
    """Install the source once, including when two collectors converge on the same ticker."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=path.parent) as staging:
        staged = Path(staging) / path.name
        atomic_parquet(staged, frame)
        try:
            path.hardlink_to(staged)
        except FileExistsError:
            before = load_training_raw(path, pd.DatetimeIndex(frame.Date))
            check_raw_overlap(before, frame)


def adjust_training_window(code, raw, days, as_of):
    if days.empty or days[-1] > pd.Timestamp(as_of):
        raise ValueError("KRX raw price dates exceed the dataset as_of")
    events = derive_events(code, raw, days)
    adjusted = apply_events(raw, events, as_of=as_of)
    adjusted["Change"] = 100 * raw.RawChange / (raw.RawClose - raw.RawChange)
    adjusted["PriceProvider"] = PRICE_SOURCE
    returns = adjusted.Close.pct_change().iloc[1:]
    if not np.allclose(returns, adjusted.Change.iloc[1:] / 100, rtol=1e-10, atol=1e-12):
        raise ValueError("Adjusted daily return disagrees with KRX base-price change")
    return validate_prices(adjusted, days, event_adjusted=True), events
