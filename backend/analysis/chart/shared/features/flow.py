"""Investor net amount / unadjusted total amount on market-session windows."""

import numpy as np
import pandas as pd

from .columns import FLOW_FEATURES


def build_flow_features(raw, market_days):
    raw = raw.copy()
    raw["Date"] = pd.to_datetime(raw.Date).dt.normalize()
    if raw.Date.duplicated().any():
        raise ValueError("Duplicate raw flow dates")
    days = pd.DatetimeIndex(pd.to_datetime(market_days)).sort_values()
    days = days[(days >= raw.Date.min()) & (days <= raw.Date.max())]
    indexed = raw.set_index("Date").reindex(days)
    amount = pd.to_numeric(indexed.Amount, errors="coerce")
    result = pd.DataFrame({"Date": days, "Code": raw.Code.iloc[0], "AvailableDate": days})
    for investor in ("Individual", "Institution", "Foreign"):
        buy = pd.to_numeric(
            indexed.get(f"{investor}_BuyAmount", pd.Series(np.nan, index=days)), errors="coerce"
        )
        sell = pd.to_numeric(
            indexed.get(f"{investor}_SellAmount", pd.Series(np.nan, index=days)), errors="coerce"
        )
        net = buy - sell
        for window in (1, 5, 20):
            numerator = net.rolling(window, min_periods=window).sum()
            denominator = (
                amount.rolling(window, min_periods=window).sum().where(lambda values: values > 0)
            )
            result[f"flow_{investor.lower()}_{window}"] = (numerator / denominator).to_numpy()
    return result[["Date", "Code", "AvailableDate", *FLOW_FEATURES]]
