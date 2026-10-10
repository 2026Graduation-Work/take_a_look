"""Verify preserved v3 artifacts, export a matching pack, and activate locally."""

import argparse
import json
import shutil
from pathlib import Path

import lightgbm as lgb
import numpy as np
import pandas as pd
import yaml
from experiments.experiment_utils import resolve_splits
from serving.internal.inference import infer_batch
from serving.internal.pack import load_pack
from shared.data.calendar import verify_calendar_schedule
from shared.data.providers import _attach_actual_vwap
from shared.data.validation import validate_prices
from shared.features.builder import build_feature_frame
from shared.features.columns import BASE_FEATURES, FLOW_FEATURES
from shared.io import atomic_json, sha256_file
from shared.settings import BUILDER_ID, CHART_ROOT, PREPROCESSING, PRICE_BASIS, processing_contract

from .pack import build_pack


def preserved_path(value):
    """Only export resolves historical manifest paths through the audited move map."""
    old = Path(value)
    if not old.is_absolute():
        old = CHART_ROOT / old
    migration = json.loads((CHART_ROOT / "docs/migration.json").read_text())
    original_root = Path(migration.get("original_chart_root", str(CHART_ROOT)))
    try:
        relative = str(old.relative_to(CHART_ROOT))
    except ValueError:
        relative = str(old.relative_to(original_root))
    moves = migration["moves"]
    for source, target in moves:
        if relative == source or relative.startswith(source + "/"):
            return (CHART_ROOT / (target + relative[len(source):])).resolve()
    return old.resolve()


