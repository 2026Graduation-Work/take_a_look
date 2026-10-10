"""Header market bar row: three index closes plus KOSPI volatility/turnover percentiles.

Same formulas as frontend/scripts/build_demo_snapshot.py (20-day window, 252-day lookback),
read from the KRX index OHLCV that daily serving already uses for its calendar.
"""

from datetime import date, timedelta

import numpy as np
import pandas as pd

INDICES = (("1001", "KOSPI", "KOSPI"), ("2001", "KOSDAQ", "KOSDAQ"), ("1028", "KOSPI200", "KOSPI 200"))
WINDOW = 20
LOOKBACK = 252


def percentile_of_last(series, lookback=LOOKBACK):
    """Where the last value sits among the previous `lookback` values (0~1); ties count half."""
    values = series.dropna()
    current, history = values.iloc[-1], values.iloc[-lookback - 1:-1]
    if len(history) < lookback:
        raise ValueError(f"Not enough history for percentile: {len(history)} < {lookback}")
    below = (history < current).sum() + 0.5 * (history == current).sum()
    return float(below / len(history))


def market_status_row(stock, as_of):
    end = date.fromisoformat(as_of)
    start = end - timedelta(days=500)  # 252 + 20 trading days with holiday slack
    frames = {code: stock.get_index_ohlcv_by_date(start.strftime("%Y%m%d"), end.strftime("%Y%m%d"),
                                                  code, name_display=False) for code, _, _ in INDICES}
    quotes = []
    for code, symbol, label in INDICES:
        close = frames[code]["종가"].astype(float)
        if close.index[-1].strftime("%Y-%m-%d") != as_of:
            raise ValueError(f"Index {symbol} has no close for {as_of}")
        last, prev = close.iloc[-1], close.iloc[-2]
        quotes.append({"symbol": symbol, "label": label, "value": round(last, 2),
                       "change": round(last - prev, 2), "changePercent": round((last / prev - 1) * 100, 2)})

    kospi = frames["1001"].astype(float)
    realized = np.log(kospi["종가"] / kospi["종가"].shift(1)).rolling(WINDOW).std(ddof=1) * np.sqrt(252)
    volatility = percentile_of_last(realized)
    turnover = percentile_of_last(kospi["거래대금"].rolling(WINDOW).mean())
    return {
        "status_date": as_of,
        "condition": "stable" if volatility < 0.6 else "caution" if volatility < 0.9 else "high_volatility",
        "volatility_score": round(volatility * 100),
        "volume_score": round(turnover * 100),
        "index_quotes": quotes,
        "updated_at": pd.Timestamp.now(tz="UTC").isoformat(),
    }
