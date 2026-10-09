"""Dataset collection and preprocessing using existing provider adapters."""

from __future__ import annotations

import hashlib
import json
import tempfile
import time
from pathlib import Path

import numpy as np
import pandas as pd

from .local_config import (
    append_collection_event,
    atomic_json,
    atomic_parquet,
    identity,
    load_dataset_config,
)
from .local_features import build_feature_frame

VALIDATION_VERSION = 3
PRICE_BASIS = "krx_raw_ohlc_uniform_close_ratio_v1"


def supplement_raw_ohlc(root, code, days, raw, source):
    """Preserve daily snapshots; cache missing KRX OHLC histories separately."""
    fields = ["RawOpen", "RawHigh", "RawLow", "RawClose", "RawVolume", "Amount"]
    if raw is not None and set(fields) <= set(raw):
        return raw
    started = time.monotonic()
    parts = []
    current = days[0]
    # Reuse complete legacy chunks before requesting a full history.
    while current <= days[-1]:
        end = min(current + pd.DateOffset(years=2) - pd.Timedelta(days=1), days[-1])
        path = root / "raw_ohlc_cache" / f"{code}_{current:%Y%m%d}_{end:%Y%m%d}.parquet"
        sidecar = path.with_suffix(".json")
        if path.exists() and sidecar.exists():
            meta = json.loads(sidecar.read_text())
            if meta.get("sha256") == sha256(path):
                parts.append(pd.read_parquet(path).set_index("Date"))
        current = end + pd.Timedelta(days=1)
    cached = pd.concat(parts).sort_index() if parts else pd.DataFrame(columns=fields)
    path = root / "raw_ohlc_cache" / f"{code}_{days[0]:%Y%m%d}_{days[-1]:%Y%m%d}.parquet"
    sidecar = path.with_suffix(".json")
    if path.exists() and sidecar.exists():
        meta = json.loads(sidecar.read_text())
        if meta.get("sha256") == sha256(path):
            cached = pd.read_parquet(path).set_index("Date")
    if not cached.empty and not cached.index.has_duplicates and days.difference(cached.index).empty:
        history = cached.reindex(days)
        provider = "cache"
    else:
        with source._krx_request_timeout():
            history = source.krx.get_market_ohlcv_by_date(
                days[0].strftime("%Y%m%d"), days[-1].strftime("%Y%m%d"), code, adjusted=False
            )
        history = history.rename(columns={
            "시가": "RawOpen", "고가": "RawHigh", "저가": "RawLow",
            "종가": "RawClose", "거래량": "RawVolume", "거래대금": "Amount",
        })
        if history.empty or set(fields) - set(history):
            raise ValueError("Missing KRX raw OHLC history")
        history = history[fields].apply(pd.to_numeric, errors="raise")
        history.index = pd.to_datetime(history.index).normalize()
        if history.index.has_duplicates or len(days.difference(history.index)):
            raise ValueError("Incomplete KRX raw OHLC history dates")
        history = history.reindex(days)
        overlap = cached.index.intersection(days)
        if len(overlap) and not np.allclose(history.loc[overlap, fields], cached.loc[overlap, fields],
                                           rtol=1e-10, atol=1e-12, equal_nan=True):
            raise ValueError("KRX full history disagrees with preserved OHLC chunks")
        provider = "full history"
    if raw is not None:
        for column in set(fields) & set(raw):
            if not np.allclose(history[column], raw[column], rtol=1e-10, atol=1e-12, equal_nan=True):
                raise ValueError(f"KRX OHLC supplement disagrees with preserved {column}")
    if provider != "cache":
        atomic_parquet(path, history.rename_axis("Date").reset_index())
        atomic_json(sidecar, {"sha256": sha256(path), "source": "pykrx KRX adjusted=False"})
    print(f"{code} KRX OHLC: {time.monotonic() - started:.2f}s ({provider}, {len(history)} rows)", flush=True)
    if raw is None:
        return history
    return raw.join(history[[column for column in fields if column not in raw]])


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def validate_index(frame, start, end):
    if frame is None or frame.empty:
        raise ValueError("Empty index response")
    frame = frame.rename(columns={"종가": "Close"}).copy()
    frame.index = pd.to_datetime(frame.index).normalize()
    frame = frame.loc[(frame.index >= start) & (frame.index <= end)]
    if frame.index.has_duplicates or frame.empty or "Close" not in frame:
        raise ValueError("Invalid index dates/columns")
    values = pd.to_numeric(frame.Close, errors="coerce")
    if not np.isfinite(values).all() or values.le(0).any():
        raise ValueError("Invalid index prices")
    return values.sort_index()


def latest_confirmed_market_day(cutoff):
    from data_collectors.price_collector import get_krx_session

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
        from data_collectors.price_collector import krx

        latest = pd.to_datetime(
            krx.get_nearest_business_day_in_a_week(cutoff.strftime("%Y%m%d"), prev=True),
            format="%Y%m%d",
        ).normalize()
        if latest > cutoff:
            raise ValueError("KRX could not establish a completed session before cutoff")
    return latest


