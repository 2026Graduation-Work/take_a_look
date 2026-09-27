"""Load an immutable model and empirical distribution release for serving."""

import hashlib
import json
from pathlib import Path

import pandas as pd


def sha256_file(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_release(manifest_path):
    """Validate files and metadata before any prediction is exported."""
    manifest_path = Path(manifest_path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    required = {"release_id", "profile", "horizon_days", "model_file", "model_sha256",
                "feature_names", "label_rule", "distribution_file", "distribution_sha256"}
    if required - manifest.keys():
        raise ValueError(f"Missing release fields: {sorted(required - manifest.keys())}")
    if manifest["profile"] not in {"stable", "aggressive"}:
        raise ValueError("Invalid release profile")
    if not isinstance(manifest["horizon_days"], int) or manifest["horizon_days"] < 1:
        raise ValueError("Invalid release horizon")
    label = manifest["label_rule"]
    if (label.get("type") != "dynamic_sigma" or label.get("sigma_window") != 20
            or label.get("up_observation") != "high"
            or label.get("down_observation") != "close"
            or label.get("same_day_tie") != "down"
            or label.get("halt_clock") != "traded_days"
            or label.get("up_mult", 0) <= 0 or label.get("down_mult", 0) <= 0):
        raise ValueError("Unsupported release label rule")
    names = manifest["feature_names"]
    if not isinstance(names, list) or not names or not all(isinstance(n, str) for n in names):
        raise ValueError("Release feature_names must be a nonempty string list")
    if len(set(names)) != len(names):
        raise ValueError("Duplicate release feature names")
    files = {}
    for key in ("model", "distribution"):
        relative = Path(manifest[f"{key}_file"])
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError(f"Release {key} path must stay inside its directory")
        path = manifest_path.parent / relative
        if sha256_file(path) != manifest[f"{key}_sha256"]:
            raise ValueError(f"Release {key} SHA-256 mismatch")
        files[key] = path

    artifact = json.loads(files["distribution"].read_text(encoding="utf-8"))
    if artifact.get("release_id") != manifest["release_id"]:
        raise ValueError("Distribution release_id mismatch")
    if artifact.get("profile") != manifest["profile"]:
        raise ValueError("Distribution profile mismatch")
    if artifact.get("horizon_days") != manifest["horizon_days"]:
        raise ValueError("Distribution horizon mismatch")
    buckets = artifact.get("buckets")
    if not isinstance(buckets, list) or not buckets:
        raise ValueError("Release requires empirical distribution buckets")
    previous = 0.0
    for bucket in buckets:
        bounds = bucket.get("score_bucket", {})
        low, high = bounds.get("low"), bounds.get("high")
        if low != previous or not isinstance(high, (int, float)) or not low < high <= 1:
            raise ValueError("Distribution buckets must partition scores from 0 to 1")
        if (bucket.get("model_version") != manifest["release_id"] or
                bucket.get("horizon_days") != manifest["horizon_days"]):
            raise ValueError("Distribution bucket model or horizon mismatch")
        if bucket.get("status") == "insufficient_samples" and manifest.get("allow_sparse_distribution"):
            if (not 0 <= bucket.get("sample_count", -1) < bucket.get("minimum_samples", 0)
                    or bucket.get("return_band") is not None or bucket.get("histogram") != []):
                raise ValueError("Invalid sparse distribution bucket")
            previous = high
            continue
        if (bucket.get("status") != "available" or bucket.get("sample_count", 0) <
                bucket.get("minimum_samples", 1)):
            raise ValueError("Release distribution bucket is unavailable")
        if not bucket.get("return_band") or not bucket.get("histogram"):
            raise ValueError("Release distribution bucket has no band or histogram")
        if not isinstance(bucket.get("bucket_hit_rate"), (int, float)) or not (
            0 <= bucket["bucket_hit_rate"] <= 1
        ):
            raise ValueError("Release bucket has no valid event hit rate")
        if bucket.get("return_definition") != "adjusted_close_to_close_fixed_horizon_percent":
            raise ValueError("Unsupported return definition")
        if bucket.get("event_definition") != "upper_barrier_first_within_horizon":
            raise ValueError("Unsupported event definition")
        if bucket.get("cohort_definition") != "same_model_horizon_score_bucket_only":
            raise ValueError("Unsupported cohort definition")
        if (bucket.get("model_version") != manifest["release_id"] or
                bucket.get("horizon_days") != manifest["horizon_days"]):
            raise ValueError("Distribution bucket model or horizon mismatch")
        if pd.Timestamp(bucket["period_end"]) > pd.Timestamp(bucket["data_asof"]):
            raise ValueError("Distribution period ends after artifact date")
        if sum(item["count"] for item in bucket["histogram"]) != bucket["sample_count"]:
            raise ValueError("Distribution histogram count mismatch")
        previous = high
    if previous != 1:
        raise ValueError("Distribution buckets must cover score 1")
    if "historical_cohorts_file" in manifest:
        relative = Path(manifest["historical_cohorts_file"])
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError("Historical cohort path must stay inside its directory")
        historical_path = manifest_path.parent / relative
        if sha256_file(historical_path) != manifest.get("historical_cohorts_sha256"):
            raise ValueError("Historical cohort SHA-256 mismatch")
        historical = json.loads(historical_path.read_text(encoding="utf-8"))
        if historical.get("horizon_days") != manifest["horizon_days"]:
            raise ValueError("Historical cohort horizon mismatch")
    return manifest, files["model"], artifact


def distribution_for_score(artifact, score):
    for bucket in artifact["buckets"]:
        low = bucket["score_bucket"]["low"]
        high = bucket["score_bucket"]["high"]
        if low <= score < high or (score == 1 and high == 1):
            return bucket
    raise ValueError("No empirical distribution bucket covers this score")


def create_signal_release(input_manifest, horizon, ledger_dir, data_dir, config_path,
                          feature_report_path=None):
    """Promote only a fully restored seven-fold ledger to an immutable release."""
    import shutil

    from serving.artifacts import validate_manifest
    from serving.cohorts import POLICY_ID

    validate_manifest(input_manifest)
    item = input_manifest["horizons"][str(horizon)]
    ledger_dir, data_dir = Path(ledger_dir), Path(data_dir)
    outputs = ledger_dir / f"oos_outputs_h{horizon}.parquet"
    cases = ledger_dir / f"cases_h{horizon}.parquet"
    excluded = ledger_dir / f"excluded_h{horizon}.csv"
    if not all(path.is_file() for path in (outputs, cases, excluded)):
        raise FileNotFoundError("OOS outputs, completed cases and exclusions are required")
    restored = pd.read_parquet(outputs, columns=["Code", "Date", "fold"])
    ledger = pd.read_parquet(cases, columns=["Code", "Date", "horizon", "fold", "policy_id"])
    audit = pd.read_csv(excluded)
    expected = sum(fold["prediction_rows"] for fold in item["folds"])
    if len(restored) != expected or len(ledger) + len(audit) != expected:
        raise ValueError("Partial OOS reconstruction cannot be promoted")
    if ledger.empty or ledger.duplicated(["Code", "Date", "horizon"]).any():
        raise ValueError("Empty or duplicate case ledger")
    if not ledger.horizon.eq(horizon).all() or not ledger.policy_id.eq(POLICY_ID).all():
        raise ValueError("Ledger policy/horizon mismatch")
    if set(ledger.fold) != set(range(7)):
        raise ValueError("Every fold must contribute completed cases")
    config_hash = sha256_file(config_path)
    model = Path(item["folds"][-1]["model_file"])
    feature_report = None
    if feature_report_path is not None:
        feature_report = json.loads(Path(feature_report_path).read_text())
        if (feature_report.get("status") != "passed" or feature_report.get("rows_compared", 0) < 1
            or feature_report.get("model_sha256") != sha256_file(model)
            or feature_report.get("feature_names_sha256") != item["feature_names_sha256"]):
            raise ValueError("Feature parity report does not match release")
    audit_hash = sha256_file(feature_report_path) if feature_report_path is not None else "unverified"
    release_digest = hashlib.sha256((sha256_file(model) + sha256_file(cases) +
                                     config_hash + audit_hash).encode()).hexdigest()[:16]
    release_id = f"h{horizon}-{release_digest}"
    release_dir = data_dir / "releases" / release_id
    if release_dir.exists():
        existing, *_ = load_signal_release(release_dir / "manifest.json")
        if existing["release_id"] != release_id:
            raise ValueError("Release directory collision")
        return release_dir / "manifest.json"
    release_dir.mkdir(parents=True)
    shutil.copyfile(model, release_dir / "model.txt")
    shutil.copyfile(cases, release_dir / "cases.parquet")
    shutil.copyfile(config_path, release_dir / "config.yaml")
    manifest = {
        "contract": "chart_signal_detail_v1", "release_id": release_id,
        "horizon": horizon, "profile": item["profile"], "policy_id": POLICY_ID,
        "training_policy": item["training_policy"], "training_end": item["folds"][-1]["train_end"],
        "reference_start": "2019-01-01", "reference_end": "2025-12-31",
        "model_file": "model.txt", "model_sha256": sha256_file(release_dir / "model.txt"),
        "cases_file": "cases.parquet", "cases_sha256": sha256_file(release_dir / "cases.parquet"),
        "config_file": "config.yaml", "config_sha256": config_hash,
        "feature_names": item["feature_names"],
        "features_sha256": item["feature_names_sha256"],
        "feature_barriers": item["feature_barriers"], "label_barriers": item["label_barriers"],
        "folds": item["folds"], "prediction_sha256": item["prediction_sha256"],
        "restored_sha256": sha256_file(outputs), "excluded_sha256": sha256_file(excluded),
        "case_count": len(ledger), "excluded_count": len(audit),
        "feature_equivalence": "unverified",
    }
    if feature_report is not None:
        shutil.copyfile(feature_report_path, release_dir / "feature_report.json")
        manifest["feature_equivalence"] = "passed"
        manifest["feature_report_file"] = "feature_report.json"
        manifest["feature_report_sha256"] = sha256_file(release_dir / "feature_report.json")
    destination = release_dir / "manifest.json"
    destination.write_text(json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2) + "\n")
    load_signal_release(destination)
    return destination


def load_signal_release(manifest_path):
    manifest_path = Path(manifest_path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("contract") != "chart_signal_detail_v1" or manifest.get("horizon") not in (5, 20):
        raise ValueError("Unsupported signal release")
    if manifest.get("profile") != ("aggressive" if manifest["horizon"] == 5 else "stable"):
        raise ValueError("Release profile mismatch")
    files = []
    for key in ("model", "cases", "config"):
        relative = Path(manifest[f"{key}_file"])
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError("Release path escapes directory")
        path = manifest_path.parent / relative
        if sha256_file(path) != manifest[f"{key}_sha256"]:
            raise ValueError(f"Release {key} hash mismatch")
        if key != "config":
            files.append(path)
    import lightgbm as lgb

    model = lgb.Booster(model_file=str(files[0]))
    if model.num_model_per_iteration() != 3 or model.feature_name() != manifest["feature_names"]:
        raise ValueError("Release model class count or feature order mismatch")
    feature_hash = hashlib.sha256(json.dumps(manifest["feature_names"]).encode()).hexdigest()
    if feature_hash != manifest["features_sha256"]:
        raise ValueError("Release feature list hash mismatch")
    if manifest.get("feature_equivalence") == "passed":
        relative = Path(manifest["feature_report_file"])
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError("Feature report path escapes release")
        report_file = manifest_path.parent / relative
        if sha256_file(report_file) != manifest.get("feature_report_sha256"):
            raise ValueError("Feature report hash mismatch")
        report = json.loads(report_file.read_text())
        if (report.get("status") != "passed" or report.get("rows_compared", 0) < 1
            or report.get("model_sha256") != manifest["model_sha256"]
            or report.get("feature_names_sha256") != manifest["features_sha256"]):
            raise ValueError("Feature report does not match release")
    return manifest, *files


def activate_signal_release(manifest_path, data_dir):
    manifest, _, _ = load_signal_release(manifest_path)
    if manifest.get("feature_equivalence") != "passed":
        raise ValueError("Cannot activate release without feature parity evidence")
    data_dir = Path(data_dir)
    expected = data_dir / "releases" / manifest["release_id"] / "manifest.json"
    if Path(manifest_path).resolve() != expected.resolve():
        raise ValueError("Release must be inside CHART_SERVING_DATA_DIR")
    pointer = data_dir / "releases" / f"active_h{manifest['horizon']}.json"
    temporary = pointer.with_suffix(".json.tmp")
    temporary.write_text(json.dumps({"release_id": manifest["release_id"]}) + "\n")
    temporary.replace(pointer)


def main(argv=None):
    import argparse
    import os

    parser = argparse.ArgumentParser(description="Create or activate H5/H20 signal releases")
    parser.add_argument("--manifest", type=Path, help="Audited seven-fold input manifest")
    parser.add_argument("--horizon", type=int, choices=(5, 20))
    parser.add_argument("--ledger-dir", type=Path)
    parser.add_argument("--feature-report", type=Path)
    parser.add_argument("--activate", type=Path, help="Activate a verified release manifest")
    args = parser.parse_args(argv)
    data_dir = os.environ.get("CHART_SERVING_DATA_DIR")
    if not data_dir:
        parser.error("CHART_SERVING_DATA_DIR is required")
    if args.activate:
        activate_signal_release(args.activate, data_dir)
        print(args.activate)
        return
    if not args.manifest or not args.horizon or not args.ledger_dir:
        parser.error("--manifest, --horizon and --ledger-dir are required")
    manifest = json.loads(args.manifest.read_text())
    config = Path(__file__).parent / "config.yaml"
    print(create_signal_release(manifest, args.horizon, args.ledger_dir, data_dir,
                                config, args.feature_report))


if __name__ == "__main__":
    main()
