"""Prepare configured local inputs while preserving every price-path row."""

import fcntl
import json
import re
from pathlib import Path

import pandas as pd
from experiments.dataset.pipeline import validate_processed_inputs
from shared.data.segmented_prices import validate_segments
from shared.io import atomic_json, atomic_parquet, identity, sha256
from shared.processing import processing_compatible

from .panel_builder import assemble_feature_panel, load_feature_sources
from .psychology import FEATURE_COLUMNS, PsychologyFeatureConfig, build_psychology_features
from .registry import FEATURE_VERSION, FLOW_FEATURES


def feature_lookback(selected):
    return max(
        [
            int(match.group(1))
            for column in selected
            if (match := re.search(r"_(5|10|20|30|60)$", column))
        ],
        default=1,
    )


def feature_settings(config):
    features = config["features"]
    return {
        "sources": [{key: value for key, value in source.items() if key != "path"}
                    for source in features.get("sources", [])],
        "psychology": features.get("psychology", {}),
    }


def feature_inputs(config):
    root = Path(config["dataset"]["root"])
    processed = root / "processed_manifest.json"
    options = config["features"]
    sources = {source["name"]: sha256(source["path"]) if Path(source["path"]).is_file() else None
               for source in options.get("sources", [])}
    sample = options.get("matched_sample_file")
    return {
        "processed_manifest_sha256": sha256(processed) if processed.is_file() else None,
        "settings": feature_settings(config),
        "sources": sources,
        "matched_sample": sha256(sample) if sample and Path(sample).is_file() else None,
        "feature_columns": config["feature_columns"],
        "feature_version": FEATURE_VERSION,
    }


def matches_feature_inputs(config, manifest, processed, inputs, *, archived=False):
    if (
        not isinstance(manifest, dict)
        or manifest.get("feature_version") != FEATURE_VERSION
        or manifest.get("feature_columns") != inputs["feature_columns"]
        or manifest.get("processed_manifest_sha256") != inputs["processed_manifest_sha256"]
        or manifest.get("dataset_id") != config["dataset"]["dataset_id"]
        or manifest.get("official_actions") != processed.get("official_actions")
        or manifest.get("price_policy") != processed.get("price_policy")
        or manifest.get("config", {}).get("processing_contract") != processed.get("processing_contract")
        or not processing_compatible(processed.get("processing_contract"), config["processing_contract"])
        or not isinstance(manifest.get("file_hashes"), dict)
        or set(manifest["file_hashes"]) != set(processed["files"])
    ):
        return False
    if "inputs" in manifest:
        return manifest["inputs"] == inputs and manifest.get("input_identity") == identity(inputs)
    if inputs["sources"]:
        # Earlier stores cannot prove a new request's external source bytes.
        return archived and manifest.get("config") == config
    recorded = manifest.get("config", {})
    if feature_settings(recorded) != inputs["settings"]:
        return False
    legacy = {"processed": processed, "sources": {}, "selected": inputs["feature_columns"],
              "version": FEATURE_VERSION}
    if config["features"].get("matched_sample_file"):
        legacy["matched_sample"] = inputs["matched_sample"]
    return manifest.get("input_identity") == identity(legacy)


def _feature_candidates(base, inputs, config, processed):
    if not base.parent.is_dir():
        return
    for path in sorted(base.parent.iterdir(), key=lambda path: (path != base, path.name)):
        manifest_path = path / "feature_manifest.json"
        if not manifest_path.is_file():
            continue
        try:
            manifest = json.loads(manifest_path.read_text())
            if matches_feature_inputs(config, manifest, processed, inputs):
                yield path, manifest
        except (AttributeError, KeyError, OSError, TypeError, ValueError):
            continue


def _set_feature_location(config, destination):
    config["features"]["materialized_dir"] = str(destination)
    config["data"]["price_dir"] = str(destination)


def locate_feature_store(config):
    root = Path(config["dataset"]["root"])
    inputs = feature_inputs(config)
    base = root / "feature_store" / identity(inputs)
    manifest_path = root / "processed_manifest.json"
    destination = base
    if manifest_path.is_file():
        processed = json.loads(manifest_path.read_text())
        candidates = list(_feature_candidates(base, inputs, config, processed))
        if len(candidates) > 1:
            candidates = [(path, manifest) for path, manifest in candidates if feature_files_match(path, manifest)]
            if candidates and any(item["file_hashes"] != candidates[0][1]["file_hashes"] for _, item in candidates):
                raise ValueError("Multiple verified feature stores contain different outputs for these inputs")
        if candidates:
            destination = candidates[0][0]
        if processing_compatible(processed.get("processing_contract"), config["processing_contract"]):
            config["processing_contract"] = processed["processing_contract"]
    _set_feature_location(config, destination)


def feature_files_match(destination, manifest):
    files = dict(manifest["file_hashes"])
    if "sample_keys_sha256" in manifest:
        files["sample_keys.parquet"] = manifest["sample_keys_sha256"]
    return all((destination / name).is_file() and sha256(destination / name) == digest
               for name, digest in files.items())