def verify_inputs(dataset, names, feature_store=None):
    original = json.loads((dataset / "dataset_manifest.json").read_text())
    processed = json.loads((dataset / "processed_manifest.json").read_text())
    calendar = json.loads((dataset / "calendar.json").read_text())
    verify_calendar_schedule(calendar)
    if (original.get("contract_version") != 3 or not original.get("prices_complete")
            or original.get("price_basis") != PRICE_BASIS
            or processed["settings"] != PREPROCESSING
            or processed["raw_files"] != original["raw_files"]):
        raise ValueError("Preserved v3 dataset settings or raw provenance mismatch")
    original_builder = CHART_ROOT / "workspace/archive/pre-refactor/originals/core/local_features.py"
    if processed.get("processing_contract") == processing_contract():
        builder_source = CHART_ROOT / "shared/features/builder.py"
    else:
        builder_source = original_builder
        if processed["implementation_sha256"] != sha256_file(builder_source):
            raise ValueError("Preserved processed data has an unverified builder")
    metadata = pd.read_csv(dataset / "ticker_metadata.csv", dtype={"Code": str},
                           parse_dates=["ListingDate", "DelistingDate"])
    days = pd.to_datetime(calendar["trading_days"])
    checked_rows, unavailable_rows, range_rows = 0, 0, 0
    cases = []
    base_names = [name for name in names if name not in FLOW_FEATURES]
    flow_names = [name for name in names if name in FLOW_FEATURES]
    flow_missing_rows = 0
    comparison = list(dict.fromkeys(["Open", "High", "Low", "Close", "Volume", "VWAP",
                                    "RawOpen", "RawHigh", "RawLow", "RawClose", "RawVolume", "Amount",
                                    "RegularSessionUnavailable", "Trading_Halt", "Log_Ret", "Sigma", *names]))
    for index, (name, expected_hash) in enumerate(sorted(processed["files"].items()), 1):
        source, expected_path = dataset / "raw" / name, dataset / "processed" / name
        if sha256_file(source) != original["raw_files"][name] or sha256_file(expected_path) != expected_hash:
            raise ValueError(f"Preserved raw/processed checksum mismatch: {name}")
        raw = pd.read_parquet(source)
        expected = pd.read_parquet(expected_path)
        if feature_store is not None:
            trained = pd.read_parquet(feature_store / name, columns=["Date", *names])
            if (not pd.to_datetime(trained.Date).equals(pd.to_datetime(expected.Date))
                    or not np.allclose(trained[base_names].to_numpy(dtype=float), expected[base_names].to_numpy(dtype=float), rtol=1e-8, atol=1e-10, equal_nan=True)):
                raise ValueError(f"Model training store/v3 processed input mismatch: {name}")
        indexed = raw.set_index("Date")
        fields = [f"Raw{c}" for c in ("Open", "High", "Low", "Close", "Volume")] + ["Amount"]
        attached = _attach_actual_vwap(indexed, indexed[fields]).reset_index()
        pieces = []
        for interval in metadata.loc[metadata.Code.eq(Path(name).stem)].itertuples():
            active = pd.to_datetime(attached.Date).ge(interval.ListingDate)
            if pd.notna(interval.DelistingDate):
                active &= pd.to_datetime(attached.Date).lt(interval.DelistingDate)
            subset = attached.loc[active].copy()
            if subset.empty:
                continue
            active_days = days[(days >= subset.Date.min()) & (days <= subset.Date.max())]
            subset = validate_prices(subset, pd.DatetimeIndex(active_days))
            pieces.append(build_feature_frame(subset, days, PREPROCESSING))
        rebuilt = pd.concat(pieces, ignore_index=True)
        if not pd.to_datetime(rebuilt.Date).equals(pd.to_datetime(expected.Date)):
            raise ValueError(f"Shared/v3 session or listing interval mismatch: {name}")
        base_comparison = [name for name in comparison if name not in FLOW_FEATURES]
        if not np.allclose(rebuilt[base_comparison].to_numpy(dtype=float), expected[base_comparison].to_numpy(dtype=float),
                           rtol=1e-8, atol=1e-10, equal_nan=True):
            raise ValueError(f"Shared/v3 price or feature mismatch: {name}")
        if flow_names:
            if feature_store is None or not np.allclose(
                rebuilt[flow_names].to_numpy(dtype=float), trained[flow_names].to_numpy(dtype=float),
                rtol=1e-8, atol=1e-10, equal_nan=True
            ):
                raise ValueError(f"Shared/training flow feature mismatch: {name}")
            flow_missing_rows += int(rebuilt[flow_names].isna().any(axis=1).sum())
        checked_rows += len(raw)
        unavailable_rows += int(expected.RegularSessionUnavailable.sum())
        range_rows += int(expected.VWAPOutsideDailyRange.sum())
        if Path(name).stem in {"005930", "000040", "001527", "015540", "016380", "016385", "047810", "145210"}:
            cases.append({"code": Path(name).stem, "rows": len(raw), "columns_match": len(comparison)})
        if index % 100 == 0:
            print(json.dumps({"event": "shared_v3_parity", "files_checked": index, "rows_checked": checked_rows}), flush=True)
    return {"files": len(processed["files"]), "rows": checked_rows, "columns": comparison,
            "rtol": 1e-8, "atol": 1e-10, "regular_session_unavailable_rows": unavailable_rows,
            "vwap_outside_range_rows": range_rows, "cases": cases,
            "flow_feature_columns": flow_names, "flow_incomplete_rows": flow_missing_rows,
            "original_builder_sha256": sha256_file(builder_source),
            "dataset_manifest_sha256": sha256_file(dataset / "dataset_manifest.json"),
            "processed_manifest_sha256": sha256_file(dataset / "processed_manifest.json"),
            "calendar_sha256": sha256_file(dataset / "calendar.json")}


