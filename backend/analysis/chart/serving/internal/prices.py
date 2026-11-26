import re
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd

from ..contracts import valid_event_basis
from .hashing import canonical_hash

REQUIRED = ("Open", "High", "Low", "Close", "Volume", "VWAP")
PRICE_SOURCE = "KRX 비수정 OHLC·거래대금, 동일 수정계수 적용"
HISTORY_SIZE = 60
VOLATILITY_DAYS = 250
EVENT_METHOD = "daily-log-std-250-v1"


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
    # Integer rounding plus ~0.03% drift seen in suppliers' old corporate-action ratios.
    tolerance = 0.5 / close + 0.5 / close.shift() + 1e-3
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

def price_bars(frame):
    return [
        {"date": pd.Timestamp(row.Date).date().isoformat(), "close": float(row.Close), "volume": float(row.Volume)}
        for row in frame.itertuples()
    ]


def _valid_bars(frame):
    values = frame[["Close", "Volume"]].apply(pd.to_numeric, errors="coerce").to_numpy(dtype=float)
    return np.isfinite(values).all() and (values[:, 0] > 0).all() and (values[:, 1] >= 0).all()


def price_snapshot(frame, as_of, sessions, input_sha256, *, replay=False, basis_from=None):
    dates = pd.DatetimeIndex(pd.to_datetime(frame.Date)).normalize()
    if dates.empty or dates.hasnans or dates.has_duplicates or not dates.is_monotonic_increasing:
        raise ValueError("Empty, invalid, duplicate or out-of-order price dates")
    end = pd.Timestamp(as_of)
    expected = sessions[sessions <= end]
    history = frame.tail(HISTORY_SIZE)
    if (expected.empty or expected[-1] != end or
            not dates[-HISTORY_SIZE:].equals(expected[-HISTORY_SIZE:])):
        raise ValueError("Price history does not match verified trading sessions")
    if not _valid_bars(history):
        raise ValueError("Prices must be positive and volumes nonnegative, all finite")
    result = {"basis": "adjusted_close", "source": PRICE_SOURCE, "history": price_bars(history)}
    if len(dates) < HISTORY_SIZE + 1 or not dates[-(HISTORY_SIZE + 1):].equals(expected[-(HISTORY_SIZE + 1):]):
        return result
    previous = frame.iloc[[-(HISTORY_SIZE + 1)]]
    if not _valid_bars(previous):
        return result
    previous_bar = price_bars(previous)[0]
    if replay:
        basis = frame.attrs.get("event_basis")
        if (valid_event_basis(basis, result["history"], as_of, input_sha256)
                and basis["previous_bar"] == previous_bar
                and len(expected) > basis["return_count"]
                and basis["period_start"] == expected[-basis["return_count"]].date().isoformat()):
            result["event_basis"] = basis
        return result
    if basis_from is not None:
        expected = expected[expected >= basis_from]
    baseline = expected[-(VOLATILITY_DAYS + 1):]
    if len(baseline) < HISTORY_SIZE + 1 or not dates[-len(baseline):].equals(baseline):
        return result
    close = pd.to_numeric(frame.Close.tail(len(baseline)), errors="coerce").to_numpy(dtype=float)
    if not np.isfinite(close).all() or (close <= 0).any():
        return result
    sigma = float(np.diff(np.log(close)).std(ddof=1))
    if np.isfinite(sigma) and sigma > 0:
        result["event_basis"] = {
            "method": EVENT_METHOD,
            "daily_sigma": sigma,
            "return_count": len(baseline) - 1,
            "period_start": baseline[1].date().isoformat(),
            "period_end": as_of,
            "input_sha256": input_sha256,
            "previous_bar": previous_bar,
        }
    return result


def archive_basis_record(frame, code, as_of, basis):
    return {
        "stock_code": code,
        "as_of": as_of,
        "input_sha256": frame.attrs["input_sha256"],
        "bars_sha256": canonical_hash(price_bars(frame)),
        "basis_sha256": canonical_hash(basis),
        "basis": basis,
    }


def restore_archive_basis(frame, code, as_of, record):
    if not isinstance(record, dict) or len(frame) != HISTORY_SIZE + 1:
        return
    try:
        basis = record.get("basis")
        if (valid_event_basis(basis, price_bars(frame.tail(HISTORY_SIZE)), as_of, frame.attrs.get("input_sha256"))
                and basis["previous_bar"] == price_bars(frame.iloc[[0]])[0]
                and record == archive_basis_record(frame, code, as_of, basis)):
            frame.attrs["event_basis"] = basis
    except (ValueError, TypeError, AttributeError, OverflowError):
        return
