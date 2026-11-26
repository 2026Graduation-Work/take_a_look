import re
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd

REQUIRED = ("Open", "High", "Low", "Close", "Volume", "VWAP")
ADJUSTED_COLUMNS = ["Open", "High", "Low", "Close", "VWAP", "AdjustmentFactor"]
PRICE_BASIS_INCONSISTENT = "price_adjustment_basis_inconsistent"


class PriceBasisError(ValueError):
    pass


def adjustment_tolerance(close, other_close):
    # Allow rounding in both provider closes and small drift in old ratios.
    return 0.5 / close + 0.5 / other_close + 1e-3


def merge_price_history(previous: pd.DataFrame, fresh: pd.DataFrame) -> tuple[pd.DataFrame, float | None]:
    columns = ["Date", "Close", "AdjustmentFactor", "Volume"]
    if any(set(columns) - set(frame) for frame in (previous, fresh)):
        raise PriceBasisError("Missing adjustment inputs")

    prefix = previous.loc[previous.Date.lt(fresh.Date.min())]
    overlap = previous[columns].merge(fresh[columns], on="Date", suffixes=("_old", "_new"), validate="one_to_one")
    # Zero-turnover rows may have no adjustment factor in either source.
    overlap = overlap.loc[~(overlap.Volume_old.eq(0) & overlap.Volume_new.eq(0))]
    if overlap.empty:
        if prefix.empty:
            return fresh, None
        raise PriceBasisError("No overlapping observations with turnover")
    factors = overlap[["AdjustmentFactor_old", "AdjustmentFactor_new"]].to_numpy(dtype=float, na_value=np.nan)
    closes = overlap[["Close_old", "Close_new"]].to_numpy(dtype=float, na_value=np.nan)
    if not np.isfinite(factors).all() or (factors <= 0).any():
        raise PriceBasisError("Invalid overlapping adjustment factor")
    if not np.isfinite(closes).all() or (closes <= 0).any():
        raise PriceBasisError("Invalid overlapping close")

    ratios = factors[:, 1] / factors[:, 0]
    if not np.isfinite(ratios).all() or (ratios <= 0).any():
        raise PriceBasisError("Invalid overlapping adjustment factor ratio")
    tolerance = adjustment_tolerance(closes[:, 1], closes[:, 0])
    lower = (ratios / (1 + tolerance)).max()
    upper = np.divide(ratios, 1 - tolerance, out=np.full_like(ratios, np.inf), where=tolerance < 1).min()
    if lower > upper:
        raise PriceBasisError("Adjustment factor ratios disagree across overlapping dates")
    if lower <= 1 <= upper:
        merged = pd.concat([previous, fresh], ignore_index=True).drop_duplicates("Date", keep="last")
        return merged, None

    ratio = float(np.clip(np.median(ratios), lower, upper))
    prefix = prefix.copy()
    prefix[ADJUSTED_COLUMNS] = prefix[ADJUSTED_COLUMNS] * ratio
    return pd.concat([prefix, fresh], ignore_index=True), ratio


def attach_actual_vwap(adjusted: pd.DataFrame, raw: pd.DataFrame) -> pd.DataFrame:
    from shared.data.providers import _attach_actual_vwap

    return _attach_actual_vwap(adjusted, raw)


def fetch_prices(code: str, start_date: str, end_date: str) -> pd.DataFrame:
    from shared.data import providers
    from shared.data.prices import fetch_price_window
    from shared.settings import serving_root

    from .calendar import get_krx_trading_days
    if not re.fullmatch(r"[0-9A-Z]{6}", code):
        raise ValueError("Stock code must be six uppercase alphanumeric characters")
    days = sorted(get_krx_trading_days(start_date, end_date))
    root = serving_root() / "cache/prices"
    # Since 2026-09-14 (KRX after-market) Naver closes drift from the regular-session close, and
    # pykrx's stock API serves adjusted=True from Naver too. Use KRX raw OHLC + KRX's own adjusted
    # series first. shared/ is pinned by the pack checksum, so the choice lives here until a new pack.
    krx_only = SimpleNamespace(krx=providers.krx, time=providers.time,
                               _krx_request_timeout=providers._krx_request_timeout,
                               _fetch_delisted_pykrx=_fetch_krx_adjusted)
    errors = []
    for options in ({"is_delisted": True, "source": krx_only}, {}):
        try:
            prices = fetch_price_window(code, days, root=root, **options)
            check_adjustment_steps(prices)
            return prices
        except ValueError as exc:
            errors.append(str(exc))
    raise ValueError("Price providers exhausted: " + " | ".join(errors))


def _fetch_krx_adjusted(code, start_date, end_date, *, raw_df):
    """KRX 개별종목 시세 with 수정종가 (MDCSTAT01701, adjStkPrc=2), scaled onto KRX raw OHLC."""
    import contextlib
    import io

    from shared.data.krx import install_request_timeout
    install_request_timeout()
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        from pykrx.website.krx.market.wrap import get_market_ohlcv_by_date
    adjusted = get_market_ohlcv_by_date(start_date.replace("-", ""), end_date.replace("-", ""), code, True)
    if adjusted is None or adjusted.empty:
        raise ValueError("Empty KRX adjusted response")
    adjusted = adjusted.rename(columns={"시가": "Open", "고가": "High", "저가": "Low", "종가": "Close",
                                        "거래량": "Volume", "등락률": "Change"})
    adjusted = adjusted[["Open", "High", "Low", "Close", "Volume", "Change"]].apply(pd.to_numeric, errors="raise")
    adjusted.index.name = "Date"
    return attach_actual_vwap(adjusted, raw_df)


def check_adjustment_steps(frame):
    """A KRX adjustment factor may move only on corporate-action days.

    Naver's after-market close moves it by 0.3~0.8% almost every day; real corporate actions
    move it a few times a year.
    """
    traded = frame.loc[frame.Volume.gt(0) & ~frame[["RawOpen", "RawHigh", "RawLow"]].eq(0).all(axis=1)]
    factor, close = traded.AdjustmentFactor.astype(float), traded.Close.astype(float)
    tolerance = adjustment_tolerance(close, close.shift())
    steps = int(((factor / factor.shift() - 1).abs() > tolerance).sum())
    allowed = 3 + len(traded) // 250
    if steps > allowed:
        raise ValueError(f"Adjustment factor moved on {steps} days (allowed {allowed})")


def load_prices(path: str | Path) -> pd.DataFrame:
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
