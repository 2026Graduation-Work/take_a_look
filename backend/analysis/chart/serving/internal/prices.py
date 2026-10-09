"""Adjusted KRX OHLCV with actual turnover-derived adjusted VWAP."""

import json
import os
import re
from pathlib import Path

import numpy as np
import pandas as pd

from .progress import report, stage

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
    root = Path(os.environ.get("CHART_SERVING_DATA_DIR", Path(__file__).parents[1] / "data"))
    seed = root / "bootstrap_raw" / f"{code}.parquet"
    raw = pd.DataFrame()
    if seed.is_file():
        cached = pd.read_parquet(seed).set_index("Date")
        raw = cached.loc[cached.index.isin(adjusted.index)].drop(columns="Code").rename(columns={
            "RawOpen": "시가", "RawHigh": "고가", "RawLow": "저가", "RawClose": "종가",
            "RawVolume": "거래량", "Amount": "거래대금"})
        if not raw.index.equals(adjusted.index):
            raw = pd.DataFrame()
    if raw.empty:
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


def bootstrap_raw_prices(root, codes, trading_days):
    """Share historical daily raw requests when many stocks lack archives."""
    from core.bulk_prices import fetch_day, validate_day
    from core.local_config import atomic_json, atomic_parquet
    from core.local_dataset import sha256
    from data_collectors import price_collector as source

    cache_root = root / "bootstrap_days"
    parts = []
    days = pd.DatetimeIndex(pd.to_datetime(sorted(trading_days)))
    for index, day in enumerate(days, 1):
        path = cache_root / f"{day:%Y-%m-%d}.parquet"
        meta = path.with_suffix(".json")
        frame = None
        if path.is_file() and meta.is_file():
            metadata = json.loads(meta.read_text())
            if metadata.get("sha256") == sha256(path):
                frame = validate_day(pd.read_parquet(path), day)
                if not set(codes).issubset(metadata.get("codes", [])):
                    frame = None
        if frame is None:
            frame = fetch_day(source, day, lambda event: report("bootstrap_price_request", **event))
            frame = frame.loc[frame.Code.isin(codes)]
            atomic_parquet(path, frame)
            atomic_json(meta, {"sha256": sha256(path), "codes": codes})
        parts.append(frame)
        if index % 25 == 0 or index == len(days):
            report("bootstrap_price_days", completed=index, total=len(days))
    panel = pd.concat(parts, ignore_index=True)
    for code, frame in panel.groupby("Code", sort=False):
        atomic_parquet(root / "bootstrap_raw" / f"{code}.parquet", frame)


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

def fetch_adjusted_prices(code, start_date, end_date):
    from pykrx import stock

    with stage("adjusted_price_history", stock_code=code):
        adjusted = stock.get_market_ohlcv_by_date(
            start_date.replace("-", ""), end_date.replace("-", ""), code, adjusted=True)
    if adjusted.empty:
        raise ValueError(f"KRX prices unavailable for {code}")
    adjusted = adjusted.rename(columns={"시가": "Open", "고가": "High", "저가": "Low", "종가": "Close", "거래량": "Volume", "등락률": "Change"})
    required = ["Open", "High", "Low", "Close", "Volume", "Change"]
    if not set(required).issubset(adjusted):
        raise ValueError(f"Adjusted KRX fields missing: {sorted(set(required) - set(adjusted))}")
    adjusted = adjusted[required].copy()
    adjusted["Change"] = adjusted["Change"].fillna(0.0)
    adjusted.index.name = "Date"
    return adjusted


def fetch_daily_prices(as_of):
    """One KRX market read for every stock's raw prices and actual turnover."""
    from pykrx import stock

    with stage("krx_daily_market", as_of=as_of):
        frame = stock.get_market_ohlcv_by_ticker(as_of.replace("-", ""), market="KOSPI")
    required = {"시가", "고가", "저가", "종가", "거래량", "거래대금"}
    if (not 500 <= len(frame) <= 1200 or not required.issubset(frame)
            or frame.index.duplicated().any()):
        raise ValueError(f"Invalid KRX daily market data for {as_of}")
    return frame


def fetch_incremental_prices(code, start, as_of, stored, daily):
    """Refresh adjusted bases, while reusing archived raw prices and daily market reads."""
    adjusted = fetch_adjusted_prices(code, start, as_of)
    parts = []
    if not stored.empty and {"RawOpen", "RawHigh", "RawLow", "RawClose", "RawVolume", "Amount"}.issubset(stored):
        parts.append(stored.set_index("Date")[["RawOpen", "RawHigh", "RawLow", "RawClose", "RawVolume", "Amount"]].rename(
            columns={"RawOpen": "시가", "RawHigh": "고가", "RawLow": "저가", "RawClose": "종가", "RawVolume": "거래량", "Amount": "거래대금"}))
    for day, market in daily.items():
        if code in market.index:
            parts.append(pd.DataFrame([market.loc[code, ["시가", "고가", "저가", "종가", "거래량", "거래대금"]]],
                                      index=pd.DatetimeIndex([day])))
    raw = pd.concat(parts) if parts else pd.DataFrame(columns=["시가", "고가", "저가", "종가", "거래량", "거래대금"])
    raw = raw.loc[~raw.index.duplicated(keep="last")].reindex(adjusted.index)
    # Per-stock raw history is needed only for a newly listed/missing archive.
    traded = adjusted.Volume.gt(0)
    missing = raw[["시가", "고가", "저가", "종가", "거래량", "거래대금"]].isna().any(axis=1) | raw[["시가", "고가", "저가", "종가", "거래량", "거래대금"]].le(0).any(axis=1)
    if (traded & missing).any():
        from pykrx import stock

        with stage("krx_raw_history_backfill", stock_code=code):
            raw = stock.get_market_ohlcv_by_date(start.replace("-", ""), as_of.replace("-", ""), code, adjusted=False)
        if raw.empty:
            raise ValueError(f"KRX prices unavailable for {code}")
    else:
        # Market-wide data can show zero quotes for halts; preserve the last raw close.
        raw["종가"] = raw["종가"].replace(0, np.nan).ffill()
    return attach_actual_vwap(adjusted, raw).reset_index()


def changed_price_rows(fresh, stored):
    """Write only new dates or corrections, including historical split adjustments."""
    if stored.empty:
        return fresh
    previous = stored.set_index("Date").reindex(pd.to_datetime(fresh.Date))
    previous.index = fresh.index
    values = fresh.drop(columns="Date")
    previous = previous.reindex(columns=values.columns)
    equal = values.eq(previous) | (values.isna() & previous.isna())
    # PostgREST round-trips derived doubles with tiny decimal differences.
    # Observed prices, volumes and turnover still require exact equality.
    for column in ("Change", "AdjustmentFactor", "VWAP"):
        equal[column] = np.isclose(values[column].to_numpy(float), previous[column].to_numpy(float),
                                   rtol=1e-14, atol=1e-12, equal_nan=True)
    return fresh.loc[~equal.all(axis=1)]



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
