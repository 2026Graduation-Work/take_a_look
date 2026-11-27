from __future__ import annotations

import fcntl
import json
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd
from experiments.config import (
    append_collection_event,
    atomic_json,
    atomic_parquet,
    identity,
    load_dataset_config,
)
from shared.data.calendar import (  # noqa: F401
    build_calendar,
    fetch_authenticated_index,
    scheduled_sessions,
    verify_calendar_schedule,
)
from shared.data.market_notices import SecurityKey
from shared.data.resolution_snapshot import (
    PRICE_POLICY,
    REVIEW_COLUMNS,
    SEGMENT_COLUMN,
    pin_resolution_snapshot,
    read_resolution_snapshot,
    require_price_provenance,
    snapshot_path,
)
from shared.data.segmented_prices import (
    ADJUSTMENT_COLUMNS,
    adjust_price_history,
    fetch_raw_window,
    validate_segments,
)
from shared.data.training_prices import (
    PRICE_SOURCE,
    check_raw_overlap,
    load_training_raw,
    preserve_training_raw,
)
from shared.data.validation import (  # noqa: F401
    expected_sessions,
    validate_flow,
    validate_index,
    validate_krx_raw,
    validate_prices,
)
from shared.io import sha256
from shared.processing import build_feature_frame, processing_contract
from shared.settings import TRAINING_PRICE_BASIS, VALIDATION_VERSION

from .census_actions import _write_csv


def write_review_queue(snapshot, path, *, securities):
    rows = sorted(snapshot.review_rows(securities), key=lambda row: (row["Code"], row["Date"]))
    _write_csv(path, REVIEW_COLUMNS, rows)
    return {"rows": len(rows), "sha256": sha256(path)}


def flow_coverage(root, investors, columns, market_days, *, price_files):
    """Missing ranking rows are unknown observations, never inferred zero trades."""
    from shared.features.flow import build_flow_features

    coverage = []
    for name in sorted(price_files):
        path = root / "raw" / name
        if sha256(path) != price_files[name]:
            raise ValueError(f"Flow coverage price input changed: {name}")
        frame = pd.read_parquet(path)
        features = (pd.concat([build_flow_features(segment, market_days)
                               for _, segment in frame.groupby(SEGMENT_COLUMN, sort=False)], ignore_index=True)
                    if SEGMENT_COLUMN in frame else build_flow_features(frame, market_days))
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
    from shared.data import providers as source

    config = load_dataset_config(config_path)
    root = Path(config["root"])
    calendar = json.loads((root / "calendar.json").read_text())
    manifest = json.loads((root / "dataset_manifest.json").read_text())
    _require_current_training_prices(manifest, root)
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
    coverage = flow_coverage(root, source._INVESTORS, source._FLOW_COLUMNS, calendar["trading_days"],
                             price_files=manifest["raw_files"])
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


def training_metadata(snapshot, collection, calendar):
    requested = {str(code).zfill(6) for code in collection.get("tickers") or []}
    scope_codes = set(snapshot.manifest["scope"]["codes"])
    if scope_codes and requested != scope_codes:
        raise ValueError("Code-scoped resolution snapshot requires its exact code scope in collection.tickers")
    days = pd.DatetimeIndex(pd.to_datetime(calendar["trading_days"]))
    if not days.equals(snapshot.sessions):
        raise ValueError("Collection calendar differs from the complete resolution snapshot scope")
    rows = []
    for security, name in snapshot.training_names.items():
        if (security.market not in collection["markets"] or requested and security.code not in requested
                or security.delisting and not collection["include_delisted"]):
            continue
        rows.append({"Code": security.code, "Name": name, "Market": security.market, "Isin": security.isin,
                     "ListingDate": security.listing, "DelistingDate": security.delisting,
                     "ShareClass": security.share_class, "IsDelisted": security.delisting is not None,
                     "Source": "Pinned KRX listing interval", "MarketHistoryVerified": True})
    if not rows or requested - {row["Code"] for row in rows}:
        raise ValueError("Resolution snapshot lacks requested training listing windows")
    frame = pd.DataFrame(rows)
    for col in ("ListingDate", "DelistingDate"):
        frame[col] = pd.to_datetime(frame[col])
    frame = frame.sort_values(["Code", "ListingDate"]).reset_index(drop=True)
    same_code = frame.Code.eq(frame.Code.shift())
    former_end = frame.DelistingDate.shift()
    if (same_code & (former_end.isna() | frame.ListingDate.lt(former_end))).any():
        raise ValueError("Overlapping official training listing windows")
    return frame


