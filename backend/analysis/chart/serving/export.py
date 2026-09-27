"""Run from chart/: python -m serving.export --help."""

import argparse
import hashlib
from pathlib import Path

import numpy as np
import pandas as pd

from .output import predict_snapshot, price_snapshot, rank_predictions, write_artifact
from .release import distribution_for_score, load_release, sha256_file

file_sha256 = sha256_file


def build_signal_snapshot(*, code, as_of, batch_id, release_path, raw_path,
                          processed_path, ledger, price_source, release=None,
                          prediction=None, current=None, stock_name=None):
    """Build one independently validated public H5/H20 snapshot."""
    from serving.barriers import MULTIPLIERS
    from serving.cohorts import POLICY_ID, matching_cases
    from serving.contracts import validate_snapshot
    from serving.inference import infer
    from serving.release import load_signal_release

    manifest, model_path, _ = release or load_signal_release(release_path)
    horizon = manifest["horizon"]
    if code != Path(raw_path).stem or code != Path(processed_path).stem:
        raise ValueError("Stock code and input paths disagree")
    raw = pd.read_parquet(raw_path)
    price = price_snapshot(raw, code, as_of, price_source)
    if price["status"] != "available":
        raise ValueError(f"Stale adjusted price: {code}, {price['data_asof']} != {as_of}")
    processed = None if current is not None else pd.read_parquet(processed_path)
    if current is None:
        selected = processed.loc[pd.to_datetime(processed.Date).eq(pd.Timestamp(as_of))]
        if len(selected) != 1:
            raise ValueError(f"Missing or duplicate feature row: {code}/{as_of}")
        row = selected.iloc[0]
    else:
        row = current
    sigma, close = float(row["Sigma"]), float(row["Close"])
    if not pd.notna(sigma) or sigma < 0 or not pd.notna(close) or close <= 0:
        raise ValueError("Invalid current Sigma or adjusted close")
    if not pd.notna(price["close"]) or not np.isclose(close, price["close"]):
        raise ValueError("Raw and processed adjusted close disagree")
    scores, features, feature_hash = prediction or infer(model_path, processed, as_of)
    _, cases = matching_cases(ledger, code=code, horizon=horizon,
                              up=scores["up"], down=scores["down"], sigma=sigma,
                              as_of=as_of, policy_id=POLICY_ID)
    up_mult, down_mult = MULTIPLIERS[horizon]
    snapshot = {
        "contract": "chart_signal_detail_v1", "stock_code": code,
        "stock_name": stock_name or code,
        "data_asof": as_of, "horizon": horizon,
        "profile": manifest["profile"], "release_id": manifest["release_id"],
        "batch_id": batch_id,
        "inference": {"status": "available", "reason": None, "scores": scores,
                      "score_event": "class_2_upper_barrier_first", "close": close,
                      "sigma": sigma,
                      "barriers": {"up": close * (1 + up_mult * sigma),
                                   "down": close * (1 - down_mult * sigma)},
                      "contribution_space": "class_2_raw_margin", "features": features},
        "cases": cases,
        "prices": {"basis": "adjusted_close", "source": price_source,
                   "history": price["history"]},
        "sources": {"model_sha256": manifest["model_sha256"],
                    "features_sha256": feature_hash,
                    "prices_sha256": file_sha256(raw_path),
                    "cases_sha256": manifest["cases_sha256"],
                    "config_sha256": manifest["config_sha256"]},
    }
    return validate_snapshot(snapshot)


def unavailable_signal_snapshot(*, code, as_of, batch_id, manifest, reason, stock_name=None):
    """Explicit per-stock failure; the batch can still disclose all expected keys."""
    from serving.cohorts import POLICY_ID, TOLERANCES
    from serving.contracts import validate_snapshot

    return validate_snapshot({
        "contract": "chart_signal_detail_v1", "stock_code": code,
        "stock_name": stock_name or code, "data_asof": as_of,
        "horizon": manifest["horizon"], "profile": manifest["profile"],
        "release_id": manifest["release_id"], "batch_id": batch_id,
        "inference": {"status": "unavailable", "reason": reason, "scores": None,
                      "score_event": "class_2_upper_barrier_first", "close": None,
                      "sigma": None, "barriers": None,
                      "contribution_space": "class_2_raw_margin", "features": []},
        "cases": {"status": "unavailable", "reason": "inference_unavailable",
                  "policy_id": POLICY_ID, "current": None, "tolerances": TOLERANCES,
                  "sample_count": 0, "up_count": 0, "down_count": 0,
                  "both_count": 0, "neither_count": 0,
                  "up_rate": None, "down_rate": None, "period_start": None,
                  "period_end": None, "observed_through": None, "by_fold": {}, "by_year": {}},
        "prices": {"basis": "adjusted_close", "source": "unavailable", "history": []},
        "sources": {"model_sha256": manifest["model_sha256"],
                    "features_sha256": None, "prices_sha256": None,
                    "cases_sha256": manifest["cases_sha256"],
                    "config_sha256": manifest["config_sha256"]},
    })


