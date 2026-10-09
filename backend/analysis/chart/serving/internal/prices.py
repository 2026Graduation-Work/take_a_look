"""Adjusted KRX OHLCV with actual turnover-derived adjusted VWAP."""

import re
from pathlib import Path

import numpy as np
import pandas as pd

REQUIRED = ("Open", "High", "Low", "Close", "Volume", "VWAP")


def attach_actual_vwap(adjusted: pd.DataFrame, raw: pd.DataFrame) -> pd.DataFrame:
    """Use the same raw OHLC scaling and VWAP calculation as collection."""
    from data_collectors.price_collector import _attach_actual_vwap

    return _attach_actual_vwap(adjusted, raw)


def fetch_prices(code: str, start_date: str, end_date: str) -> pd.DataFrame:
    """Fetch both price bases from KRX; imports pykrx only when collection runs."""
    from pykrx import stock

    if not re.fullmatch(r"[0-9A-Z]{6}", code):
        raise ValueError("Stock code must be six uppercase alphanumeric characters")
    start, end = start_date.replace("-", ""), end_date.replace("-", "")
    adjusted = stock.get_market_ohlcv_by_date(start, end, code, adjusted=True)
    raw = stock.get_market_ohlcv_by_date(start, end, code, adjusted=False)
    if adjusted.empty or raw.empty:
        raise ValueError(f"KRX prices unavailable for {code}")
    adjusted = adjusted.rename(columns={"시가": "Open", "고가": "High", "저가": "Low", "종가": "Close", "거래량": "Volume", "등락률": "Change"})
    required = ["Open", "High", "Low", "Close", "Volume", "Change"]
    if not set(required).issubset(adjusted):
        raise ValueError(f"Adjusted KRX fields missing: {sorted(set(required) - set(adjusted))}")
    adjusted = adjusted[required].copy()
    adjusted["Change"] = adjusted["Close"].pct_change(fill_method=None) * 100
    adjusted.index.name = "Date"
    return attach_actual_vwap(adjusted, raw).reset_index()


def load_prices(path: str | Path) -> pd.DataFrame:
    """Load an immutable raw price snapshot with the fields needed by training."""
    frame = pd.read_parquet(path)
    missing = set(REQUIRED).difference(frame.columns)
    if missing:
        raise ValueError(f"Raw price snapshot missing: {sorted(missing)}")
    if "Date" not in frame.columns:
        raise ValueError("Raw price snapshot missing Date")
    frame = frame.copy()
    frame["Date"] = pd.to_datetime(frame["Date"])
    if frame["Date"].isna().any() or frame["Date"].duplicated().any():
        raise ValueError("Invalid or duplicate raw price dates")
    return frame.sort_values("Date").reset_index(drop=True)

def price_snapshot(frame, code, as_of, source):
    """Export observed bars only; do not forward-fill missing sessions."""
    required = {"Date", "Close", "Volume"}
    if not required.issubset(frame.columns):
        raise ValueError(f"Missing price columns: {sorted(required - set(frame.columns))}")
    prices = frame.copy()
    prices["Date"] = pd.to_datetime(prices["Date"], errors="raise").dt.normalize()
    cutoff = pd.Timestamp(as_of).normalize()
    prices = prices.loc[prices.Date <= cutoff].sort_values("Date")
    if prices.empty or prices.Date.duplicated().any():
        raise ValueError("Empty price history or duplicate dates")
    values = prices[["Close", "Volume"]].to_numpy(dtype=float)
    if not np.isfinite(values).all() or (values[:, 0] <= 0).any() or (values[:, 1] < 0).any():
        raise ValueError("Prices must be positive and volumes nonnegative, all finite")
    last = prices.iloc[-1]
    history = prices.tail(60)
    return {
        "code": str(code),
        "requested_asof": cutoff.date().isoformat(),
        "data_asof": last.Date.date().isoformat(),
        "status": "available" if last.Date == cutoff else "stale",
        "source": source,
        "price_basis": "adjusted_close",
        "close": float(last.Close),
        "volume": float(last.Volume),
        "change_percent": (
            float((last.Close / prices.iloc[-2].Close - 1) * 100)
            if len(prices) >= 2 else None
        ),
        "history": [
            {"date": row.Date.date().isoformat(), "close": float(row.Close),
             "volume": float(row.Volume)}
            for row in history.itertuples()
        ],
    }
