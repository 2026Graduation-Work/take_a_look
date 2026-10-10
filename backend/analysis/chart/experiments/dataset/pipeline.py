"""Dataset collection and preprocessing using existing provider adapters."""

from __future__ import annotations

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
from shared.data.metadata import fetch_active_listing_intervals, load_metadata  # noqa: F401
from shared.data.prices import fetch_price_window, supplement_raw_ohlc  # noqa: F401
from shared.data.validation import (  # noqa: F401
    expected_sessions,
    validate_flow,
    validate_index,
    validate_prices,
)
from shared.features.builder import build_feature_frame
from shared.io import sha256
from shared.settings import PRICE_BASIS, VALIDATION_VERSION, processing_contract


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


def flow_coverage(root, investors, columns, market_days):
    """Missing ranking rows are unknown observations, never inferred zero trades."""
    from shared.features.flow import build_flow_features

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
    from shared.data import providers as source

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
    from shared.data import providers as source

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
    from shared.data.bulk_prices import prepare_bulk_prices, stock_raw

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
                raw_window = stock_raw(bulk, code, days) if bulk is not None else None
                fetched = fetch_price_window(code, days, root=root, raw=raw_window,
                    is_delisted=row.IsDelisted, source=source,
                    progress=lambda event: append_collection_event(root, event))
                providers.append(fetched.PriceProvider.iloc[0])
                fetched = fetched.assign(Code=code, Name=row.Name, IsDelisted=row.IsDelisted)
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
        "processing_contract": processing_contract(config["preprocessing"]),
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
        "processing_contract": processing_contract(config["preprocessing"]),
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
    previous_processed = root / "processed_manifest.json"
    if previous_processed.exists():
        previous = json.loads(previous_processed.read_text())
        if previous.get("processing_contract") != processing_contract(config["preprocessing"]):
            raise ValueError("Preserve the previous processed data; use a new dataset root for this builder")
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
    if (failed and not allow_partial) or not outputs:
        raise RuntimeError(
            f"Preprocessing incomplete; inspect {root / 'preprocessing_report.json'}"
        )
    atomic_json(
        root / "processed_manifest.json",
        {
            "contract_version": VALIDATION_VERSION,
            "settings": config["preprocessing"],
            "processing_contract": processing_contract(config["preprocessing"]),
            "raw_files": (
                {name: manifest["raw_files"][name] for name in outputs}
                if allow_partial else manifest["raw_files"]
            ),
            "allow_partial": allow_partial,
            "files": outputs,
            "implementation_sha256": sha256(Path(__file__).parents[2] / "shared/features/builder.py"),
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
    if processed.get("processing_contract") != processing_contract(config["preprocessing"]):
        raise ValueError("Shared processing changed; rerun preprocessing in a new dataset root")
    if processed["settings"] != config["preprocessing"] or processed["raw_files"] != expected_raw:
        raise ValueError("Dataset changed; rerun preprocessing before preparing features")
    if processed["implementation_sha256"] != sha256(Path(__file__).parents[2] / "shared/features/builder.py"):
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
