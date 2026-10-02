"""Adjusted KRX OHLCV with actual turnover-derived adjusted VWAP."""

import re

import numpy as np
import pandas as pd

from .progress import stage


def attach_actual_vwap(adjusted: pd.DataFrame, raw: pd.DataFrame) -> pd.DataFrame:
    """Use KRX unadjusted turnover and volume, scaled to adjusted close."""
    if adjusted.empty or raw.empty:
        raise ValueError("Adjusted and raw KRX frames are required")
    result = adjusted.copy()
    result.index = pd.to_datetime(result.index).normalize()
    source = raw.rename(columns={"종가": "RawClose", "거래량": "RawVolume", "거래대금": "Amount"})
    source.index = pd.to_datetime(source.index).normalize()
    needed = {"RawClose", "RawVolume", "Amount"}
    if not needed.issubset(source):
        raise ValueError(f"Actual VWAP inputs missing: {sorted(needed - set(source))}")
    result = result.join(source[["RawClose", "RawVolume", "Amount"]].apply(pd.to_numeric, errors="coerce"), how="left")
    traded = pd.to_numeric(result["Volume"], errors="coerce").fillna(0).gt(0)
    bad = traded & (
        result[["RawClose", "RawVolume", "Amount"]].isna().any(axis=1)
        | result[["RawClose", "RawVolume", "Amount"]].le(0).any(axis=1)
    )
    if bad.any():
        raise ValueError(f"KRX turnover missing for traded dates: {result.index[bad][:5].tolist()}")
    result["AdjustmentFactor"] = result["Close"] / result["RawClose"].where(result["RawClose"].gt(0))
    result["VWAP"] = result["Amount"] / result["RawVolume"] * result["AdjustmentFactor"]
    result.loc[~traded, "VWAP"] = np.nan
    return result


def fetch_prices(code: str, start_date: str, end_date: str) -> pd.DataFrame:
    """Fetch both price bases from KRX; imports pykrx only when collection runs."""
    from pykrx import stock

    if not re.fullmatch(r"[0-9A-Z]{6}", code):
        raise ValueError("Stock code must be six uppercase alphanumeric characters")
    start, end = start_date.replace("-", ""), end_date.replace("-", "")
    adjusted = fetch_adjusted_prices(code, start_date, end_date)
    with stage("krx_raw_prices", stock_code=code):
        raw = stock.get_market_ohlcv_by_date(start, end, code, adjusted=False)
    if raw.empty:
        raise ValueError(f"KRX prices unavailable for {code}")
    return attach_actual_vwap(adjusted, raw).reset_index()


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
    required = {"종가", "거래량", "거래대금"}
    if (not 500 <= len(frame) <= 1200 or not required.issubset(frame)
            or frame.index.duplicated().any()):
        raise ValueError(f"Invalid KRX daily market data for {as_of}")
    return frame


def fetch_incremental_prices(code, start, as_of, stored, daily):
    """Refresh adjusted bases, while reusing archived raw prices and daily market reads."""
    adjusted = fetch_adjusted_prices(code, start, as_of)
    parts = []
    if not stored.empty:
        parts.append(stored.set_index("Date")[["RawClose", "RawVolume", "Amount"]].rename(
            columns={"RawClose": "종가", "RawVolume": "거래량", "Amount": "거래대금"}))
    for day, market in daily.items():
        if code in market.index:
            parts.append(pd.DataFrame([market.loc[code, ["종가", "거래량", "거래대금"]]],
                                      index=pd.DatetimeIndex([day])))
    raw = pd.concat(parts) if parts else pd.DataFrame(columns=["종가", "거래량", "거래대금"])
    raw = raw.loc[~raw.index.duplicated(keep="last")].reindex(adjusted.index)
    # Per-stock raw history is needed only for a newly listed/missing archive.
    traded = adjusted.Volume.gt(0)
    missing = raw[["종가", "거래량", "거래대금"]].isna().any(axis=1) | raw[["종가", "거래량", "거래대금"]].le(0).any(axis=1)
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
    previous = previous[values.columns]
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
