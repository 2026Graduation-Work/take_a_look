"""Adjusted KRX OHLCV with actual turnover-derived adjusted VWAP."""

import re
from pathlib import Path

import numpy as np
import pandas as pd

REQUIRED = ("Open", "High", "Low", "Close", "Volume", "VWAP")


def attach_actual_vwap(adjusted: pd.DataFrame, raw: pd.DataFrame) -> pd.DataFrame:
    """Use the same raw OHLC scaling and VWAP calculation as collection."""
    from shared.data.providers import _attach_actual_vwap

    return _attach_actual_vwap(adjusted, raw)


def fetch_prices(code: str, start_date: str, end_date: str) -> pd.DataFrame:
    from shared.data.prices import fetch_price_window
    from shared.settings import serving_root

    from .calendar import get_krx_trading_days
    if not re.fullmatch(r"[0-9A-Z]{6}", code):
        raise ValueError("Stock code must be six uppercase alphanumeric characters")
    days = sorted(get_krx_trading_days(start_date, end_date))
    root = serving_root() / "cache/prices"
    # Since 2026-09-14 (KRX after-market) FDR/Naver closes drift from the regular-session close.
    # Prefer KRX raw OHLC + KRX's own adjusted close (the is_delisted path is exactly that adapter);
    # shared/ is pinned by the pack checksum, so the choice lives here until a new pack (co-deep).
    try:
        return fetch_price_window(code, days, root=root, is_delisted=True)
    except ValueError as exc:
        krx_error = exc
    prices = fetch_price_window(code, days, root=root)
    try:
        check_adjustment_steps(prices)
    except ValueError as exc:
        raise ValueError(f"Price providers exhausted: KRX adjusted ({krx_error}); fallback {exc}") from None
    return prices


def check_adjustment_steps(frame):
    """A KRX adjustment factor may move only on corporate-action days.

    Naver's after-market close moves it by 0.3~0.8% almost every day; real corporate actions
    move it a few times a year.
    """
    traded = frame.loc[frame.Volume.gt(0) & ~frame[["RawOpen", "RawHigh", "RawLow"]].eq(0).all(axis=1)]
    factor, close = traded.AdjustmentFactor.astype(float), traded.Close.astype(float)
    # Integer rounding plus ~0.03% drift seen in suppliers' old corporate-action ratios.
    tolerance = 0.5 / close + 0.5 / close.shift() + 1e-3
    steps = int(((factor / factor.shift() - 1).abs() > tolerance).sum())
    allowed = 3 + len(traded) // 250
    if steps > allowed:
        raise ValueError(f"Adjustment factor moved on {steps} days (allowed {allowed})")


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
