"""KRX index sessions checked against the XKRX exchange schedule."""
from pathlib import Path

import pandas as pd

from shared.io import atomic_json, atomic_parquet, sha256
from shared.settings import VALIDATION_VERSION

from .validation import validate_index

# Exchange-calendar rules are independent of the index price response. KRX's
# announced closures missing in exchange_calendars 4.13.2 are explicit exceptions.
# Sources: https://kind.krx.co.kr/external/2026/05/20/000110/20260520000197/32154.htm
# Same holiday schedule across markets: https://regulation.krx.co.kr/contents/RGL/03/03030100/RGL03030100.jsp
CALENDAR_RULES_VERSION = 1
ANNOUNCED_CLOSURES = {"2026-06-03": "Local election", "2026-07-17": "Constitution Day"}


def latest_confirmed_market_day(cutoff):
    from shared.data.providers import get_krx_session

    session = get_krx_session()
    if session is None:
        raise ValueError("KRX reference required to establish latest confirmed session")
    response = session.get(
        "https://data.krx.co.kr/comm/bldAttendant/executeForResourceBundle.cmd",
        params={"baseName": "krx.mdc.i18n.component", "key": "B128.bld"},
        timeout=30,
    )
    response.raise_for_status()
    value = response.json()["result"]["output"][0]["max_work_dt"]
    latest = pd.to_datetime(value, format="%Y%m%d").normalize()
    if latest > cutoff:
        from shared.data.providers import krx

        latest = pd.to_datetime(
            krx.get_nearest_business_day_in_a_week(cutoff.strftime("%Y%m%d"), prev=True),
            format="%Y%m%d",
        ).normalize()
        if latest > cutoff:
            raise ValueError("KRX could not establish a completed session before cutoff")
    return latest

def fetch_authenticated_index(start, end, ticker="1001"):
    """Read KRX's index endpoint using the existing authenticated session."""
    from shared.data.providers import get_krx_session

    session = get_krx_session()
    if session is None:
        raise ValueError("Authenticated KRX session required for direct index verification")
    if ticker not in {"1001", "2001"}:
        raise ValueError("Only KOSPI 1001 and KOSDAQ 2001 are supported")
    frames = []
    current = start
    while current <= end:
        chunk_end = min(current + pd.DateOffset(years=2) - pd.Timedelta(1, unit="D"), end)
        response = session.post(
            "https://data.krx.co.kr/comm/bldAttendant/getJsonData.cmd",
            data={
                "bld": "dbms/MDC/STAT/standard/MDCSTAT00301",
                "indIdx": ticker[0], "indIdx2": ticker[1:],
                "strtDd": current.strftime("%Y%m%d"),
                "endDd": chunk_end.strftime("%Y%m%d"),
                "share": "1", "money": "1", "csvxls_isNo": "false",
            },
            timeout=(10, 30),
        )
        response.raise_for_status()
        frame = pd.DataFrame(response.json()["output"])
        if frame.empty or {"TRD_DD", "CLSPRC_IDX"} - set(frame):
            raise ValueError(f"Missing direct KRX index response: {current.date()}..{chunk_end.date()}")
        frames.append(pd.DataFrame({
            "Date": pd.to_datetime(frame.TRD_DD),
            "Close": pd.to_numeric(frame.CLSPRC_IDX.astype(str).str.replace(",", "", regex=False)),
        }))
        current = chunk_end + pd.Timedelta(1, unit="D")
    return pd.concat(frames, ignore_index=True).set_index("Date")

def scheduled_sessions(start, end):
    import exchange_calendars as calendars

    if start < pd.Timestamp("2016-01-01") or end > pd.Timestamp("2026-12-31"):
        raise ValueError("Calendar rules reviewed for 2016..2026 only; review new KRX closures first")
    if start == end:
        offset = pd.Timedelta(days=7)
        schedule = calendars.get_calendar("XKRX", start=start - offset, end=end + offset)
    else:
        schedule = calendars.get_calendar("XKRX", start=start, end=end)
    sessions = schedule.sessions.tz_localize(None)
    return sessions[(sessions >= start) & (sessions <= end)].difference(
        pd.DatetimeIndex(pd.to_datetime(list(ANNOUNCED_CLOSURES)))
    )