def main(argv=None):
    parser = argparse.ArgumentParser(description="Export chart detail preview JSON")
    parser.add_argument("--raw-dir", type=Path, required=True)
    parser.add_argument("--codes", required=True, help="Explicit comma-separated universe")
    parser.add_argument("--as-of", required=True, help="Explicit YYYY-MM-DD trading date")
    parser.add_argument("--price-source", required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--processed-dir", type=Path)
    parser.add_argument("--registry", type=Path)
    parser.add_argument("--profile", choices=["stable", "aggressive"])
    parser.add_argument("--feature-version", help="Identifier of the selected feature snapshot")
    parser.add_argument("--release", type=Path, help="Validated release manifest JSON")
    args = parser.parse_args(argv)
    options = [args.processed_dir, args.registry, args.profile, args.feature_version]
    if args.release and (args.registry or args.profile or args.feature_version):
        parser.error("Release cannot be combined with registry, profile or feature-version")
    if args.release and not args.processed_dir:
        parser.error("Release requires processed-dir")
    if not args.release and any(options) and not all(options):
        parser.error("Inference requires processed-dir, registry, profile and feature-version")
    codes = sorted(set(code.strip() for code in args.codes.split(",")))
    if not codes or any(len(code) != 6 or not code.isalnum() for code in codes):
        parser.error("Codes must be six alphanumeric characters")
    model = None
    metadata = None
    distribution_artifact = None
    if args.release:
        import lightgbm as lgb

        manifest, model_path, distribution_artifact = load_release(args.release)
        historical_artifact = None
        if manifest.get("historical_cohorts_file"):
            import json
            historical_artifact = json.loads((args.release.parent / manifest["historical_cohorts_file"]).read_text())
        cutoff = pd.Timestamp(args.as_of).normalize()
        if any(pd.Timestamp(bucket["data_asof"]).normalize() > cutoff
               for bucket in distribution_artifact["buckets"]):
            raise ValueError("Distribution artifact is newer than prediction date")
        if historical_artifact and pd.Timestamp(historical_artifact["data_asof"]) > cutoff:
            raise ValueError("Historical artifact is newer than prediction date")
        model = lgb.Booster(model_file=str(model_path))
        if model.feature_name() != manifest["feature_names"]:
            raise ValueError("Model feature names/order differ from release manifest")
        if model.num_model_per_iteration() != 3:
            raise ValueError("Release model must have three classes")
        metadata = {"release_id": manifest["release_id"], "profile": manifest["profile"],
                    "horizon_days": manifest["horizon_days"],
                    "sha256": manifest["model_sha256"],
                    "distribution_sha256": manifest["distribution_sha256"],
                    "manifest_sha256": file_sha256(args.release)}
        if historical_artifact:
            metadata["historical_cohorts_sha256"] = manifest["historical_cohorts_sha256"]
    elif args.registry:
        import lightgbm as lgb
        import yaml
        from core.inference import FEATURE_COLS

        registry = yaml.safe_load(args.registry.read_text(encoding="utf-8"))
        entry = registry["models"][args.profile]
        path = args.registry.parent / entry["model_file"]
        digest = file_sha256(path)
        if digest != entry["sha256"]:
            raise ValueError("Model SHA-256 mismatch")
        if entry["classes"] != {"down": 0, "neutral": 1, "up": 2}:
            raise ValueError("Unsupported class mapping")
        model = lgb.Booster(model_file=str(path))
        names = model.feature_name()
        if names != FEATURE_COLS:
            raise ValueError("Model feature names/order differ from the inference contract")
        feature_hash = hashlib.sha256(
            "\n".join(names).encode("utf-8")
        ).hexdigest()
        metadata = {"profile": args.profile, "horizon_days": entry["horizon_days"],
                    "sha256": digest, "registry_entry": entry,
                    "registry_sha256": file_sha256(args.registry),
                    "feature_contract_sha256": feature_hash,
                    "feature_version": args.feature_version}
    prices, predictions = [], []
    input_files = []
    # Fail the whole export on any missing/bad input; never silently shrink rank universe.
    for code in codes:
        raw_path = args.raw_dir / f"{code}.parquet"
        prices.append(price_snapshot(pd.read_parquet(raw_path),
                                     code, args.as_of, args.price_source))
        provenance = {"code": code, "raw_sha256": file_sha256(raw_path)}
        if model is not None:
            if prices[-1]["status"] != "available":
                raise ValueError(f"Stale price for prediction: {code}")
            processed_path = args.processed_dir / f"{code}.parquet"
            processed = pd.read_parquet(processed_path)
            predictions.append(predict_snapshot(
                model, processed, code, args.as_of,
                allow_missing=bool(args.release and manifest.get("missing_policy") == "native_nan"),
            ))
            if distribution_artifact is not None:
                predictions[-1]["return_distribution"] = distribution_for_score(
                    distribution_artifact, predictions[-1]["scores"]["up"]
                )
                if historical_artifact is not None:
                    from pipeline.research import cohort_for
                    sigma = processed.loc[pd.to_datetime(processed.Date).eq(pd.Timestamp(args.as_of)), "Sigma"]
                    predictions[-1]["historical_score_sigma_distribution"] = cohort_for(
                        historical_artifact, predictions[-1]["scores"]["up"], float(sigma.iloc[0])
                    )
            provenance["processed_sha256"] = file_sha256(processed_path)
        input_files.append(provenance)
    write_artifact({
        "format": "chart_detail_preview_v0", "deployment_status": (
            "validated_release_preview" if args.release else "preview_only"
        ),
        "requested_asof": args.as_of, "universe": codes,
        "model": metadata, "input_files": input_files,
        "prices": prices, "predictions": rank_predictions(predictions),
    }, args.out)
    print(f"Exported {len(prices)} prices / {len(predictions)} predictions: {args.out}")


if __name__ == "__main__":
    main()