def listing_identity(row):
    return SecurityKey(row.Code, row.Isin, row.ListingDate.date().isoformat(),
                       None if pd.isna(row.DelistingDate) else row.DelistingDate.date().isoformat(),
                       row.Market, row.ShareClass)


def verify_training_metadata(root, snapshot, collection, calendar):
    expected = training_metadata(snapshot, collection, calendar)
    stored = pd.read_csv(root / "ticker_metadata.csv", dtype={"Code": str},
                         parse_dates=["ListingDate", "DelistingDate"])
    stored["DelistingDate"] = pd.to_datetime(stored["DelistingDate"])
    if not stored.equals(expected):
        raise ValueError("Dataset metadata differs from pinned KRX listing windows")
    return stored


def collect_dataset(config_path, *, mode="full", rebuild=False, action_snapshot=None):
    config = load_dataset_config(config_path)
    root = Path(config["root"])
    root.mkdir(parents=True, exist_ok=True)
    with (root / "collection.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ValueError("A price collector already owns this dataset root") from None
        return _collect_dataset(config, mode, rebuild, action_snapshot)


def pinned_collection_window(snapshot, collection):
    scope = snapshot.manifest["scope"]
    settings = {**collection, "end_date": collection.get("end_date") or scope["end"]}
    expected = scheduled_sessions(pd.Timestamp(settings["start_date"]), pd.Timestamp(settings["end_date"]))
    training_metadata(snapshot, settings, {"trading_days": expected})
    return settings


def _collect_dataset(config, mode, rebuild, action_snapshot):
    from shared.data import providers as source

    contract = processing_contract(config["preprocessing"])
    root = Path(config["root"])
    if rebuild and mode != "full":
        raise ValueError("--rebuild requires full")
    if rebuild and root.exists() and any(path.name != "collection.lock" for path in root.iterdir()):
        raise FileExistsError("--rebuild requires a new dataset root; preserve existing data")
    manifest_path = root / "dataset_manifest.json"
    manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() else None
    pin_file = root / "collection_action_pin.json"
    collection_identity = identity(config["collection"])
    if manifest or pin_file.exists():
        pin = manifest if manifest else json.loads(pin_file.read_text())
        if pin["collection_identity"] != collection_identity:
            raise ValueError("Collection settings changed; use a new dataset root")
        snapshot = _require_current_training_prices(pin, root)
        if action_snapshot is not None and sha256(action_snapshot) != snapshot.path.stem:
            raise ValueError("Official action snapshot changed; use a new dataset root")
    else:
        if action_snapshot is None:
            raise ValueError("An official resolution snapshot is required for a new dataset")
        source_snapshot = read_resolution_snapshot(action_snapshot)
        pinned_collection_window(source_snapshot, config["collection"])
        snapshot = pin_resolution_snapshot(source_snapshot, root)
        atomic_json(pin_file, {"price_basis": TRAINING_PRICE_BASIS, "price_policy": PRICE_POLICY,
                               "official_actions": snapshot.provenance, "collection_identity": collection_identity})
    action_provenance = snapshot.provenance
    calendar_settings = pinned_collection_window(snapshot, config["collection"])
    append_collection_event(root, {"state": "started", "stage": "collection", "mode": mode})
    # End date is immutable inside a build, including resumed and update executions.
    calendar_path = root / "calendar.json"
    atomic_json(root / "collection_report.json", {"status": "running", "stage": "calendar"})
    try:
        if calendar_path.exists():
            calendar = json.loads(calendar_path.read_text())
            if "checked_end" not in calendar:
                calendar["checked_end"] = calendar["requested_end"]
            calendar["schedule_validation"] = verify_calendar_schedule(calendar)
            atomic_json(calendar_path, calendar)
        else:
            calendar = build_calendar(root, calendar_settings)
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
    try:
        if metadata_path.exists():
            metadata = verify_training_metadata(root, snapshot, config["collection"], calendar)
        else:
            metadata = training_metadata(snapshot, config["collection"], calendar)
            metadata.to_csv(metadata_path, index=False)
    except Exception as exc:
        append_collection_event(root, {"state": "failed", "stage": "metadata",
                                       "exception_type": type(exc).__name__, "reason": str(exc)})
        atomic_json(root / "collection_report.json",
                    {"status": "failed", "stage": "metadata", "reason": str(exc)})
        raise
    selected = {listing_identity(row) for row in metadata.itertuples()}
    review_details = write_review_queue(snapshot, root / "review_queue.csv", securities=selected)
    from shared.data.bulk_prices import prepare_bulk_prices, stock_raw

    report = {"prices": [], "flow_failures": [], "market_history_verified": False}
    bulk = prepare_bulk_prices(root, metadata, calendar, report, source)
    atomic_json(root / "collection_report.json", {"status": "running", "stage": "prices"})
    price_files = {}
    krx_raw_files = dict((manifest or {}).get("krx_raw_files", {}))
    price_events = []
    as_of = pd.Timestamp(calendar["observed_end"])
    for code, intervals in metadata.groupby("Code", sort=True):
        path = root / "raw" / f"{code}.parquet"
        original_path = root / "krx_raw_prices" / path.name
        expected = expected_sessions(intervals, calendar)
        if expected.empty:
            continue
        try:
            previous = pd.read_parquet(path) if (manifest and path.name in manifest["raw_files"] and path.exists()) else None
            saved = load_training_raw(original_path, expected, krx_raw_files.get(path.name))
            windows = [(listing_identity(row), row.Name) for row in intervals.itertuples()]
            if saved is None:
                raw_parts = []
                for security, _ in windows:
                    days = snapshot.days(security)
                    raw = stock_raw(bulk, code, days) if bulk is not None else None
                    if raw is None:
                        raw = fetch_raw_window(security, days, source=source,
                            progress=lambda event: append_collection_event(root, event))
                    raw_parts.append(validate_krx_raw(raw, days))
                saved = validate_krx_raw(pd.concat(raw_parts, ignore_index=True), expected)
            if previous is not None:
                previous["Date"] = pd.to_datetime(previous.Date).dt.normalize()
                check_raw_overlap(previous, saved)

            frame, event_parts = adjust_price_history(windows, saved, expected, as_of, snapshot)
            if not original_path.exists():
                preserve_training_raw(original_path, saved)
            krx_raw_files[path.name] = sha256(original_path)
            if previous is not None:
                flows = [col for col in source._FLOW_COLUMNS if col in previous]
                if flows:
                    frame = frame.merge(
                        previous[["Date", *flows]], on="Date", how="left", validate="one_to_one"
                    )
            resumed = previous is not None and previous.equals(frame)
            if not resumed:
                atomic_parquet(path, frame)
            price_files[path.name] = sha256(path)
            price_events.extend(event_parts)
            report["prices"].append(
                {
                    "code": code,
                    "status": "verified_resume" if resumed else "verified",
                    "rows": len(frame),
                    "providers": [PRICE_SOURCE],
                    "events": sum(len(events) for events in event_parts),
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
    event_table = pd.concat(price_events, ignore_index=True) if price_events else pd.DataFrame(columns=ADJUSTMENT_COLUMNS)
    event_table["ExDate"] = pd.to_datetime(event_table.ExDate)
    event_key = identity(event_table.to_json(date_format="iso", orient="table"))
    event_path = root / f"price_events_{event_key}.parquet"
    if not event_path.exists():
        with tempfile.TemporaryDirectory(dir=root) as staging:
            staged = Path(staging) / event_path.name
            atomic_parquet(staged, event_table)
            try:
                event_path.hardlink_to(staged)
            except FileExistsError:
                pass
    if not pd.read_parquet(event_path).equals(event_table):
        raise ValueError(f"Saved price events differ from the computed table: {event_path.name}")
    event_details = {"path": event_path.name, "sha256": sha256(event_path), "rows": len(event_table)}
    checkpoint = {
        "contract_version": VALIDATION_VERSION,
        "config": config,
        "dataset_id": config["dataset_id"],
        "collection_identity": collection_identity,
        "price_policy": PRICE_POLICY,
        "official_actions": action_provenance,
        "end_date": calendar["observed_end"],
        "raw_files": price_files,
        "krx_raw_files": krx_raw_files,
        "price_events": event_details,
        "review_queue": review_details,
        "prices_complete": not price_failed,
        "flows_complete": False,
        "flow_queries_complete": False,
        "price_basis": TRAINING_PRICE_BASIS,
        "processing_contract": contract,
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
        raw_paths = [root / "raw" / name for name in price_files]
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
    coverage = flow_coverage(root, source._INVESTORS, source._FLOW_COLUMNS, calendar["trading_days"],
                             price_files=checkpoint["raw_files"])
    report["flow_coverage"] = coverage
    failed = any(item["status"] == "failed" for item in report["prices"])
    manifest = {
        "contract_version": VALIDATION_VERSION,
        "config": config,
        "dataset_id": config["dataset_id"],
        "collection_identity": collection_identity,
        "price_policy": PRICE_POLICY,
        "official_actions": action_provenance,
        "end_date": calendar["observed_end"],
        "raw_files": checkpoint["raw_files"],
        "krx_raw_files": krx_raw_files,
        "price_events": event_details,
        "review_queue": review_details,
        "prices_complete": not failed,
        "price_basis": TRAINING_PRICE_BASIS,
        "processing_contract": contract,
        "flow_queries_complete": bool(config["collection"]["investor_flows"])
        and not report["flow_failures"]
        and report.get("flow_progress", {}).get("completed_days") == len(calendar["trading_days"]),
        "flows_complete": bool(coverage) and not report["flow_failures"]
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


def _require_current_training_prices(manifest, root, *, verify_archive=False):
    if manifest.get("price_basis") != TRAINING_PRICE_BASIS:
        raise ValueError("Unsupported dataset price basis; rerun collection before preprocessing")
    try:
        evidence = require_price_provenance(manifest)
    except ValueError:
        raise ValueError("Unsupported dataset price policy; rerun collection before preprocessing") from None
    snapshot = read_resolution_snapshot(snapshot_path(root, evidence["sha256"]), verify_archive=verify_archive)
    if snapshot.provenance != evidence:
        raise ValueError("Pinned official resolution snapshot provenance differs")
    return snapshot


def eligible_training_prices(raw, intervals, snapshot):
    validate_segments(raw, required=True)
    excluded = set().union(*(snapshot.excluded_segment_ids(listing_identity(row))
                             for row in intervals.itertuples()))
    return raw.loc[~raw[SEGMENT_COLUMN].isin(excluded)]


def build_segment_features(raw, trading_days, settings):
    return pd.concat([
        build_feature_frame(segment, trading_days, settings)
        for _, segment in raw.groupby(SEGMENT_COLUMN, sort=False)
    ], ignore_index=True)


def preprocess_dataset(config_path, *, rebuild=False, allow_partial=False):
    config = load_dataset_config(config_path)
    root = Path(config["root"])
    manifest_path = root / "dataset_manifest.json"
    if not manifest_path.exists():
        raise FileNotFoundError("Run price_collector.py --config first")
    manifest = json.loads(manifest_path.read_text())
    snapshot = _require_current_training_prices(manifest, root)
    if not manifest.get("prices_complete") and not allow_partial:
        raise ValueError("Price collection incomplete; resume collection first")
    calendar = json.loads((root / "calendar.json").read_text())
    if calendar.get("validation_version") != VALIDATION_VERSION:
        raise ValueError("Unverified calendar")
    metadata = verify_training_metadata(root, snapshot, config["collection"], calendar)
    contract = processing_contract(config["preprocessing"])
    previous_processed = root / "processed_manifest.json"
    if previous_processed.exists():
        previous = json.loads(previous_processed.read_text())
        if previous.get("processing_contract") != contract:
            raise ValueError("Preserve the previous processed data; use a new dataset root for this builder")
    reports = []
    outputs, policy_excluded = {}, {}
    for name in sorted(manifest["raw_files"]):
        path = root / "raw" / name
        try:
            raw_hash = sha256(path)
            if manifest["raw_files"].get(path.name) != raw_hash:
                raise ValueError("Raw changed outside collection; run update to revalidate")
            raw = pd.read_parquet(path)
            intervals = metadata.loc[metadata.Code.eq(path.stem)]
            raw = validate_prices(
                raw, expected_sessions(intervals, calendar),
                event_adjusted=True,
            )
            eligible = eligible_training_prices(raw, intervals, snapshot)
            excluded_rows = len(raw) - len(eligible)
            if excluded_rows:
                policy_excluded[name] = excluded_rows
            if eligible.empty:
                reports.append({"file": name, "status": "spac_policy", "excluded_rows": excluded_rows})
                continue
            frame = build_segment_features(eligible, pd.to_datetime(calendar["trading_days"]), config["preprocessing"])
            from shared.features.columns import BASE_FEATURES

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
    if failed and not allow_partial:
        raise RuntimeError(
            f"Preprocessing incomplete; inspect {root / 'preprocessing_report.json'}"
        )
    atomic_json(
        root / "processed_manifest.json",
        {
            "contract_version": VALIDATION_VERSION,
            "settings": config["preprocessing"],
            "price_policy": PRICE_POLICY,
            "official_actions": snapshot.provenance,
            "dataset_manifest_sha256": sha256(manifest_path),
            "processing_contract": contract,
            "raw_files": (
                {name: manifest["raw_files"][name] for name in outputs}
                if allow_partial else manifest["raw_files"]
            ),
            "allow_partial": allow_partial,
            "excluded_price_files": sorted(set(manifest.get("krx_raw_files", {})) - outputs.keys()
                                           | (manifest["raw_files"].keys() - outputs.keys())),
            "files": outputs,
            "spac_excluded_rows": policy_excluded,
            "implementation_sha256": contract["implementation_sha256"]["features/builder.py"],
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
    evidence = _require_current_training_prices(dataset, root).provenance
    if require_price_provenance(processed) != evidence:
        raise ValueError("Processed official action provenance changed")
    if (
        (not dataset.get("prices_complete") and not processed.get("allow_partial"))
        or processed.get("contract_version") != VALIDATION_VERSION
    ):
        raise ValueError("Dataset/processed not verified; collect and preprocess first")
    expected_raw = dataset["raw_files"]
    if processed.get("allow_partial"):
        expected_raw = {name: expected_raw.get(name) for name in processed["raw_files"]}
    contract = processing_contract(config["preprocessing"])
    if processed.get("processing_contract") != contract:
        raise ValueError("Shared processing changed; rerun preprocessing in a new dataset root")
    if (processed["settings"] != config["preprocessing"] or processed["raw_files"] != expected_raw
            or processed.get("dataset_manifest_sha256") != sha256(root / "dataset_manifest.json")):
        raise ValueError("Dataset changed; rerun preprocessing before preparing features")
    if processed["implementation_sha256"] != contract["implementation_sha256"]["features/builder.py"]:
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