def verify_calendar_schedule(payload):
    """Detect omissions shared by all price adapters, including both boundaries."""
    import exchange_calendars as calendars

    start, end = pd.Timestamp(payload["requested_start"]), pd.Timestamp(payload["checked_end"])
    expected = scheduled_sessions(start, end)
    observed = pd.DatetimeIndex(pd.to_datetime(payload["trading_days"]))
    if observed.has_duplicates or not observed.is_monotonic_increasing:
        raise ValueError("Invalid cached calendar dates/order")
    missing, extra = expected.difference(observed), observed.difference(expected)
    if len(missing) or len(extra):
        raise ValueError(
            "Calendar disagrees with independent XKRX schedule: "
            f"missing_sessions={missing.strftime('%Y-%m-%d').tolist()}, "
            f"unexpected_sessions={extra.strftime('%Y-%m-%d').tolist()}"
        )
    return {
        "rules_version": CALENDAR_RULES_VERSION,
        "provider": "exchange_calendars XKRX", "package_version": calendars.__version__,
        "rules_sha256": sha256(Path(__file__)),
        "announced_closures": ANNOUNCED_CLOSURES,
        "checked_start": str(start.date()), "checked_end": str(end.date()),
        "sessions": len(expected),
    }

def build_calendar(root, collection):
    from shared.data import trading_calendar as calendar

    start = pd.Timestamp(collection["start_date"])
    # A live session must never enter a historical dataset before its close.
    now = pd.Timestamp.now(tz="Asia/Seoul")
    confirmed_cutoff = now.tz_localize(None).normalize()
    if now.hour < 16:
        confirmed_cutoff -= pd.Timedelta(1, unit="D")
    requested_end = pd.Timestamp(collection.get("end_date") or confirmed_cutoff)
    end = min(requested_end, confirmed_cutoff)
    latest_reference = (
        latest_confirmed_market_day(confirmed_cutoff)
        if collection.get("end_date") is None
        else None
    )
    if latest_reference is not None:
        end = latest_reference
    primary_provider = "pykrx KOSPI 1001"
    primary = validate_index(calendar._fetch_pykrx_index(start, end), start, end)
    secondary = validate_index(fetch_authenticated_index(start, end), start, end)
    if not primary.index.equals(secondary.index):
        raise ValueError(
            "Calendar providers disagree; no verified coverage: "
            f"only {primary_provider}={primary.index.difference(secondary.index).strftime('%Y-%m-%d').tolist()}, "
            f"only direct KRX={secondary.index.difference(primary.index).strftime('%Y-%m-%d').tolist()}"
        )
    if primary.index[0] > start + pd.Timedelta(7, unit="D") or primary.index[-1] < end - pd.Timedelta(7, unit="D"):
        raise ValueError("Index response does not establish requested boundary coverage")
    effective_end = primary.index[-1]
    if latest_reference is not None and effective_end != latest_reference:
        raise ValueError("Index response is stale relative to KRX latest-session reference")
    kosdaq_provider = "pykrx KOSDAQ 2001"
    kosdaq = validate_index(calendar._fetch_pykrx_index(start, effective_end, "2001"), start, effective_end)
    if not kosdaq.index.equals(primary.index):
        raise ValueError("KOSDAQ index has missing sessions")
    payload = {
        "validation_version": VALIDATION_VERSION,
        "requested_start": str(start.date()),
        "requested_end": str(requested_end.date()),
        "checked_end": str(end.date()),
        "observed_start": str(primary.index[0].date()),
        "observed_end": str(effective_end.date()),
        "verified_start": str(primary.index[0].date()),
        "verified_end": str(effective_end.date()),
        "trading_days": [str(day.date()) for day in primary.index],
        "providers": [primary_provider, "KRX authenticated MDCSTAT00301", kosdaq_provider],
        "fallbacks": [],
        "latest_confirmed_reference": str(latest_reference.date())
        if latest_reference is not None
        else None,
        "fetched_at": now.isoformat(),
        "unverified_tail": str(requested_end.date()) if requested_end > effective_end else None,
    }
    payload["schedule_validation"] = verify_calendar_schedule(payload)
    atomic_json(root / "calendar.json", payload)
    for name, series in [("KOSPI", primary), ("KOSDAQ", kosdaq)]:
        atomic_parquet(
            root / "benchmarks" / f"{name}.parquet",
            series.rename("Close").rename_axis("Date").reset_index(),
        )
    return payload