def prepare_local_panel(config):
    root = Path(config["dataset"]["root"])
    processed = validate_processed_inputs(config["dataset"])
    config["processing_contract"] = processed["processing_contract"]
    inputs = feature_inputs(config)
    base = root / "feature_store" / identity(inputs)
    base.parent.mkdir(parents=True, exist_ok=True)
    with (base.parent / f"{base.name}.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        candidates = [(path, manifest) for path, manifest in _feature_candidates(base, inputs, config, processed)
                      if feature_files_match(path, manifest)]
        if candidates:
            destination, manifest = candidates[0]
            if any(item["file_hashes"] != manifest["file_hashes"] for _, item in candidates):
                raise ValueError("Multiple verified feature stores contain different outputs for these inputs")
            _set_feature_location(config, destination)
            return manifest
        destination = base
        attempt = 1
        while destination.exists():
            destination = base.with_name(f"{base.name}-{attempt}")
            attempt += 1
        _set_feature_location(config, destination)
        return _build_local_panel(config, processed, inputs, destination)


def _build_local_panel(config, contract, inputs, destination):
    frames = []
    processed_dir = Path(config["features"]["base_processed_dir"])
    for name in contract["files"]:
        frame = pd.read_parquet(processed_dir / name)
        validate_segments(frame, required=True)
        frames.append((name, frame))
    sources = load_feature_sources(config["features"]["sources"]) if inputs["sources"] else []
    selected = inputs["feature_columns"]
    destination.mkdir(parents=True, exist_ok=True)
    psychology = None
    if set(selected) & set(FEATURE_COLUMNS):
        all_prices = pd.concat([frame for _, frame in frames], ignore_index=True)
        psychology, _ = build_psychology_features(
            all_prices, PsychologyFeatureConfig(**config["features"].get("psychology", {}))
        )
        # Reuse the existing AvailableDate contract, retaining missing rows.
        from .panel_builder import LoadedFeatureSource, _parse_source_spec

        columns = [col for col in FEATURE_COLUMNS if col in selected]
        spec = _parse_source_spec(
            {
                "name": "psychology",
                "path": str(destination / "psychology.parquet"),
                "columns": columns,
                "apply_period": "one_day",
                "missing": {"policy": "forward_fill", "max_staleness_trading_days": 0},
            }
        )
        sources.append(LoadedFeatureSource(spec, psychology, {}))
    lookback = feature_lookback(selected)
    reports, hashes, sample_keys = [], {}, []
    for name, base in frames:
        panel, report = assemble_feature_panel(base, sources)
        missing = set(selected) - set(panel)
        if missing:
            raise ValueError(f"{name}: missing selected inputs {sorted(missing)}")
        warmed = panel.groupby("SegmentId", observed=True).cumcount().ge(lookback)
        eligible = panel.Trading_Halt.eq(0) & panel.Sigma.notna() & warmed
        required_flow = [col for col in selected if col in FLOW_FEATURES]
        flow_complete = (
            panel[required_flow].notna().all(axis=1)
            if required_flow
            else pd.Series(True, index=panel.index)
        )
        flow_excluded = eligible & ~flow_complete
        eligible &= flow_complete
        if psychology is not None:
            eligible &= panel[[col for col in selected if col in FEATURE_COLUMNS]].notna().all(axis=1)
        if config["features"].get("matched_sample_file"):
            keys = pd.read_parquet(config["features"]["matched_sample_file"])[["Date", "Code"]]
            eligible &= pd.MultiIndex.from_frame(panel[["Date", "Code"]]).isin(
                pd.MultiIndex.from_frame(keys)
            )
        panel["Code"] = panel["Code"].astype("string").str.zfill(6)
        panel["SampleEligible"] = eligible
        panel = panel.drop(columns=["Y_Label", "y_label"], errors="ignore")
        atomic_parquet(destination / name, panel)
        hashes[name] = sha256(destination / name)
        sample_keys.append(panel.loc[eligible, ["Date", "Code"]])
        reports.append(
            {
                "file": name,
                **report,
                "eligible_rows": int(eligible.sum()),
                "flow_excluded_rows": int(flow_excluded.sum()),
                "missing_by_selected_feature": panel[selected].isna().sum().to_dict(),
            }
        )
    if not sample_keys:
        raise ValueError("The pinned listing scope has no training price segments")
    sample_path = destination / "sample_keys.parquet"
    atomic_parquet(sample_path, pd.concat(sample_keys, ignore_index=True))
    if feature_inputs(config) != inputs:
        raise ValueError("Feature sources or processed manifest changed during preparation")
    manifest = {
        "input_identity": identity(inputs),
        "inputs": inputs,
        "price_policy": contract["price_policy"],
        "official_actions": contract["official_actions"],
        "processed_manifest_sha256": inputs["processed_manifest_sha256"],
        "feature_version": FEATURE_VERSION,
        "feature_columns": selected,
        "dataset_id": config["dataset"]["dataset_id"],
        "output_feature_store_dir": str(destination),
        "file_hashes": hashes,
        "sample_keys_sha256": sha256(sample_path),
        "files": reports,
        "spac_policy_excluded_files": sorted(set(contract["spac_excluded_rows"]) - hashes.keys()),
        "config": config,
    }
    atomic_json(destination / "feature_manifest.json", manifest)
    return manifest
