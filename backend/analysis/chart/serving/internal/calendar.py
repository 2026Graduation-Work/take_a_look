"""Serving calendar storage uses the shared v3 verification rules."""
import json

import pandas as pd
from shared.data.calendar import build_calendar, verify_calendar_schedule
from shared.data.trading_calendar import (  # noqa: F401
    TradingCalendarError,
    reindex_to_krx_trading_days,
)
from shared.settings import serving_root


def _calendar_path():
    return serving_root() / "cache/calendar/calendar.json"


def refresh_krx_trading_days(start_date, end_date):
    root = _calendar_path().parent
    root.mkdir(parents=True, exist_ok=True)
    payload = build_calendar(root, {"start_date": start_date, "end_date": end_date})
    return set(pd.to_datetime(payload["trading_days"]).date)


def get_krx_trading_days(start_date, end_date):
    try:
        payload = json.loads(_calendar_path().read_text())
        start, end = pd.Timestamp(start_date), pd.Timestamp(end_date)
        if pd.Timestamp(payload["requested_start"]) > start or pd.Timestamp(payload["checked_end"]) < end:
            raise ValueError("Calendar coverage does not include requested dates")
        verify_calendar_schedule(payload)
        days = pd.to_datetime(payload["trading_days"])
        return set(days[(days >= start) & (days <= end)].date)
    except (OSError, ValueError, KeyError) as exc:
        raise TradingCalendarError(f"Verified serving calendar absent: {exc}") from exc
