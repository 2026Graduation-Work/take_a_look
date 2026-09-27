"""Build a serving release from an audited OOS sample file and model cache."""

import argparse
import json
from pathlib import Path

import lightgbm as lgb
import pandas as pd

from .distribution import build_distribution
from .release import sha256_file


def create_release(*, model_path, oos_path, release_id, profile, horizon_days,
                   as_of, output_dir, edges, up_mult, down_mult, min_samples=100,
                   allow_sparse=False):
    """Write metadata only after every score bucket has mature empirical samples."""
    model_path = Path(model_path).resolve()
    oos_path = Path(oos_path)
    output_dir = Path(output_dir).resolve()
    if model_path.parent != output_dir:
        raise ValueError("Model cache must be inside the release directory")
    if not release_id or not release_id.strip():
        raise ValueError("Release ID is required")
    if profile not in {"stable", "aggressive"}:
        raise ValueError("Invalid profile")
    if up_mult <= 0 or down_mult <= 0:
        raise ValueError("Barrier multipliers must be positive")
    if edges[0] != 0 or edges[-1] != 1 or any(
        low >= high for low, high in zip(edges[:-1], edges[1:])
    ):
        raise ValueError("Score edges must increase from 0 to 1")
    model = lgb.Booster(model_file=str(model_path))
    if model.num_model_per_iteration() != 3:
        raise ValueError("Only three-class models are supported")
    samples = pd.read_csv(oos_path, dtype={"code": str})
    buckets = []
    for low, high in zip(edges[:-1], edges[1:]):
        bucket = build_distribution(
            samples, as_of=as_of, model_version=release_id,
            horizon_days=horizon_days, score_low=low, score_high=high,
            min_samples=min_samples,
        )
        if bucket["status"] != "available" and not allow_sparse:
            raise ValueError(f"Insufficient OOS samples for score bucket [{low}, {high}]")
        buckets.append(bucket)
    artifact = {"release_id": release_id, "profile": profile,
                "horizon_days": horizon_days, "buckets": buckets,
                "oos_sha256": sha256_file(oos_path)}
    distribution_path = output_dir / "distribution.json"
    manifest_path = output_dir / "release.json"
    distribution_path.write_text(
        json.dumps(artifact, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    manifest = {"release_id": release_id, "profile": profile,
                "horizon_days": horizon_days, "model_file": model_path.name,
                "model_sha256": sha256_file(model_path),
                "feature_names": model.feature_name(),
                "allow_sparse_distribution": allow_sparse,
                "label_rule": {"type": "dynamic_sigma", "sigma_window": 20,
                               "up_mult": up_mult, "down_mult": down_mult,
                               "up_observation": "high", "down_observation": "close",
                               "same_day_tie": "down", "halt_clock": "traded_days"},
                "distribution_file": distribution_path.name,
                "distribution_sha256": sha256_file(distribution_path)}
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    return manifest_path


def main(argv=None):
    parser = argparse.ArgumentParser(description="Build a chart serving release")
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--oos", type=Path, required=True, help="Audited OOS CSV")
    parser.add_argument("--release-id", required=True)
    parser.add_argument("--profile", choices=["stable", "aggressive"], required=True)
    parser.add_argument("--horizon-days", type=int, required=True)
    parser.add_argument("--up-mult", type=float, required=True)
    parser.add_argument("--down-mult", type=float, required=True)
    parser.add_argument("--as-of", required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--score-edges", default="0,0.2,0.4,0.6,0.8,1")
    parser.add_argument("--min-samples", type=int, default=100)
    args = parser.parse_args(argv)
    edges = [float(value) for value in args.score_edges.split(",")]
    path = create_release(
        model_path=args.model, oos_path=args.oos, release_id=args.release_id,
        profile=args.profile, horizon_days=args.horizon_days, as_of=args.as_of,
        output_dir=args.out_dir, edges=edges, min_samples=args.min_samples,
        up_mult=args.up_mult, down_mult=args.down_mult,
    )
    print(f"Built release: {path}")


if __name__ == "__main__":
    main()
