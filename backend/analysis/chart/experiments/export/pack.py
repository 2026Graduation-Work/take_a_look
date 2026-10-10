"""Export validated research artifacts as an immutable serving pack."""
import json
import shutil
import tarfile
from pathlib import Path

import lightgbm as lgb
from serving.internal.pack import FORMAT_VERSION, load_pack
from shared.io import sha256_file
from shared.settings import BUILDER_ID, CHART_ROOT, processing_contract

from .samples import build_samples

LOCAL_BUILDER_ID = BUILDER_ID

def build_pack(*, pack_id, output, models, predictions, processed_dir, calendar_file=None, research_manifest=None):
    if not pack_id or any(ch not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_" for ch in pack_id):
        raise ValueError("Invalid pack ID")
    if not research_manifest or not calendar_file:
        raise ValueError("A verified research manifest and calendar are required")
    if research_manifest.get("processing_contract") != processing_contract():
        raise ValueError("Export/shared processing contract mismatch")
    root = Path(output) / pack_id
    if root.exists():
        raise FileExistsError(root)
    root.mkdir(parents=True)
    official = json.loads(Path(calendar_file).read_text())["trading_days"]
    manifest_settings = research_manifest["processing_contract"]["preprocessing"]
    manifest = {"format_version": FORMAT_VERSION, "pack_id": pack_id,
                "feature_builder_id": BUILDER_ID,
                "processing_contract": processing_contract(),
                "feature_barriers": {"up_mult": manifest_settings["barrier_feature_up_mult"], "down_mult": manifest_settings["barrier_feature_down_mult"]},
                "comparison": {"score_absolute": .01, "sigma_relative": .05},
                "return_rule": "100 * (adjusted_close_after_H_traded_rows / adjusted_close_on_prediction_date - 1)",
                "known_issues": research_manifest["known_issues"],
                "validation_status": research_manifest["validation_status"],
                "horizons": {}}
    if research_manifest.get("feature_builder_id") != BUILDER_ID:
        raise ValueError("Export/shared feature builder mismatch")
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
        part = root / f"h{horizon}"
        part.mkdir()
        model_path = part / "model.txt"
        shutil.copyfile(models[horizon], model_path)
        model = lgb.Booster(model_file=str(model_path))
        if model.num_model_per_iteration() != 3:
            raise ValueError("Expected 3-class model")
        samples, report = build_samples(predictions[horizon], processed_dir, horizon, calendar_days=official)
        source_sha = sha256_file(predictions[horizon])
        sample_path = part / "historical_samples.parquet"
        samples.to_parquet(sample_path, index=False)
        reports[f"h{horizon}"] = report
        manifest["horizons"][f"h{horizon}"] = {
            "horizon": horizon, "profile": "aggressive" if horizon == 5 else "stable",
            "model_file": f"h{horizon}/model.txt", "model_sha256": sha256_file(model_path),
            "samples_file": f"h{horizon}/historical_samples.parquet", "samples_sha256": sha256_file(sample_path),
            "source_prediction_sha256": source_sha,
            "feature_names": model.feature_name(), "classes": {"down": 0, "neutral": 1, "up": 2},
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