def verify_runs(result_dirs, *, with_flows=False):
    models, predictions, provenance = {}, {}, {}
    configs = []
    groups = ["base", "flow"] if with_flows else ["base"]
    names = list(BASE_FEATURES) + (list(FLOW_FEATURES) if with_flows else [])
    for horizon, result in result_dirs.items():
        manifest_path = result / "run_manifest.json"
        manifest = json.loads(manifest_path.read_text())
        cfg = manifest["config"]
        if (cfg.get("contract_version") != 3 or cfg["features"]["groups"] != groups
                or cfg["labels"]["horizon"] != horizon or manifest["feature_columns"] != names
                or cfg["dataset"]["preprocessing"] != PREPROCESSING):
            raise ValueError("Expected completed v3 H5/H20 runs with the requested common feature groups/order")
        folds = resolve_splits(cfg)
        last = folds[-1]
        if (last["train_start"], last["train_end"], last["test_end"]) != ("2023-01-01", "2025-12-31", "2026-10-06"):
            raise ValueError("Expected 2023..2025 training and data ending 2026-10-06")
        cache_hash = manifest["predictions_hash"]
        models[horizon] = CHART_ROOT / "workspace/experiments/cache/training/models" / f"{cache_hash}_fold{last['fold_id']}_model.txt"
        predictions[horizon] = CHART_ROOT / "workspace/experiments/cache/predictions" / f"{cache_hash}_predictions.parquet"
        model_meta_path = Path(str(models[horizon]) + ".manifest.json")
        prediction_meta_path = Path(str(predictions[horizon]) + ".manifest.json")
        model_meta = json.loads(model_meta_path.read_text())
        pred_meta = json.loads(prediction_meta_path.read_text())
        if (sha256_file(models[horizon]) != model_meta["sha256"]
                or sha256_file(predictions[horizon]) != pred_meta["sha256"]
                or pred_meta["predictions_hash"] != cache_hash or pred_meta["config"] != cfg
                or pred_meta["feature_columns"] != manifest["feature_columns"]
                or model_meta["feature_columns"] != manifest["feature_columns"]):
            raise ValueError("Preserved model/prediction provenance mismatch")
        model = lgb.Booster(model_file=str(models[horizon]))
        if model.num_model_per_iteration() != 3 or model.feature_name() != manifest["feature_columns"]:
            raise ValueError("Research model feature/class mismatch")
        prediction = pd.read_parquet(predictions[horizon])
        prediction.Date = pd.to_datetime(prediction.Date)
        if (set(prediction.fold_id.unique()) != {f["fold_id"] for f in folds}
                or not prediction.fold_id.eq(prediction.Date.dt.year - 2019).all()
                or prediction.Date.max() != pd.Timestamp("2026-10-06")
                or not np.allclose(prediction[["prob_down", "prob_neutral", "prob_up"]].sum(axis=1), 1)):
            raise ValueError("OOS dates/folds/classes mismatch")
        store = preserved_path(cfg["features"]["materialized_dir"])
        feature_manifest_path = store / "feature_manifest.json"
        feature_manifest = json.loads(feature_manifest_path.read_text())
        if feature_manifest["feature_columns"] != names:
            raise ValueError("Training feature store order differs from the models")
        for name, digest in feature_manifest["file_hashes"].items():
            if sha256_file(store / name) != digest:
                raise ValueError(f"Training feature store checksum mismatch: {name}")
        provenance[f"h{horizon}"] = {
            "run_manifest_sha256": sha256_file(manifest_path), "original_run_manifest": str(manifest_path),
            "prediction_hash": cache_hash, "prediction_sha256": pred_meta["sha256"],
            "prediction_manifest_sha256": sha256_file(prediction_meta_path),
            "model_sha256": model_meta["sha256"], "model_manifest_sha256": sha256_file(model_meta_path),
            "feature_manifest_sha256": sha256_file(feature_manifest_path), "training_feature_store": str(store), "fold": last,
            "oos_period": {"start": prediction.Date.min().date().isoformat(), "end": "2026-10-06"},
            "labels": cfg["labels"], "prediction_rows": len(prediction),
            "feature_groups": groups, "feature_columns": names}
        configs.append(cfg)
    if configs[0]["dataset"] != configs[1]["dataset"]:
        raise ValueError("H5/H20 datasets disagree")
    return models, predictions, provenance, preserved_path(configs[0]["dataset"]["root"])


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--h5-result", type=Path, required=True)
    parser.add_argument("--h20-result", type=Path, required=True)
    parser.add_argument("--pack-id", required=True)
    parser.add_argument("--with-flows", action="store_true", help="Export base + investor-flow H5/H20 runs")
    parser.add_argument("--activate", action="store_true")
    args = parser.parse_args(argv)
    models, predictions, sources, dataset = verify_runs({5: args.h5_result, 20: args.h20_result}, with_flows=args.with_flows)
    stores = {source["training_feature_store"] for source in sources.values()}
    if len(stores) != 1:
        raise ValueError("H5/H20 training feature stores disagree")
    evidence = verify_inputs(dataset, sources["h5"]["feature_columns"], Path(next(iter(stores))))
    info = {"feature_builder_id": BUILDER_ID, "processing_contract": processing_contract(),
            "training_period": {"start": "2023-01-01", "end": "2025-12-31"},
            "data_period": {"start": "2016-01-04", "end": "2026-10-06", "partial_years": [2026]},
            "validation_status": "all_preserved_v3_price_feature_hashes_and_local_inference_passed",
            "known_issues": ["Adjusted prices are current snapshots, not point-in-time archives.",
                             "Past KOSPI membership history is not fully verified.",
                             "KRX turnover aggregation scope is unverified; out-of-range VWAP is retained.",
                             "Regular-session unavailable rows exclude execution but do not establish official suspension.",
                             ("Missing investor ranking rows stay null; incomplete flow windows block flow-model inference."
                              if args.with_flows else "Missing investor ranking rows stay null; base H5/H20 models do not use flows."),
                             "2026 results are partial through 2026-10-06."],
            "models": sources, "feature_parity": evidence}
    output = CHART_ROOT / "workspace/serving/packs"
    root, archive, reports = build_pack(pack_id=args.pack_id, output=output, models=models,
        predictions=predictions, processed_dir=dataset / "processed",
        calendar_file=dataset / "calendar.json", research_manifest=info)
    pack, paths = load_pack(root)
    raw = pd.read_parquet(dataset / "raw/005930.parquet")
    days = pd.to_datetime(json.loads((dataset / "calendar.json").read_text())["trading_days"])
    features = build_feature_frame(raw, set(days.date)).tail(1)
    if args.with_flows and features[list(FLOW_FEATURES)].isna().any(axis=None):
        raise ValueError("Flow-model activation requires a complete operational preview input")
    scores = {str(h): infer_batch(paths[h][0], features)[0][0] for h in (5, 20)}
    atomic_json(root / "serving_check.json", {"feature_parity": evidence, "stock_code": "005930", "scores": scores})
    if args.activate:
        config_path = CHART_ROOT / "serving/config.local.yaml"
        previous_path = config_path if config_path.exists() else CHART_ROOT / "serving/config.yaml"
        previous = yaml.safe_load(previous_path.read_text())
        previous_pack = output / previous["active_pack"]["pack_id"] / "manifest.json"
        previous_manifest = json.loads(previous_pack.read_text()) if previous_pack.exists() else {}
        atomic_json(root / "previous_active_pack.json", {"config": previous,
                    "previous_processing_contract": previous_manifest.get("processing_contract"),
                    "previous_builder_sources": previous_manifest.get("builder_sources"),
                    "builder_baseline_commit": "dc67769" if previous_manifest.get("processing_contract") == processing_contract() else ("0c474ff" if previous_manifest.get("processing_contract", {}).get("sha256") == "4bc96abda10a26638271744f35f5f4d157e177b8c127adab83bc13f287c71867" else ("e5a0fe4" if previous_manifest.get("processing_contract") else "095584b")), "original_builder_snapshot": "workspace/archive/pre-refactor/originals",
                    "policy": "Restore this pack together with its recorded compatible builder."})
        temporary = config_path.with_suffix(".yaml.tmp")
        temporary.write_text(yaml.safe_dump({"active_pack": {"pack_id": args.pack_id,
            "release_tag": "chart-serving-" + args.pack_id, "asset_name": archive.name,
            "sha256": sha256_file(archive), "builder_sha256": processing_contract()["sha256"]}}, sort_keys=False))
        temporary.replace(config_path)
        # Explicitly export one operational preview input, with provenance. Serving never scans research paths.
        inputs = CHART_ROOT / "workspace/serving/inputs/raw"
        inputs.mkdir(parents=True, exist_ok=True)
        source = dataset / "raw/005930.parquet"
        destination = inputs / "005930.parquet"
        if destination.exists():
            backup = CHART_ROOT / "workspace/archive/previous-operational-inputs" / args.pack_id / sha256_file(destination)
            backup.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(destination, backup)
            previous_metadata = destination.with_suffix(".manifest.json")
            if previous_metadata.exists():
                shutil.copy2(previous_metadata, backup.with_suffix(".manifest.json"))
        shutil.copy2(source, destination)
        atomic_json(destination.with_suffix(".manifest.json"), {"source": str(source), "source_sha256": sha256_file(source),
                    "processing_contract_sha256": processing_contract()["sha256"], "pack_id": args.pack_id,
                    "purpose": "explicit local preview input transfer"})
    atomic_json(CHART_ROOT / "docs/local-pack-validation.json", {
        "pack_id": args.pack_id, "processing_contract": pack["processing_contract"],
        "models": sources, "feature_parity": evidence, "build_reports": reports, "scores": scores,
        "archive_sha256": sha256_file(archive), "activated_locally": args.activate,
        "data_period": info["data_period"], "known_issues": info["known_issues"]})
    print(json.dumps({"pack_id": args.pack_id, "archive": str(archive), "sha256": sha256_file(archive),
                      "activated_locally": args.activate, "reports": reports, "scores": scores}))


if __name__ == "__main__":
    main()
