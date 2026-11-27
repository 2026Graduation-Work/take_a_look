import json
import shutil
import tarfile
from pathlib import Path

import lightgbm as lgb
from experiments.dataset.pipeline import _require_current_training_prices
from serving.internal.pack import FORMAT_VERSION, load_pack
from shared.data.resolution_snapshot import require_price_provenance
from shared.io import sha256_file
from shared.settings import BUILDER_ID, CHART_ROOT, processing_contract

from .golden import DEFAULT_INPUTS, generate
from .samples import build_samples

LOCAL_BUILDER_ID = BUILDER_ID


def _verify_artifact(path, expected_contract, *, kind, allow_legacy):
    sidecar = Path(f"{path}.manifest.json")
    if not sidecar.exists() and not sidecar.is_symlink():
        if allow_legacy:
            return None
        raise ValueError(f"Missing {kind} manifest: {sidecar}. Use --allow-legacy-artifacts for legacy files.")
    metadata = json.loads(sidecar.read_text())
    if not isinstance(metadata, dict):
        raise ValueError(f"Invalid {kind} manifest: {sidecar}")
    contracts = [metadata["processing_contract"]] if "processing_contract" in metadata else []
    config = metadata.get("config")
    if kind == "prediction" and isinstance(config, dict) and "processing_contract" in config:
        contracts.append(config["processing_contract"])
    if not contracts or any(contract != expected_contract for contract in contracts):
        raise ValueError(f"Export {kind} processing contract mismatch: {path}")
    if metadata.get("sha256") != sha256_file(path):
        raise ValueError(f"Export {kind} checksum mismatch: {path}")
    return metadata


