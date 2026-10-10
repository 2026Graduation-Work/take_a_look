"""Prepare configured local inputs while preserving every price-path row."""

import json
import re
from pathlib import Path

import pandas as pd
from experiments.dataset.pipeline import validate_processed_inputs
from shared.io import atomic_json, atomic_parquet, identity, sha256

from .flow import build_flow_features
from .panel_builder import assemble_feature_panel, load_feature_sources
from .psychology import FEATURE_COLUMNS, PsychologyFeatureConfig, build_psychology_features
from .registry import FEATURE_VERSION, FLOW_FEATURES


def prepare_local_panel(config):
    root = Path(config["dataset"]["root"])
    destination = Path(config["features"]["materialized_dir"])
    contract = validate_processed_inputs(config["dataset"])
    frames = []
    for name, digest in contract["files"].items():
        path = root / "processed" / name
        if not path.exists() or sha256(path) != digest:
            raise ValueError(f"Processed input changed: {path}; rerun preprocessing")
        frames.append((name, pd.read_parquet(path)))
    sources = (
        load_feature_sources(config["features"]["sources"])
        if config["features"].get("sources")
        else []
    )
    selected = config["feature_columns"]
    inputs = {
        "processed": contract,
        "sources": {s.spec.name: s.fingerprint for s in sources},
        "selected": selected,
        "version": FEATURE_VERSION,
    }
    if config["features"].get("matched_sample_file"):
        sample_path = Path(config["features"]["matched_sample_file"])
        inputs["matched_sample"] = sha256(sample_path)
    fingerprint = identity(inputs)
    manifest_path = destination / "feature_manifest.json"
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text())
        if manifest.get("input_identity") != fingerprint:
            raise ValueError("Feature inputs changed; use a fresh feature store or rebuild inputs")
        for name, digest in manifest["file_hashes"].items():
            if sha256(destination / name) != digest:
                raise ValueError("Feature store modified; prepare again in a fresh store")
        return manifest
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
    calendar = json.loads((root / "calendar.json").read_text())
    metadata = pd.read_csv(
        root / "ticker_metadata.csv",
        dtype={"Code": str},
        parse_dates=["ListingDate", "DelistingDate"],
    )
    lookback = max(
        [
            int(match.group(1))
            for column in selected
            if (match := re.search(r"_(5|10|20|30|60)$", column))
        ],
        default=1,
    )
    reports, hashes, sample_keys = [], {}, []
    for name, base in frames:
        panel, report = assemble_feature_panel(base, sources)
        if set(selected) & set(FLOW_FEATURES):
            raw = pd.read_parquet(root / "raw" / name)
            flow = build_flow_features(raw, calendar["trading_days"])
            panel = panel.drop(columns=list(FLOW_FEATURES), errors="ignore")
            panel = panel.merge(
                flow.drop(columns="AvailableDate"),
                on=["Date", "Code"],
                how="left",
                validate="one_to_one",
            )
        missing = set(selected) - set(panel)
        if missing:
            raise ValueError(f"{name}: missing selected inputs {sorted(missing)}")
        warmed = pd.Series(False, index=panel.index)
        for interval in metadata.loc[metadata.Code.eq(Path(name).stem)].itertuples():
            interval_rows = panel.Date.ge(interval.ListingDate)
            if pd.notna(interval.DelistingDate):
                interval_rows &= panel.Date.lt(interval.DelistingDate)
            warmed.loc[panel.index[interval_rows][lookback:]] = True
        eligible = panel.Trading_Halt.eq(0) & panel.Sigma.notna() & warmed
        required_flow = [col for col in selected if col in FLOW_FEATURES]
        flow_complete = (
            panel[required_flow].notna().all(axis=1)
            if required_flow
            else pd.Series(True, index=panel.index)
        )
        flow_excluded = eligible & ~flow_complete
        eligible &= flow_complete
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
    atomic_parquet(destination / "sample_keys.parquet", pd.concat(sample_keys, ignore_index=True))
    manifest = {
        "input_identity": fingerprint,
        "feature_version": FEATURE_VERSION,
        "feature_columns": selected,
        "dataset_id": config["dataset"]["dataset_id"],
        "output_feature_store_dir": str(destination),
        "file_hashes": hashes,
        "files": reports,
        "config": config,
    }
    atomic_json(manifest_path, manifest)
    return manifest
