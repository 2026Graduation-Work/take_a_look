"""Official KOSPI session calendar used to distinguish halts from holidays."""

import json
import os
from collections.abc import Collection
from datetime import UTC, date, datetime
from pathlib import Path

import pandas as pd


class TradingCalendarError(RuntimeError):
    """Official session coverage is missing or inconsistent."""


def refresh_krx_trading_days(start_date: str, end_date: str) -> set[date]:
    """Fetch official KOSPI index sessions and atomically store a coverage artifact."""
    from pykrx import stock

    start, end = pd.Timestamp(start_date).normalize(), pd.Timestamp(end_date).normalize()
    if start > end:
        raise ValueError("start_date is after end_date")
    root = os.environ.get("CHART_SERVING_DATA_DIR")
    if not root:
        raise TradingCalendarError("CHART_SERVING_DATA_DIR is required")
    index = stock.get_index_ohlcv_by_date(
        start.strftime("%Y%m%d"), end.strftime("%Y%m%d"), "1001", name_display=False
    )
    if index.empty:
        raise TradingCalendarError("KRX KOSPI index returned no sessions")
    days = {pd.Timestamp(value).date() for value in index.index}
    if any(day < start.date() or day > end.date() for day in days):
        raise TradingCalendarError("KRX index returned an out-of-range session")
    path = Path(root) / "krx_trading_calendar.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "source": "KOSPI index trading days",
        "provider": "KRX KOSPI index 1001 via pykrx",
        "coverage_start": start.date().isoformat(),
        "coverage_end": end.date().isoformat(),
        "fetched_at": datetime.now(UTC).isoformat(),
        "trading_days": sorted(day.isoformat() for day in days),
    }
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)
    return days


def get_krx_trading_days(start_date: str, end_date: str) -> set[date]:
    """Read a coverage-checked calendar artifact; never infer sessions from weekdays."""
    start, end = pd.Timestamp(start_date).normalize(), pd.Timestamp(end_date).normalize()
    if start > end:
        raise ValueError("start_date is after end_date")
    data_root = os.environ.get("CHART_SERVING_DATA_DIR")
    if not data_root:
        raise TradingCalendarError("CHART_SERVING_DATA_DIR is required")
    path = Path(data_root) / "krx_trading_calendar.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if payload.get("source") != "KOSPI index trading days":
            raise ValueError("unknown calendar source")
        if pd.Timestamp(payload["coverage_start"]) > start or pd.Timestamp(payload["coverage_end"]) < end:
            raise ValueError("calendar coverage does not include requested dates")
        days = {pd.Timestamp(value).date() for value in payload["trading_days"]}
        return {day for day in days if start.date() <= day <= end.date()}
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise TradingCalendarError(f"Official calendar unavailable: {path}: {exc}") from exc


def reindex_to_krx_trading_days(
    df: pd.DataFrame,
    trading_days: Collection[date | pd.Timestamp | str] | None = None,
) -> pd.DataFrame:
    """Reindex only within the observed listing period, matching training semantics."""
    if df.empty:
        return df.copy()
    indexed = df.copy()
    if "Date" in indexed.columns:
        indexed = indexed.set_index("Date")
    indexed.index = pd.to_datetime(indexed.index).normalize()
    if indexed.index.has_duplicates:
        raise TradingCalendarError("Duplicate source dates")
    indexed = indexed.sort_index()
    start, end = indexed.index.min(), indexed.index.max()
    if trading_days is None:
        trading_days = get_krx_trading_days(start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d"))
    market_index = pd.DatetimeIndex(pd.to_datetime(list(trading_days))).normalize()
    market_index = market_index[(market_index >= start) & (market_index <= end)].unique().sort_values()
    if market_index.empty:
        raise TradingCalendarError("No KRX sessions within source period")
    unexpected = indexed.index.unique().difference(market_index)
    if not unexpected.empty:
        formatted = ", ".join(day.strftime("%Y-%m-%d") for day in unexpected[:5])
        raise TradingCalendarError(f"KRX 거래일이 아닌 원본 데이터 날짜가 있습니다: {formatted}")
    indexed = indexed.reindex(market_index)
    indexed.index.name = "Date"
    return indexed