def build_pack(*, pack_id, output, models, predictions, processed_dir, calendar_file=None, research_manifest=None,
               allow_legacy_artifacts=False):
    if not pack_id or any(ch not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_" for ch in pack_id):
        raise ValueError("Invalid pack ID")
    if not research_manifest or not calendar_file:
        raise ValueError("A verified research manifest and calendar are required")
    expected_contract = processing_contract()
    if research_manifest.get("processing_contract") != expected_contract:
        raise ValueError("Export/shared processing contract mismatch")
    if research_manifest.get("feature_builder_id") != BUILDER_ID:
        raise ValueError("Export/shared feature builder mismatch")
    processed_dir = Path(processed_dir)
    dataset_root = processed_dir.parent
    dataset_manifest = dataset_root / "dataset_manifest.json"
    dataset = json.loads(dataset_manifest.read_text())
    processed_manifest = dataset_root / "processed_manifest.json"
    processed = json.loads(processed_manifest.read_text())
    evidence = require_price_provenance(research_manifest)
    if (not dataset.get("prices_complete")
            or evidence != _require_current_training_prices(dataset, dataset_root).provenance
            or evidence != require_price_provenance(processed)
            or sha256_file(dataset_manifest) != processed.get("dataset_manifest_sha256")
            or sha256_file(processed_manifest) != research_manifest.get("processed_manifest_sha256")
            or processed["raw_files"] != dataset["raw_files"]
            or processed.get("allow_partial")
            or set(processed["files"]) | set(processed["spac_excluded_rows"]) != set(dataset["raw_files"])):
        raise ValueError("Export training price provenance differs from processed inputs")
    root = Path(output) / pack_id
    if root.exists():
        raise FileExistsError(root)
    verified_inputs = {}
    for horizon in (5, 20):
        model_meta = _verify_artifact(models[horizon], expected_contract, kind="model",
                                      allow_legacy=allow_legacy_artifacts)
        prediction_meta = _verify_artifact(predictions[horizon], expected_contract, kind="prediction",
                                           allow_legacy=allow_legacy_artifacts)
        model = lgb.Booster(model_file=str(models[horizon]))
        feature_names = model.feature_name()
        if model.num_model_per_iteration() != 3:
            raise ValueError("Expected 3-class model")
        if model_meta is not None and model_meta.get("feature_columns") != feature_names:
            raise ValueError(f"Export model feature order mismatch: {models[horizon]}")
        verified_inputs[horizon] = feature_names, model_meta, prediction_meta

    names = {name for features, _, _ in verified_inputs.values() for name in features}
    golden = root / "golden" / f"{pack_id}.json"
    root.mkdir(parents=True)
    generate(pack_id, CHART_ROOT / DEFAULT_INPUTS, golden, model_features=names)
    official = json.loads(Path(calendar_file).read_text())["trading_days"]
    manifest_settings = research_manifest["processing_contract"]["preprocessing"]
    manifest = {"format_version": FORMAT_VERSION, "pack_id": pack_id,
                "feature_builder_id": BUILDER_ID,
                "processing_contract": expected_contract, "golden_sha256": sha256_file(golden),
                "feature_barriers": {"up_mult": manifest_settings["barrier_feature_up_mult"], "down_mult": manifest_settings["barrier_feature_down_mult"]},
                "comparison": {"score_absolute": .01, "sigma_relative": .05},
                "return_rule": "100 * (adjusted_close_after_H_traded_rows / adjusted_close_on_prediction_date - 1)",
                "known_issues": research_manifest["known_issues"],
                "validation_status": research_manifest["validation_status"],
                "horizons": {}}
    manifest["research_provenance"] = research_manifest
    manifest["data_period"] = research_manifest["data_period"]
    manifest["builder_sources"] = {}
    for name, digest in manifest["processing_contract"]["implementation_sha256"].items():
        destination = root / "builder" / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(CHART_ROOT / "shared" / name, destination)
        if sha256_file(destination) != digest:
            raise ValueError("Shared source changed during pack export")
        manifest["builder_sources"][name] = "builder/" + name
    reports = {}
    for horizon in (5, 20):
        feature_names, model_meta, prediction_meta = verified_inputs[horizon]
        part = root / f"h{horizon}"
        part.mkdir()
        model_path = part / "model.txt"
        shutil.copyfile(models[horizon], model_path)
        model_sha = sha256_file(model_path)
        if model_meta is not None and model_sha != model_meta["sha256"]:
            raise ValueError(f"Model changed during pack export: {models[horizon]}")
        samples, report = build_samples(predictions[horizon], processed_dir, horizon, calendar_days=official,
                                        price_files=processed["files"], segmented=True)
        source_sha = sha256_file(predictions[horizon])
        if prediction_meta is not None and source_sha != prediction_meta["sha256"]:
            raise ValueError(f"Prediction changed during pack export: {predictions[horizon]}")
        sample_path = part / "historical_samples.parquet"
        samples.to_parquet(sample_path, index=False)
        reports[f"h{horizon}"] = report
        manifest["horizons"][f"h{horizon}"] = {
            "horizon": horizon, "profile": "aggressive" if horizon == 5 else "stable",
            "model_file": f"h{horizon}/model.txt", "model_sha256": model_sha,
            "samples_file": f"h{horizon}/historical_samples.parquet", "samples_sha256": sha256_file(sample_path),
            "source_prediction_sha256": source_sha,
            "feature_names": feature_names, "classes": {"down": 0, "neutral": 1, "up": 2},
            "training_period": research_manifest["training_period"],
            "label_barriers": {key: research_manifest["models"][f"h{horizon}"]["labels"][key]
                               for key in ("up_mult", "down_mult")},
            "sample_period": {"start": samples.prediction_date.min().date().isoformat(),
                              "end": samples.prediction_date.max().date().isoformat()},
            "walk_forward_policy": "rolling_three_year_train_2019_2026",
            "fold_sources": {str(year - 2019): {"test_year": int(year), "training_end": f"{year-1}-12-31",
                                                "prediction_cache_sha256": source_sha}
                             for year in sorted(samples.prediction_date.dt.year.unique())},
        }
    if calendar_file:
        shutil.copyfile(calendar_file, root / "calendar.json")
        manifest["calendar_sha256"] = sha256_file(root / "calendar.json")
    (root / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    (root / "build_report.json").write_text(json.dumps(reports, ensure_ascii=False, indent=2) + "\n")
    load_pack(root)
    archive = root.parent / f"{pack_id}.tar.gz"
    with tarfile.open(archive, "w:gz") as tar:
        tar.add(root, arcname=pack_id)
    return root, archive, reports