def fetch_authenticated_index(start, end):
    """Read KRX's index endpoint using the existing authenticated session."""
    from data_collectors.price_collector import get_krx_session

    session = get_krx_session()
    if session is None:
        raise ValueError("Authenticated KRX session required for direct index verification")
    frames = []
    current = start
    while current <= end:
        chunk_end = min(current + pd.DateOffset(years=2) - pd.Timedelta(days=1), end)
        response = session.post(
            "https://data.krx.co.kr/comm/bldAttendant/getJsonData.cmd",
            data={
                "bld": "dbms/MDC/STAT/standard/MDCSTAT00301",
                "indIdx": "1", "indIdx2": "001",
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
        current = chunk_end + pd.Timedelta(days=1)
    return pd.concat(frames, ignore_index=True).set_index("Date")


# Exchange-calendar rules are independent of the index price response. KRX's
# announced closures missing in exchange_calendars 4.13.2 are explicit exceptions.
# Sources: https://kind.krx.co.kr/external/2026/05/20/000110/20260520000197/32154.htm
# Same holiday schedule across markets: https://regulation.krx.co.kr/contents/RGL/03/03030100/RGL03030100.jsp
CALENDAR_RULES_VERSION = 1
ANNOUNCED_CLOSURES = {"2026-06-03": "Local election", "2026-07-17": "Constitution Day"}


def scheduled_sessions(start, end):
    import exchange_calendars as calendars

    if start < pd.Timestamp("2016-01-01") or end > pd.Timestamp("2026-12-31"):
        raise ValueError("Calendar rules reviewed for 2016..2026 only; review new KRX closures first")
    schedule = calendars.get_calendar("XKRX", start=start, end=end)
    return schedule.sessions.tz_localize(None).difference(
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


def reject_price_revision(root, code, previous, current):
    """Keep a dataset's validated historical prices immutable after collection."""
    columns = ["Open", "High", "Low", "Close", "Volume", "Change", "Amount",
               "RawVolume", "RawClose", "AdjustmentFactor", "VWAP"]
    if set(columns) - set(previous):
        raise ValueError("Existing price basis is unverified; use a new dataset root")
    overlap = current[["Date", *columns]].merge(
        previous[["Date", *columns]], on="Date", suffixes=("_new", "_old"), validate="one_to_one"
    )
    changes = np.column_stack([
        ~np.isclose(overlap[f"{column}_new"].to_numpy(dtype=float),
                    overlap[f"{column}_old"].to_numpy(dtype=float), rtol=1e-10, atol=1e-12,
                    equal_nan=True)
        for column in columns
    ])
    if changes.any():
        revised = overlap.loc[changes.any(axis=1)].copy()
        key = identity(revised.to_json(date_format="iso"))
        destination = root / "price_revisions" / f"{code}_{key}.parquet"
        atomic_parquet(destination, revised)
        atomic_json(destination.with_suffix(".json"), {
            "code": code, "detected_at": pd.Timestamp.now(tz="UTC").isoformat(),
            "changed_columns": [column for column, changed in zip(columns, changes.any(axis=0)) if changed],
            "rows": len(revised), "previous_sha256": sha256(root / "raw" / f"{code}.parquet"),
            "policy": "preserve_existing_prices_use_new_dataset_for_revision",
        })
        raise ValueError(f"Historical prices revised; existing raw preserved. Use a new dataset root; inspect {destination}")


def build_calendar(root, collection):
    from data_collectors import trading_calendar as calendar
    from data_collectors.price_collector import fdr

    start = pd.Timestamp(collection["start_date"])
    # A live session must never enter a historical dataset before its close.
    now = pd.Timestamp.now(tz="Asia/Seoul")
    confirmed_cutoff = now.tz_localize(None).normalize()
    if now.hour < 16:
        confirmed_cutoff -= pd.Timedelta(days=1)
    requested_end = pd.Timestamp(collection.get("end_date") or confirmed_cutoff)
    end = min(requested_end, confirmed_cutoff)
    latest_reference = (
        latest_confirmed_market_day(confirmed_cutoff)
        if collection.get("end_date") is None
        else None
    )
    if latest_reference is not None:
        end = latest_reference
    secondary = validate_index(calendar._fetch_pykrx_index(start, end), start, end)
    fallbacks = []
    primary_provider = "FinanceDataReader KS11"
    try:
        primary = validate_index(calendar._fetch_fdr_index(start, end), start, end)
        if not primary.index.equals(secondary.index):
            raise ValueError("KS11 dates differ from KRX (stale or partial cache)")
        if primary.index[-1] < end - pd.Timedelta(days=7):
            raise ValueError("KS11 does not establish requested boundary coverage")
        if latest_reference is not None and primary.index[-1] != latest_reference:
            raise ValueError("KS11 is older than the latest confirmed KRX session")
    except Exception as exc:
        fallbacks.append({"provider": primary_provider, "reason": str(exc)})
        primary_provider = "KRX authenticated MDCSTAT00301"
        primary = validate_index(
            fetch_authenticated_index(start, end), start, end
        )
    if not primary.index.equals(secondary.index):
        raise ValueError(
            "Calendar providers disagree; no verified coverage: "
            f"only {primary_provider}={primary.index.difference(secondary.index).strftime('%Y-%m-%d').tolist()}, "
            f"only pykrx={secondary.index.difference(primary.index).strftime('%Y-%m-%d').tolist()}"
        )
    if primary.index[0] > start + pd.Timedelta(days=7) or primary.index[-1] < end - pd.Timedelta(
        days=7
    ):
        raise ValueError("Index response does not establish requested boundary coverage")
    effective_end = primary.index[-1]
    if latest_reference is not None and effective_end != latest_reference:
        raise ValueError("Index response is stale relative to KRX latest-session reference")
    kosdaq_provider = "FinanceDataReader KQ11"
    try:
        kosdaq = validate_index(
            fdr.DataReader("KQ11", str(start.date()), str(effective_end.date())),
            start, effective_end,
        )
        if not kosdaq.index.equals(primary.index):
            raise ValueError("KQ11 dates differ from verified KOSPI sessions")
    except Exception as exc:
        fallbacks.append({"provider": kosdaq_provider, "reason": str(exc)})
        kosdaq_provider = "pykrx KOSDAQ 2001"
        from data_collectors.price_collector import krx

        kosdaq = validate_index(
            krx.get_index_ohlcv_by_date(
                start.strftime("%Y%m%d"), effective_end.strftime("%Y%m%d"), "2001"
            ), start, effective_end,
        )
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
        "providers": [primary_provider, "pykrx KOSPI 1001", kosdaq_provider],
        "fallbacks": fallbacks,
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


def fetch_active_listing_intervals(market):
    """Use each security's own KRX listing date, including preferred shares."""
    from data_collectors.price_collector import get_krx_session

    session = get_krx_session()
    if session is None:
        raise ValueError("KRX authenticated session required for listing metadata")
    response = session.post(
        "https://data.krx.co.kr/comm/bldAttendant/getJsonData.cmd",
        data={"bld": "dbms/MDC/STAT/standard/MDCSTAT01901", "mktId": "ALL",
              "share": "1", "csvxls_isNo": "false"},
        timeout=(10, 30),
    )
    response.raise_for_status()
    frame = pd.DataFrame(response.json()["OutBlock_1"]).rename(columns={
        "ISU_SRT_CD": "Code", "ISU_ABBRV": "Name", "MKT_TP_NM": "Market",
        "LIST_DD": "ListingDate", "SECUGRP_NM": "SecurityGroup",
    })
    required = {"Code", "Name", "Market", "ListingDate", "SecurityGroup"}
    if required - set(frame):
        raise ValueError("KRX individual-security metadata lacks required fields")
    # KOSDAQ GLOBAL is a segment of KOSDAQ, not a separate exchange universe.
    frame["Market"] = frame.Market.replace({"KOSDAQ GLOBAL": "KOSDAQ"})
    frame = frame.loc[frame.Market.eq(market) & frame.SecurityGroup.eq("주권")].copy()
    frame["Code"] = frame.Code.astype(str).str.zfill(6)
    frame["ListingDate"] = pd.to_datetime(frame.ListingDate, errors="coerce")
    if frame.empty or frame.Code.duplicated().any() or frame.ListingDate.isna().any():
        raise ValueError(f"{market}: invalid KRX individual-security listing metadata")
    return frame[["Code", "Name", "Market", "ListingDate"]]


def load_metadata(collection, end):
    from data_collectors import price_collector as source

    parts = []
    for market in collection["markets"]:
        active_source = f"{market}-DESC"
        try:
            frame = source.fdr.StockListing(f"{market}-DESC").copy()
            if {"Code", "Name", "ListingDate"} - set(frame) or pd.to_datetime(
                frame.ListingDate, errors="coerce"
            ).isna().any():
                raise ValueError("FDR listing dates incomplete; use KRX individual securities")
        except Exception:
            active_source = "KRX individual securities MDCSTAT01901"
            frame = fetch_active_listing_intervals(market)
        required = {"Code", "Name", "ListingDate"}
        if required - set(frame):
            raise ValueError(f"{market}-DESC lacks verified listing dates")
        frame = frame.assign(
            Market=market, DelistingDate=pd.NaT, IsDelisted=False, Source=active_source
        )
        parts.append(frame)
    if collection["include_delisted"]:
        frame = source._fetch_delisted_list(collection["start_date"])
        frame = frame.loc[frame.Market.isin(collection["markets"]) & frame.SecuGroup.eq("주권")]
        parts.append(
            frame.rename(columns={"Symbol": "Code"}).assign(IsDelisted=True, Source="KRX-DELISTING")
        )
    columns = ["Code", "Name", "Market", "ListingDate", "DelistingDate", "IsDelisted", "Source"]
    metadata = pd.concat([part[columns] for part in parts], ignore_index=True)
    metadata["Code"] = metadata.Code.astype(str).str.zfill(6)
    if collection.get("tickers"):
        metadata = metadata.loc[
            metadata.Code.isin([str(code).zfill(6) for code in collection["tickers"]])
        ].copy()
    metadata["ListingDate"] = pd.to_datetime(metadata.ListingDate, errors="coerce")
    metadata["DelistingDate"] = pd.to_datetime(metadata.DelistingDate, errors="coerce")
    if (
        metadata.ListingDate.isna().any()
        or metadata.loc[metadata.IsDelisted, "DelistingDate"].isna().any()
    ):
        bad = metadata.ListingDate.isna() | (metadata.IsDelisted & metadata.DelistingDate.isna())
        details = metadata.loc[bad, ["Code", "Name", "Market", "Source"]].head(20).to_dict("records")
        raise ValueError(f"Unknown listing interval for {int(bad.sum())} securities: {details}")
    metadata = metadata.loc[
        (metadata.ListingDate <= pd.Timestamp(end))
        & (
            metadata.DelistingDate.isna()
            | (metadata.DelistingDate > pd.Timestamp(collection["start_date"]))
        )
    ]
    if tickers := collection.get("tickers"):
        metadata = metadata.loc[metadata.Code.isin([str(code).zfill(6) for code in tickers])]
        if set(str(code).zfill(6) for code in tickers) - set(metadata.Code):
            raise ValueError("Requested ticker lacks verified metadata")
    metadata = metadata.drop_duplicates(["Code", "ListingDate", "DelistingDate"]).sort_values(
        ["Code", "ListingDate"]
    )
    for code, intervals in metadata.groupby("Code"):
        previous_end = None
        for i, row in enumerate(intervals.itertuples()):
            if i and (pd.isna(previous_end) or row.ListingDate < previous_end):
                raise ValueError(f"Overlapping listing intervals: {code}")
            previous_end = row.DelistingDate
    if metadata.empty:
        raise ValueError("Empty metadata")
    metadata["MarketHistoryVerified"] = False
    return metadata


def expected_sessions(intervals, calendar):
    days = pd.DatetimeIndex(pd.to_datetime(calendar["trading_days"]))
    expected = pd.DatetimeIndex([])
    for row in intervals.itertuples():
        active = days >= row.ListingDate
        if pd.notna(row.DelistingDate):
            active &= days < row.DelistingDate
        expected = expected.union(days[active])
    return expected.sort_values()


def validate_prices(frame, expected):
    if "Date" not in frame:
        raise ValueError("Missing Date")
    frame = frame.copy()
    frame["Date"] = pd.to_datetime(frame.Date).dt.normalize()
    if frame.Date.duplicated().any() or not pd.DatetimeIndex(frame.Date).sort_values().equals(
        expected
    ):
        missing = expected.difference(pd.DatetimeIndex(frame.Date))
        raise ValueError(f"Price coverage mismatch; missing {missing[:5].tolist()}")
    required = [
        "Open",
        "High",
        "Low",
        "Close",
        "Volume",
        "Amount",
        "RawVolume",
        "RawClose",
        "RawOpen", "RawHigh", "RawLow",
        "AdjustmentFactor",
        "VWAP",
    ]
    if set(required) - set(frame):
        raise ValueError("Missing OHLC/VWAP source fields")
    frame[required] = frame[required].apply(pd.to_numeric, errors="coerce")
    if (
        not np.isfinite(frame[["Volume", "RawVolume", "Amount"]].to_numpy()).all()
        or frame[["Volume", "RawVolume", "Amount"]].lt(0).any().any()
    ):
        raise ValueError("Invalid volume/amount")
    traded = frame.Volume.gt(0)
    if not np.array_equal(frame.Volume.to_numpy(), frame.RawVolume.to_numpy()):
        raise ValueError("Volume disagrees with KRX RawVolume")
    unavailable = frame[["RawOpen", "RawHigh", "RawLow"]].eq(0).all(axis=1)
    regular = traded & ~unavailable
    turnover_fields = ["Close", "RawClose", "Volume", "RawVolume", "Amount", "AdjustmentFactor", "VWAP"]
    values = frame.loc[traded, turnover_fields].to_numpy(dtype=float)
    if not np.isfinite(values).all() or (values <= 0).any():
        raise ValueError("Non-positive/non-finite traded prices or VWAP source")
    values = frame.loc[regular, required].to_numpy(dtype=float)
    if not np.isfinite(values).all() or (values <= 0).any():
        raise ValueError("Non-positive/non-finite regular-session OHLC")
    row = frame.loc[regular]
    if (
        (row.Low > row[["Open", "Close"]].min(axis=1)).any()
        or (row.High < row[["Open", "Close"]].max(axis=1)).any()
        or (row.Low > row.High).any()
    ):
        raise ValueError("OHLC relationship invalid")
    row = frame.loc[traded]
    calculated = row.Amount / row.RawVolume * row.AdjustmentFactor
    if not np.allclose(row.VWAP, calculated, rtol=1e-8) or not np.allclose(
        row.AdjustmentFactor, row.Close / row.RawClose, rtol=1e-8
    ):
        raise ValueError("VWAP adjustment mismatch")
    for column in ("Open", "High", "Low", "Close"):
        if not np.allclose(row[column], row[f"Raw{column}"] * row.AdjustmentFactor, rtol=1e-10):
            raise ValueError("OHLC uniform adjustment mismatch")
    frame["RegularSessionUnavailable"] = unavailable
    frame["VWAPOutsideDailyRange"] = regular & ((frame.VWAP < frame.Low) | (frame.VWAP > frame.High))
    frame["VWAPScope"] = "KRX_amount_volume_scope_unverified"
    frame["PriceBasis"] = PRICE_BASIS
    halt = ~traded
    if (frame.loc[halt, ["RawVolume", "Amount"]] != 0).any().any():
        raise ValueError("Zero-volume row has inconsistent source amount")
    frame["Trading_Halt"] = halt.astype("int8")
    return frame.sort_values("Date").reset_index(drop=True)


def validate_flow(frame, day, columns):
    required = {"Date", "Code", *columns}
    if frame.empty or required - set(frame):
        raise ValueError("Incomplete flow cache schema")
    dates = pd.to_datetime(frame.Date).dt.normalize()
    if (
        not dates.eq(day).all()
        or frame.Code.duplicated().any()
        or not frame.Code.astype(str).str.fullmatch(r"[0-9A-Z]{6}").all()
    ):
        raise ValueError("Invalid flow cache date/code/duplicates")
    values = frame[columns].apply(pd.to_numeric, errors="coerce")
    # A partial investor response remains missing; never manufacture zero.
    if ((frame[columns].notna() & values.isna()).any().any()
            or np.isinf(values.to_numpy(dtype=float, na_value=np.nan)).any()
            or values.lt(0).any().any()):
        raise ValueError("Invalid flow values")
    frame = frame.copy()
    frame[columns] = values
    return frame


def flow_coverage(root, investors, columns, market_days):
    """Missing ranking rows are unknown observations, never inferred zero trades."""
    from experiments.features.flow import build_flow_features

    coverage = []
    for path in sorted((root / "raw").glob("*.parquet")):
        frame = pd.read_parquet(path)
        features = build_flow_features(frame, market_days)
        for investor in investors:
            fields = [col for col in columns if col.startswith(investor + "_")]
            values = frame.reindex(columns=fields)
            complete = values.notna().all(axis=1)
            absent = values.isna().all(axis=1)
            traded = frame.RawVolume.gt(0)
            coverage.append({
                "code": path.stem, "investor": investor,
                "complete_rows": int(complete.sum()), "total_rows": len(frame),
                "missing_dates": frame.loc[~complete, "Date"].astype(str).tolist(),
                "not_returned_rows": int(absent.sum()),
                "partial_rows": int((~complete & ~absent).sum()),
                "missing_traded_rows": int((~complete & traded).sum()),
                "missing_zero_volume_rows": int((~complete & ~traded).sum()),
                "amount_window_coverage": {
                    str(window): {
                        "complete_rows": int(features[f"flow_{investor.lower()}_{window}"].notna().sum()),
                        "excluded_rows": int(features[f"flow_{investor.lower()}_{window}"].isna().sum()),
                    } for window in (1, 5, 20)
                },
            })
    return coverage


def verify_cached_flows(config_path):
    """Audit existing flow caches independently of unfinished price collection."""
    from data_collectors import price_collector as source

    config = load_dataset_config(config_path)
    root = Path(config["root"])
    calendar = json.loads((root / "calendar.json").read_text())
    failures, verified = [], 0
    for day in pd.to_datetime(calendar["trading_days"]):
        cache = root / "investor_flow_cache" / f"{day:%Y-%m-%d}.parquet"
        try:
            meta = json.loads(cache.with_suffix(".json").read_text())
            if meta.get("validation_version") != VALIDATION_VERSION or meta.get("sha256") != sha256(cache):
                raise ValueError("Unverified flow cache hash/version")
            validate_flow(pd.read_parquet(cache), day, source._FLOW_COLUMNS)
            verified += 1
        except (ValueError, OSError) as exc:
            failures.append({"date": str(day.date()), "reason": str(exc)})
        if (verified + len(failures)) % 250 == 0:
            print(f"Flow caches checked: {verified + len(failures)}/{len(calendar['trading_days'])}", flush=True)
    coverage = flow_coverage(root, source._INVESTORS, source._FLOW_COLUMNS, calendar["trading_days"])
    summary = {}
    for investor in source._INVESTORS:
        rows = [row for row in coverage if row["investor"] == investor]
        summary[investor] = {
            key: sum(row[key] for row in rows) for key in (
                "complete_rows", "total_rows", "not_returned_rows", "partial_rows",
                "missing_traded_rows", "missing_zero_volume_rows",
            )
        }
        summary[investor]["amount_window_coverage"] = {
            str(window): {key: sum(row["amount_window_coverage"][str(window)][key] for row in rows)
                          for key in ("complete_rows", "excluded_rows")}
            for window in (1, 5, 20)
        }
    report = {
        "flow_queries_complete": not failures,
        "verified_days": verified, "total_days": len(calendar["trading_days"]),
        "cache_failures": failures, "raw_stock_count": len(coverage) // len(source._INVESTORS),
        "flows_complete": bool(coverage) and not failures
        and all(row["complete_rows"] == row["total_rows"] for row in coverage),
        "summary": summary, "coverage": coverage,
        "missing_policy": "preserve_unknown_ranking_rows; use_complete_selected_amount_windows_only",
        "coverage_scope": "existing_raw_stocks_only; unfinished_price_stocks_not_included",
    }
    atomic_json(root / "flow_validation_report.json", report)
    print(f"Flow query cache verification: {verified}/{report['total_days']}; full coverage: {report['flows_complete']}")
    if failures:
        raise RuntimeError(f"Flow cache verification failed; inspect {root / 'flow_validation_report.json'}")
    return report


def collect_dataset(config_path, *, mode="full", rebuild=False):
    from data_collectors import price_collector as source

    config = load_dataset_config(config_path)
    root = Path(config["root"])
    if rebuild and mode != "full":
        raise ValueError("--rebuild requires full")
    if rebuild and root.exists() and any(root.iterdir()):
        raise FileExistsError("--rebuild requires a new dataset root; preserve existing data")
    root.mkdir(parents=True, exist_ok=True)
    append_collection_event(root, {"state": "started", "stage": "collection", "mode": mode})
    manifest_path = root / "dataset_manifest.json"
    manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() else None
    collection_identity = identity(config["collection"])
    if manifest and manifest["collection_identity"] != collection_identity:
        raise ValueError("Collection settings changed; use a new dataset root")
    # End date is immutable inside a build, including resumed and update executions.
    calendar_path = root / "calendar.json"
    atomic_json(root / "collection_report.json", {"status": "running", "stage": "calendar"})
    try:
        if calendar_path.exists():
            calendar = json.loads(calendar_path.read_text())
            if "checked_end" not in calendar:
                # Legacy caches never verified the unobserved tail. Check it too.
                calendar["checked_end"] = calendar["requested_end"]
            calendar["schedule_validation"] = verify_calendar_schedule(calendar)
            atomic_json(calendar_path, calendar)
        else:
            calendar = build_calendar(root, config["collection"])
    except Exception as exc:
        append_collection_event(root, {"state": "failed", "stage": "calendar",
                                       "exception_type": type(exc).__name__, "reason": str(exc)})
        atomic_json(
            root / "collection_report.json",
            {"status": "failed", "stage": "calendar", "reason": str(exc)},
        )
        raise
    if calendar.get("validation_version") != VALIDATION_VERSION:
        raise ValueError("Legacy/unverified calendar; use a new dataset root")
    metadata_path = root / "ticker_metadata.csv"
    atomic_json(root / "collection_report.json", {"status": "running", "stage": "metadata"})
    if metadata_path.exists():
        metadata = pd.read_csv(
            metadata_path, dtype={"Code": str}, parse_dates=["ListingDate", "DelistingDate"]
        )
    else:
        try:
            metadata = load_metadata(config["collection"], calendar["observed_end"])
            metadata.to_csv(metadata_path, index=False)
        except Exception as exc:
            append_collection_event(root, {"state": "failed", "stage": "metadata",
                                           "exception_type": type(exc).__name__, "reason": str(exc)})
            atomic_json(
                root / "collection_report.json",
                {"status": "failed", "stage": "metadata", "reason": str(exc)},
            )
            raise
    from .bulk_prices import prepare_bulk_prices, stock_raw

    report = {"prices": [], "flow_failures": [], "market_history_verified": False}
    bulk = prepare_bulk_prices(root, metadata, calendar, mode, report, source)
    atomic_json(root / "collection_report.json", {"status": "running", "stage": "prices"})
    for code, intervals in metadata.groupby("Code", sort=True):
        path = root / "raw" / f"{code}.parquet"
        expected = expected_sessions(intervals, calendar)
        if expected.empty:
            continue
        try:
            previous = pd.read_parquet(path) if path.exists() else None
            changed_price_rows = 0
            if mode == "full" and previous is not None:
                try:
                    verified_previous = validate_prices(previous, expected)
                    report["prices"].append(
                        {"code": code, "status": "verified_resume", "rows": len(previous),
                         "regular_session_unavailable_dates": verified_previous.loc[verified_previous.RegularSessionUnavailable & verified_previous.RawVolume.gt(0), "Date"].dt.strftime("%Y-%m-%d").tolist(),
                         "vwap_outside_range_rows": int(verified_previous.VWAPOutsideDailyRange.sum()),
                         "vwap_outside_range_dates": verified_previous.loc[verified_previous.VWAPOutsideDailyRange, "Date"].dt.strftime("%Y-%m-%d").tolist()}
                    )
                    atomic_json(root / "collection_report.json", {
                        **report, "status": "running", "stage": "prices",
                    })
                    continue
                except ValueError:
                    pass
                if "RawOpen" not in previous:
                    preserved = previous.set_index("Date")
                    raw_window = stock_raw(bulk, code, expected) if bulk is not None else None
                    if raw_window is None:
                        raw_window = supplement_raw_ohlc(root, code, expected,
                            preserved[["RawClose", "RawVolume", "Amount"]], source)
                    for column in ("RawClose", "RawVolume", "Amount"):
                        if not np.allclose(raw_window[column], preserved[column],
                                           rtol=1e-10, atol=1e-12, equal_nan=True):
                            raise ValueError(f"Daily OHLC supplement disagrees with preserved {column}")
                    upgraded = source._attach_actual_vwap(preserved, raw_window).rename_axis("Date").reset_index()
                    upgraded = validate_prices(upgraded, expected)
                    backup = root / "price_basis_backups" / f"{code}_{sha256(path)}.parquet"
                    if not backup.exists():
                        atomic_parquet(backup, previous)
                    atomic_parquet(path, upgraded)
                    report["prices"].append({"code": code, "status": "verified_basis_upgrade",
                        "rows": len(upgraded), "backup": str(backup),
                        "regular_session_unavailable_dates": upgraded.loc[upgraded.RegularSessionUnavailable & upgraded.RawVolume.gt(0), "Date"].dt.strftime("%Y-%m-%d").tolist(),
                        "vwap_outside_range_rows": int(upgraded.VWAPOutsideDailyRange.sum()),
                        "vwap_outside_range_dates": upgraded.loc[upgraded.VWAPOutsideDailyRange, "Date"].dt.strftime("%Y-%m-%d").tolist()})
                    continue
            parts = []
            providers = []
            for row in intervals.itertuples():
                days = expected[
                    (expected >= row.ListingDate)
                    & (expected < row.DelistingDate if pd.notna(row.DelistingDate) else True)
                ]
                if days.empty:
                    continue
                args = (code, str(days.min().date()), str(days.max().date()))
                raw_window = stock_raw(bulk, code, days) if bulk is not None else None
                raw_window = supplement_raw_ohlc(root, code, days, raw_window, source)
                fetched = None
                failures = []
                adapters = (
                    [("pykrx", source._fetch_delisted_pykrx)]
                    if row.IsDelisted
                    else [("fdr", source._fetch_ohlcv_fdr), ("pykrx", source._fetch_ohlcv_pykrx)]
                )
                for provider, adapter in adapters:
                    try:
                        if bulk is None:
                            candidate = adapter(*args, raw_df=raw_window)
                        else:
                            # pykrx omits default HTTP timeouts; bound both cached-raw
                            # adjusted calls and the individual raw fallback.
                            for attempt in range(1, 4):
                                try:
                                    with source._krx_request_timeout():
                                        candidate = (adapter(*args, raw_df=raw_window)
                                                     if raw_window is not None else adapter(*args))
                                    if candidate is None or candidate.empty:
                                        raise ValueError("Empty provider response")
                                    break
                                except Exception as exc:
                                    append_collection_event(root, {
                                        "state": "request_failed", "stage": "prices", "code": code,
                                        "provider": provider, "attempt": attempt, "start_date": args[1],
                                        "end_date": args[2], "exception_type": type(exc).__name__,
                                        "reason": str(exc), **getattr(exc, "details", {}),
                                    })
                                    if attempt == 3:
                                        raise
                                    source.time.sleep(attempt)
                        if candidate is None or candidate.empty:
                            raise ValueError("Empty provider response")
                        candidate = candidate.rename_axis("Date").reset_index()
                        candidate = candidate.loc[pd.to_datetime(candidate.Date).isin(days)]
                        candidate = validate_prices(candidate, days)
                        fetched = candidate.assign(
                            Code=code,
                            Name=row.Name,
                            IsDelisted=row.IsDelisted,
                            PriceProvider=provider,
                        )
                        providers.append(provider)
                        break
                    except Exception as exc:
                        failures.append(str(exc))
                if fetched is None:
                    raise ValueError("; ".join(failures))
                parts.append(fetched)
            frame = validate_prices(pd.concat(parts, ignore_index=True), expected)
            if previous is not None:
                reject_price_revision(root, code, previous, frame)
                if "PriceProvider" not in previous:
                    raise ValueError("Existing price basis is unverified; use new dataset")
                overlap = frame.merge(previous, on="Date", suffixes=("_new", "_old"))
                changed_price_rows = int(
                    (~np.isclose(overlap.Close_new, overlap.Close_old, rtol=1e-8)).sum()
                )
                changed_provider = overlap.PriceProvider_new != overlap.PriceProvider_old
                if changed_provider.any() and not np.allclose(
                    overlap.loc[changed_provider, "Close_new"],
                    overlap.loc[changed_provider, "Close_old"],
                    rtol=1e-5,
                ):
                    raise ValueError("Provider price basis mismatch")
                flows = [col for col in source._FLOW_COLUMNS if col in previous]
                if flows:
                    frame = frame.merge(
                        previous[["Date", *flows]], on="Date", how="left", validate="one_to_one"
                    )
            atomic_parquet(path, frame)
            report["prices"].append(
                {
                    "code": code,
                    "status": "verified",
                    "rows": len(frame),
                    "providers": providers,
                    "changed_price_rows": changed_price_rows,
                    "regular_session_unavailable_dates": frame.loc[frame.RegularSessionUnavailable & frame.RawVolume.gt(0), "Date"].dt.strftime("%Y-%m-%d").tolist(),
                    "vwap_outside_range_rows": int(frame.VWAPOutsideDailyRange.sum()),
                    "vwap_outside_range_dates": frame.loc[frame.VWAPOutsideDailyRange, "Date"].dt.strftime("%Y-%m-%d").tolist(),
                }
            )
        except KeyboardInterrupt:
            report["status"] = "interrupted"
            raise
        except Exception as exc:
            append_collection_event(root, {"state": "failed", "stage": "prices", "code": code,
                                           "exception_type": type(exc).__name__, "reason": str(exc)})
            report["prices"].append({"code": code, "status": "failed", "reason": str(exc)})
        finally:
            atomic_json(root / "collection_report.json", {
                **report, "status": report.get("status", "running"), "stage": "prices",
                "price_stock_progress": {"completed_stocks": len(report["prices"]),
                                         "total_stocks": metadata.Code.nunique(), "code": code},
            })
    # Price completion is durable before slow flow requests. Interrupted flow collection
    # must not make independently verified prices unusable for the base experiment.
    price_failed = any(item["status"] == "failed" for item in report["prices"])
    checkpoint_files = {
        path.name: sha256(path) for path in sorted((root / "raw").glob("*.parquet"))
    }
    checkpoint = {
        "contract_version": VALIDATION_VERSION,
        "config": config,
        "dataset_id": config["dataset_id"],
        "collection_identity": collection_identity,
        "price_policy": "krx_raw_ohlc_uniform_close_ratio_snapshot_not_point_in_time_archive",
        "end_date": calendar["observed_end"],
        "raw_files": checkpoint_files,
        "prices_complete": not price_failed,
        "flows_complete": False,
        "flow_queries_complete": False,
        "price_basis": PRICE_BASIS,
    }
    atomic_json(manifest_path, checkpoint)
    atomic_json(
        root / "collection_report.json",
        {
            **report,
            "status": "running",
            "stage": "flows" if config["collection"]["investor_flows"] else "validation",
        },
    )
    if config["collection"]["investor_flows"]:
        parts = []
        staging = tempfile.TemporaryDirectory(prefix="flow_merge_", dir=root)
        batch = 0
        raw_paths = sorted((root / "raw").glob("*.parquet"))
        raw_codes = {path.stem for path in raw_paths}
        collected_days = []

        def stage_flow_parts():
            nonlocal batch
            if not parts:
                return
            combined = pd.concat(parts, ignore_index=True)
            collected_days.extend(pd.to_datetime(combined.Date.unique()))
            combined = combined.loc[combined.Code.isin(raw_codes)]
            for code, rows in combined.groupby("Code", sort=False):
                atomic_parquet(Path(staging.name) / str(code) / f"{batch}.parquet", rows)
            batch += 1
            parts.clear()

        def merge_staged_flows():
            days = pd.DatetimeIndex(collected_days).unique()
            if days.empty:
                return
            checkpoint["raw_files"] = dict(checkpoint["raw_files"])
            for index, path in enumerate(raw_paths, 1):
                raw = pd.read_parquet(path)
                raw["Date"] = pd.to_datetime(raw.Date)
                for column in source._FLOW_COLUMNS:
                    if column not in raw:
                        raw[column] = np.nan
                mask = raw.Date.isin(days)
                pieces = list((Path(staging.name) / path.stem).glob("*.parquet"))
                if pieces:
                    values = pd.concat([pd.read_parquet(piece) for piece in pieces]).set_index("Date")
                    raw.loc[mask, source._FLOW_COLUMNS] = values.reindex(raw.loc[mask, "Date"])[
                        source._FLOW_COLUMNS
                    ].to_numpy(dtype=float, na_value=np.nan)
                else:
                    raw.loc[mask, source._FLOW_COLUMNS] = np.nan
                atomic_parquet(path, raw)
                checkpoint["raw_files"][path.name] = sha256(path)
                atomic_json(manifest_path, checkpoint)
                if index % 100 == 0 or index == len(raw_paths):
                    print(f"Flow merge stocks: {index}/{len(raw_paths)}", flush=True)
            staging.cleanup()

        progress = {"completed_days": 0, "cached_days": 0, "total_days": len(calendar["trading_days"])}

        def record_flow(event):
            progress.update(event)
            if event.get("state") in {"request_failed", "failed"}:
                append_collection_event(root, {**progress, "stage": "flows", "provider": "KRX investor flows"})
            atomic_json(root / "collection_report.json", {
                **report, "status": "running", "stage": "flows", "flow_progress": progress,
            })

        for day in pd.to_datetime(calendar["trading_days"]):
            record_flow({"date": str(day.date()), "state": "checking_cache"})
            cache = root / "investor_flow_cache" / f"{day:%Y-%m-%d}.parquet"
            version = cache.with_suffix(".json")
            try:
                flow = None
                if cache.exists() and version.exists():
                    try:
                        meta = json.loads(version.read_text())
                        if meta.get("validation_version") == VALIDATION_VERSION and meta.get(
                            "sha256"
                        ) == sha256(cache):
                            flow = validate_flow(pd.read_parquet(cache), day, source._FLOW_COLUMNS)
                    except (ValueError, OSError):
                        pass
                if flow is None:
                    flow = validate_flow(
                        source._fetch_investor_day(day, progress=record_flow), day, source._FLOW_COLUMNS
                    )
                    atomic_parquet(cache, flow)
                    atomic_json(
                        version, {"validation_version": VALIDATION_VERSION, "sha256": sha256(cache)}
                    )
                else:
                    progress["cached_days"] += 1
                parts.append(flow)
                progress["completed_days"] += 1
                record_flow({"state": "complete"})
                if len(parts) >= 250:
                    stage_flow_parts()
            except KeyboardInterrupt:
                atomic_json(root / "collection_report.json", {
                    **report, "status": "interrupted", "stage": "flows", "flow_progress": progress,
                })
                raise
            except Exception as exc:
                report["flow_failures"].append({"date": str(day.date()), "reason": str(exc)})
                record_flow({"state": "failed", "reason": str(exc), "exception_type": type(exc).__name__})
        stage_flow_parts()
        merge_staged_flows()
        report["flow_progress"] = progress
    files = {path.name: sha256(path) for path in sorted((root / "raw").glob("*.parquet"))}
    coverage = flow_coverage(root, source._INVESTORS, source._FLOW_COLUMNS, calendar["trading_days"])
    report["flow_coverage"] = coverage
    failed = any(item["status"] == "failed" for item in report["prices"])
    manifest = {
        "contract_version": VALIDATION_VERSION,
        "config": config,
        "dataset_id": config["dataset_id"],
        "collection_identity": collection_identity,
        "price_policy": "krx_raw_ohlc_uniform_close_ratio_snapshot_not_point_in_time_archive",
        "end_date": calendar["observed_end"],
        "raw_files": files,
        "prices_complete": not failed,
        "price_basis": PRICE_BASIS,
        "flow_queries_complete": bool(config["collection"]["investor_flows"])
        and not report["flow_failures"]
        and report.get("flow_progress", {}).get("completed_days") == len(calendar["trading_days"]),
        "flows_complete": not report["flow_failures"]
        and all(item["complete_rows"] == item["total_rows"] for item in coverage),
    }
    atomic_json(manifest_path, manifest)
    report["prices_complete"] = manifest["prices_complete"]
    report["flow_queries_complete"] = manifest["flow_queries_complete"]
    report["flows_complete"] = manifest["flows_complete"]
    report["status"] = (
        "failed"
        if failed
        else "complete"
    )
    atomic_json(root / "collection_report.json", report)
    if failed:
        raise RuntimeError(f"Dataset incomplete; inspect {root / 'collection_report.json'}")
    print(f"Verified dataset: {root}; frozen end: {calendar['observed_end']}")


def preprocess_dataset(config_path, *, rebuild=False, allow_partial=False):
    config = load_dataset_config(config_path)
    root = Path(config["root"])
    manifest_path = root / "dataset_manifest.json"
    if not manifest_path.exists():
        raise FileNotFoundError("Run price_collector.py --config first")
    manifest = json.loads(manifest_path.read_text())
    if not manifest.get("prices_complete") and not allow_partial:
        raise ValueError("Price collection incomplete; resume collection first")
    calendar = json.loads((root / "calendar.json").read_text())
    if calendar.get("validation_version") != VALIDATION_VERSION:
        raise ValueError("Unverified calendar")
    metadata = pd.read_csv(
        root / "ticker_metadata.csv",
        dtype={"Code": str},
        parse_dates=["ListingDate", "DelistingDate"],
    )
    reports = []
    outputs = {}
    for path in sorted((root / "raw").glob("*.parquet")):
        try:
            raw_hash = sha256(path)
            if manifest["raw_files"].get(path.name) != raw_hash:
                raise ValueError("Raw changed outside collection; run update to revalidate")
            raw = pd.read_parquet(path)
            intervals = metadata.loc[metadata.Code.eq(path.stem)]
            raw = validate_prices(raw, expected_sessions(intervals, calendar))
            pieces = []
            for row in intervals.itertuples():
                dates = pd.to_datetime(raw.Date)
                active = dates >= row.ListingDate
                if pd.notna(row.DelistingDate):
                    active &= dates < row.DelistingDate
                subset = raw.loc[active].copy()
                if subset.empty:
                    continue
                pieces.append(
                    build_feature_frame(
                        subset, pd.to_datetime(calendar["trading_days"]), config["preprocessing"]
                    )
                )
            frame = pd.concat(pieces, ignore_index=True)
            from experiments.features.registry import BASE_FEATURES

            missing = frame[list(BASE_FEATURES)].isna()
            reports.append(
                {
                    "file": path.name,
                    "rows": len(frame),
                    "warmup_rows": int(frame.roc_60.isna().sum()),
                    "missing_by_feature": missing.sum().to_dict(),
                    "status": "verified",
                }
            )
            destination = root / "processed" / path.name
            atomic_parquet(destination, frame)
            outputs[path.name] = sha256(destination)
        except Exception as exc:
            reports.append({"file": path.name, "status": "failed", "reason": str(exc)})
    atomic_json(root / "preprocessing_report.json", reports)
    failed = sum(row["status"] == "failed" for row in reports)
    if (failed and not allow_partial) or not outputs:
        raise RuntimeError(
            f"Preprocessing incomplete; inspect {root / 'preprocessing_report.json'}"
        )
    atomic_json(
        root / "processed_manifest.json",
        {
            "contract_version": VALIDATION_VERSION,
            "settings": config["preprocessing"],
            "raw_files": (
                {name: manifest["raw_files"][name] for name in outputs}
                if allow_partial else manifest["raw_files"]
            ),
            "allow_partial": allow_partial,
            "files": outputs,
            "implementation_sha256": sha256(Path(__file__).with_name("local_features.py")),
        },
    )
    print(f"Processed {len(outputs)} files; retained warmup and full price paths")
    if allow_partial:
        print(f"Partial collection allowed; excluded {failed} files; see preprocessing_report.json")


def validate_processed_inputs(config):
    root = Path(config["root"])
    path = root / "processed_manifest.json"
    if not path.exists():
        raise FileNotFoundError("Run preprocess_data.py --config first")
    processed = json.loads(path.read_text())
    dataset = json.loads((root / "dataset_manifest.json").read_text())
    if (
        (not dataset.get("prices_complete") and not processed.get("allow_partial"))
        or processed.get("contract_version") != VALIDATION_VERSION
    ):
        raise ValueError("Dataset/processed not verified; collect and preprocess first")
    expected_raw = dataset["raw_files"]
    if processed.get("allow_partial"):
        expected_raw = {name: expected_raw.get(name) for name in processed["raw_files"]}
    if processed["settings"] != config["preprocessing"] or processed["raw_files"] != expected_raw:
        raise ValueError("Dataset changed; rerun preprocessing before preparing features")
    if processed["implementation_sha256"] != sha256(Path(__file__).with_name("local_features.py")):
        raise ValueError("Feature implementation changed; rerun preprocessing")
    for directory, fingerprints in (
        ("raw", processed["raw_files"]),
        ("processed", processed["files"]),
    ):
        for name, digest in fingerprints.items():
            source = root / directory / name
            if not source.exists() or sha256(source) != digest:
                raise ValueError(
                    f"Modified/missing {directory} input: {name}; revalidate collection/preprocessing"
                )
    return processed
