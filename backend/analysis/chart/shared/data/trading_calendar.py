import json
import os
from collections.abc import Collection
from datetime import date, datetime
from pathlib import Path

import pandas as pd

# 실행 위치(CWD)와 무관하게 chart/data/ 아래 한 파일을 쓴다(추론 서버 등 CWD가 다른 호출자, #107).
TRADING_CALENDAR_CACHE_PATH = os.path.join(
    str(Path(__file__).resolve().parents[2]), "workspace", "archive", "data", "krx_trading_calendar.json"
)
_TRADING_CALENDAR_SOURCE = "KRX verified trading days v2"
_TRADING_CALENDAR_PROVIDER = "pykrx KOSPI 1001 + KRX MDCSTAT00301 + XKRX"


class TradingCalendarError(RuntimeError):
    """KRX 거래일을 신뢰할 수 있는 출처에서 확정하지 못했을 때 발생합니다."""


def _fetch_pykrx_index(start: pd.Timestamp, end: pd.Timestamp, ticker="1001") -> pd.DataFrame:
    from .providers import krx

    return krx.get_index_ohlcv_by_date(
        start.strftime("%Y%m%d"), end.strftime("%Y%m%d"), ticker, name_display=False,
    )


def _fetch_direct_index(start, end):
    from .calendar import fetch_authenticated_index

    return fetch_authenticated_index(start, end)


def _load_trading_calendar_cache(
    start_date: pd.Timestamp, end_date: pd.Timestamp
) -> set[date]:
    """요청 범위를 모두 포함하는 경우에만 로컬 거래일 캐시를 반환합니다."""
    if not os.path.exists(TRADING_CALENDAR_CACHE_PATH):
        return set()

    try:
        with open(TRADING_CALENDAR_CACHE_PATH, encoding="utf-8") as cache_file:
            payload = json.load(cache_file)

        if payload.get("source") != _TRADING_CALENDAR_SOURCE:
            return set()
        coverage_start = pd.Timestamp(payload["coverage_start"]).normalize()
        coverage_end = pd.Timestamp(payload["coverage_end"]).normalize()
        if coverage_start > start_date or coverage_end < end_date:
            return set()

        trading_days = {
            pd.Timestamp(value).date()
            for value in payload["trading_days"]
            if start_date <= pd.Timestamp(value).normalize() <= end_date
        }
        from .calendar import scheduled_sessions

        expected = scheduled_sessions(start_date, end_date)
        if not pd.DatetimeIndex(sorted(trading_days)).equals(expected):
            return set()
        return trading_days
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError):
        return set()


def _save_trading_calendar_cache(
    start_date: pd.Timestamp,
    end_date: pd.Timestamp,
    trading_days: set[date],
    provider: str,
) -> None:
    """검증된 KRX 거래일과 조회 범위를 원자적으로 저장합니다."""
    coverage_start = start_date
    coverage_end = end_date
    cached_days = set()
    if os.path.exists(TRADING_CALENDAR_CACHE_PATH):
        try:
            with open(TRADING_CALENDAR_CACHE_PATH, encoding="utf-8") as cache_file:
                cached_payload = json.load(cache_file)
            cached_start = pd.Timestamp(cached_payload["coverage_start"]).normalize()
            cached_end = pd.Timestamp(cached_payload["coverage_end"]).normalize()
            ranges_connect = (
                start_date <= cached_end + pd.Timedelta(1, unit="D")
                and end_date >= cached_start - pd.Timedelta(1, unit="D")
            )
            if cached_payload.get("source") == _TRADING_CALENDAR_SOURCE and ranges_connect:
                coverage_start = min(start_date, cached_start)
                coverage_end = max(end_date, cached_end)
                cached_days = {
                    cached_day
                    for value in cached_payload["trading_days"]
                    if (cached_day := pd.Timestamp(value).date()) < start_date.date()
                    or cached_day > end_date.date()
                }
        except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError):
            cached_days = set()

    merged_days = trading_days | cached_days
    os.makedirs(os.path.dirname(TRADING_CALENDAR_CACHE_PATH), exist_ok=True)
    payload = {
        "source": _TRADING_CALENDAR_SOURCE,
        "provider": provider,
        "coverage_start": coverage_start.strftime("%Y-%m-%d"),
        "coverage_end": coverage_end.strftime("%Y-%m-%d"),
        "fetched_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "trading_days": sorted(day.isoformat() for day in merged_days),
    }
    temporary_path = f"{TRADING_CALENDAR_CACHE_PATH}.tmp"
    with open(temporary_path, "w", encoding="utf-8") as cache_file:
        json.dump(payload, cache_file, ensure_ascii=False, indent=2)
    os.replace(temporary_path, TRADING_CALENDAR_CACHE_PATH)


def get_krx_trading_days(start_date: str, end_date: str) -> set[date]:
    """검증된 캐시 또는 KRX 지수로 영업일을 확인합니다."""
    start = pd.Timestamp(start_date).normalize()
    end = pd.Timestamp(end_date).normalize()
    if start > end:
        raise ValueError("start_date는 end_date보다 늦을 수 없습니다.")
    cached_days = _load_trading_calendar_cache(start, end)
    if cached_days:
        return cached_days

    from .calendar import scheduled_sessions
    from .validation import validate_index

    try:
        primary = validate_index(_fetch_pykrx_index(start, end), start, end)
        direct = validate_index(_fetch_direct_index(start, end), start, end)
        scheduled = scheduled_sessions(start, end)
        if not primary.index.equals(direct.index) or not primary.index.equals(scheduled):
            raise ValueError("KRX index dates disagree with direct KRX or XKRX sessions")
        trading_days = set(primary.index.date)
        try:
            _save_trading_calendar_cache(start, end, trading_days, _TRADING_CALENDAR_PROVIDER)
        except OSError as exc:
            print(f"KRX 거래일 캐시 저장 실패: {exc}")
        return trading_days
    except Exception as exc:
        raise TradingCalendarError(
            "KOSPI 지수 거래일 조회에 실패했고 요청 범위를 덮는 캐시도 없습니다. "
            f"공급자 오류: {exc}"
        ) from exc


def reindex_to_krx_trading_days(
    df: pd.DataFrame,
    trading_days: Collection[date | pd.Timestamp | str] | None = None,
) -> pd.DataFrame:
    """종목 데이터를 실제 KRX 개장일로만 재구성합니다."""
    if df.empty:
        return df.copy()

    indexed = df.copy()
    if "Date" in indexed.columns:
        indexed = indexed.set_index("Date")
    indexed.index = pd.to_datetime(indexed.index).normalize()
    indexed = indexed.sort_index()

    start = indexed.index.min()
    end = indexed.index.max()
    if trading_days is None:
        trading_days = get_krx_trading_days(
            start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d")
        )

    market_index = pd.DatetimeIndex(pd.to_datetime(list(trading_days))).normalize()
    market_index = market_index[(market_index >= start) & (market_index <= end)].unique().sort_values()
    if market_index.empty:
        raise TradingCalendarError("종목 데이터 기간에 해당하는 KRX 거래일이 없습니다.")

    unexpected_dates = indexed.index.unique().difference(market_index)
    if not unexpected_dates.empty:
        formatted = ", ".join(day.strftime("%Y-%m-%d") for day in unexpected_dates[:5])
        raise TradingCalendarError(f"KRX 거래일이 아닌 원본 데이터 날짜가 있습니다: {formatted}")

    indexed = indexed.reindex(market_index)
    indexed.index.name = "Date"
    return indexed
