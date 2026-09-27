"""One-time conversion of explicit research artifacts into an independent model pack."""

import argparse
import json
import shutil
import tarfile
from pathlib import Path

import lightgbm as lgb

from .hashing import sha256_file
from .historical_samples import build_samples
from .pack import BUILDER_ID, FORMAT_VERSION, load_pack


def build_pack(*, pack_id, output, models, predictions, processed_dir, calendar_file=None):
    if not pack_id or any(ch not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_" for ch in pack_id):
        raise ValueError("Invalid pack ID")
    root = Path(output) / pack_id
    if root.exists():
        raise FileExistsError(root)
    root.mkdir(parents=True)
    official = None
    if calendar_file:
        official = json.loads(Path(calendar_file).read_text())["trading_days"]
    manifest = {"format_version": FORMAT_VERSION, "pack_id": pack_id,
                "feature_builder_id": BUILDER_ID,
                "feature_barriers": {"up_mult": 1.5, "down_mult": 1.2},
                "comparison": {"score_absolute": .01, "sigma_relative": .05},
                "return_rule": "100 * (adjusted_close_after_H_traded_rows / adjusted_close_on_prediction_date - 1)",
                "known_issues": ["Original walk-forward cache includes non-KRX dates. The legacy Trading_Halt marker excludes them where present; a full official-calendar audit is pending.",
                                 "Actual VWAP feature equivalence to training input has not been established."],
                "validation_status": "historical_quality_and_feature_equivalence_pending",
                "horizons": {}}
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
            "training_period": {"start": "2022-01-01", "end": "2024-12-31"},
            "label_barriers": ({"up_mult": 1.75, "down_mult": 1.5} if horizon == 5
                               else {"up_mult": 3.75, "down_mult": 3.0}),
            "sample_period": {"start": samples.prediction_date.min().date().isoformat(),
                              "end": samples.prediction_date.max().date().isoformat()},
            "walk_forward_policy": "rolling_three_year_train_2019_2025",
            "fold_sources": {str(year - 2019): {"test_year": year, "training_end": f"{year-1}-12-31",
                                                "prediction_cache_sha256": source_sha}
                             for year in range(2019, 2026)},
        }
    (root / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    (root / "build_report.json").write_text(json.dumps(reports, ensure_ascii=False, indent=2) + "\n")
    load_pack(root)
    archive = root.parent / f"{pack_id}.tar.gz"
    with tarfile.open(archive, "w:gz") as tar:
        tar.add(root, arcname=pack_id)
    return root, archive, reports


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pack-id", required=True)
    parser.add_argument("--output", type=Path, required=True)
    for horizon in (5, 20):
        parser.add_argument(f"--model-h{horizon}", type=Path, required=True)
        parser.add_argument(f"--predictions-h{horizon}", type=Path, required=True)
    parser.add_argument("--processed-dir", type=Path, required=True)
    parser.add_argument("--calendar-file", type=Path)
    args = parser.parse_args(argv)
    root, archive, reports = build_pack(
        pack_id=args.pack_id, output=args.output,
        models={5: args.model_h5, 20: args.model_h20},
        predictions={5: args.predictions_h5, 20: args.predictions_h20},
        processed_dir=args.processed_dir, calendar_file=args.calendar_file)
    print(json.dumps({"pack": str(root), "archive": str(archive), "archive_sha256": sha256_file(archive),
                      "reports": reports}, ensure_ascii=False))


if __name__ == "__main__":
    main()
