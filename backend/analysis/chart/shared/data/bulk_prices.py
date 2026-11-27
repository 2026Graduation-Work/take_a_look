"""Bounded daily KRX price snapshots shared by all local stock collectors."""

import json
import time

import numpy as np
import pandas as pd

from shared.io import append_collection_event, atomic_json, atomic_parquet

from .training_prices import parse_krx_fields
from .validation import KRX_RAW_COLUMNS, expected_sessions

CACHE_VERSION = 2


def validate_day(frame, day):
    required = ["Code", *KRX_RAW_COLUMNS]
    if frame.empty or set(required) - set(frame):
        raise ValueError("Empty/incomplete daily KRX price response")
    frame = frame[required].copy()
    frame["Date"] = pd.to_datetime(frame.Date).dt.normalize()
    frame["Code"] = frame.Code.astype(str)
    if (not frame.Date.eq(day).all() or frame.Code.duplicated().any()
            or not frame.Code.str.fullmatch(r"[0-9A-Z]{6}").all()):
        raise ValueError("Invalid daily KRX dates/codes/duplicates")
    values = frame[KRX_RAW_COLUMNS[1:]].apply(pd.to_numeric, errors="raise")
    if not np.isfinite(values.to_numpy()).all() or values.drop(columns="RawChange").lt(0).any().any():
        raise ValueError("Invalid daily KRX raw prices/volume/amount")
    frame[values.columns] = values
    return frame


def request_day(day):
    from pykrx.website.krx.market.core import 전종목시세

    rows = 전종목시세().fetch(day.strftime("%Y%m%d"), "ALL")
    return parse_krx_fields(rows).rename(columns={"ISU_SRT_CD": "Code"}).assign(Date=day)


def fetch_day(source, day, record):
    for attempt in range(1, 4):
        record({"date": str(day.date()), "attempt": attempt, "state": "requesting"})
        started = time.monotonic()
        try:
            with source._krx_request_timeout():
                return validate_day(request_day(day), day)
        except Exception as exc:
            response = getattr(exc, "response", None)
            details = getattr(exc, "details", {})
            if response is not None:
                details = {**details, "http_status": response.status_code,
                           "content_type": response.headers.get("Content-Type", "unknown")}
            record({"state": "request_failed", "reason": str(exc),
                    "exception_type": type(exc).__name__, "elapsed_seconds": round(time.monotonic() - started, 3),
                    **details})
            if attempt == 3:
                raise
            delay = 5 if attempt == 1 else 15
            record({"state": "retry_wait", "retry_seconds": delay})
            time.sleep(delay)


def prepare_bulk_prices(root, metadata, calendar, report, source):
    """Skip saved stocks; amortize daily requests only when cheaper than histories."""
    from shared.io import sha256

    needed = {}
    for code, intervals in metadata.groupby("Code", sort=True):
        days = expected_sessions(intervals, calendar)
        if days.empty or (root / "krx_raw_prices" / f"{code}.parquet").exists():
            continue
        needed[code] = days
    if not needed:
        return None
    days = pd.DatetimeIndex(np.unique(np.concatenate([d.values for d in needed.values()])))
    cache_root = root / "krx_price_day_cache"
    estimated_history_requests = sum(max(1, int((d[-1] - d[0]).days / 731) + 1) for d in needed.values())
    if estimated_history_requests <= len(days) and not cache_root.exists():
        print(f"Price source: individual histories ({len(needed)} pending stocks)", flush=True)
        return None
    progress = {"total_days": len(days), "completed_days": 0, "cached_days": 0,
                "pending_stocks": len(needed)}
    report["bulk_price_failures"] = []
    started = time.monotonic()
    consecutive_failures = 0

    def record(event):
        if event.get("state") in {"requesting", "checking_cache"}:
            for field in ("reason", "exception_type", "http_status", "content_type", "response_bytes", "response_kind", "elapsed_seconds"):
                progress.pop(field, None)
        progress.update(event)
        report["price_day_progress"] = progress
        if event.get("state") in {"request_failed", "retry_wait", "failed"}:
            append_collection_event(root, {**progress, "stage": "price_days", "provider": "KRX daily ALL"})
        atomic_json(root / "collection_report.json", {
            **report, "status": "running", "stage": "price_days",
        })

    frames = []
    print(f"Price source: daily ALL snapshots ({len(days)} days, {len(needed)} pending stocks)", flush=True)
    for day in days:
        cache = cache_root / f"{day:%Y-%m-%d}.parquet"
        sidecar = cache.with_suffix(".json")
        tick = time.monotonic()
        record({"date": str(day.date()), "state": "checking_cache"})
        try:
            frame = None
            if cache.exists() and sidecar.exists():
                try:
                    meta = json.loads(sidecar.read_text())
                    if meta.get("version") == CACHE_VERSION and meta.get("sha256") == sha256(cache):
                        frame = validate_day(pd.read_parquet(cache), day)
                except Exception:
                    pass
            cached = frame is not None
            if frame is None:
                frame = fetch_day(source, day, record)
                atomic_parquet(cache, frame)
                atomic_json(sidecar, {"version": CACHE_VERSION, "sha256": sha256(cache),
                                      "date": str(day.date()), "rows": len(frame),
                                      "source": "KRX MDCSTAT01501 daily ALL"})
            if not cached:
                time.sleep(max(0, 1.0 - (time.monotonic() - tick)))
            selected = frame.loc[frame.Code.isin(needed)].copy()
            selected["Code"] = selected.Code.astype("string[pyarrow]")
            frames.append(selected)
            consecutive_failures = 0
            progress["consecutive_failures"] = 0
            progress["completed_days"] += 1
            progress["cached_days"] += int(cached)
            record({"state": "cached" if cached else "verified", "rows": len(frame),
                    "request_seconds": round(time.monotonic() - tick, 3)})
        except KeyboardInterrupt:
            atomic_json(root / "collection_report.json", {
                **report, "status": "interrupted", "stage": "price_days",
            })
            raise
        except Exception as exc:
            report["bulk_price_failures"].append({"date": str(day.date()), "reason": str(exc)})
            consecutive_failures += 1
            record({"state": "failed", "consecutive_failures": consecutive_failures})
            print(f"KRX date {day:%Y-%m-%d} failed after retries: {exc}", flush=True)
            if consecutive_failures >= 3:
                atomic_json(root / "collection_report.json", {
                    **report, "status": "failed", "stage": "price_days",
                    "reason": "3 consecutive dates failed; stop requests and resume after provider recovery",
                })
                raise RuntimeError(
                    "KRX daily collection stopped after 3 consecutive failed dates; "
                    "verified caches preserved. Inspect collection_report.json and resume later."
                ) from exc
        if progress["completed_days"] % 25 == 0 or day == days[-1]:
            elapsed = time.monotonic() - started
            print(f"KRX days {progress['completed_days']}/{len(days)}; cache {progress['cached_days']}; "
                  f"failed {len(report['bulk_price_failures'])}; elapsed {elapsed:.1f}s", flush=True)
    if not frames:
        return None
    return pd.concat(frames, ignore_index=True).groupby("Code", sort=False)


def stock_raw(bulk, code, days):
    """Only complete observed windows can bypass the individual raw adapter."""
    try:
        frame = bulk.get_group(code).set_index("Date").sort_index()
    except KeyError:
        return None
    frame = frame.loc[frame.index.isin(days)].reset_index()
    return frame[KRX_RAW_COLUMNS] if pd.DatetimeIndex(frame.Date).equals(days) else None
