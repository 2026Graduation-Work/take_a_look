"""Validate an immutable H5/H20 model pack and download its release archive."""

import json
import os
import re
import shutil
import tarfile
import tempfile
import urllib.request
from pathlib import Path

import lightgbm as lgb
import pandas as pd
import yaml

from .hashing import sha256_file
from .samples import build_samples

FORMAT_VERSION = 1
BUILDER_ID = "alpha158_actual_vwap_v1"


def load_pack(path):
    root = Path(path)
    manifest = json.loads((root / "manifest.json").read_text())
    if manifest.get("format_version") != FORMAT_VERSION or not manifest.get("pack_id") or root.name != manifest["pack_id"]:
        raise ValueError("Pack identity or format mismatch")
    if manifest.get("feature_builder_id") != BUILDER_ID:
        raise ValueError("Unsupported feature builder")
    if set(manifest.get("horizons", {})) != {"h5", "h20"}:
        raise ValueError("Pack must contain H5 and H20")
    paths = {}
    for horizon in (5, 20):
        item = manifest["horizons"][f"h{horizon}"]
        if item["horizon"] != horizon or item["classes"] != {"down": 0, "neutral": 1, "up": 2}:
            raise ValueError("Horizon/class mapping mismatch")
        if item["profile"] != ("aggressive" if horizon == 5 else "stable"):
            raise ValueError("Profile/horizon mismatch")
        checked = []
        for kind in ("model", "samples"):
            relative = Path(item[f"{kind}_file"])
            if relative.is_absolute() or ".." in relative.parts or relative.parts[0] != f"h{horizon}":
                raise ValueError("Unsafe pack file path")
            file = root / relative
            if not file.is_file() or sha256_file(file) != item[f"{kind}_sha256"]:
                raise ValueError(f"Missing or changed H{horizon} {kind} file")
            checked.append(file)
        model = lgb.Booster(model_file=str(checked[0]))
        if model.num_model_per_iteration() != 3 or model.feature_name() != item["feature_names"]:
            raise ValueError("Model feature order or class count mismatch")
        sample_horizons = pd.read_parquet(checked[1], columns=["horizon"])["horizon"].unique().tolist()
        if sample_horizons != [horizon]:
            raise ValueError("Historical samples mixed or swapped H5/H20")
        paths[horizon] = tuple(checked)
    return manifest, paths


def download(config_file):
    config = yaml.safe_load(Path(config_file).read_text())["active_pack"]
    pack_id, tag, asset, expected = (config[k] for k in ("pack_id", "release_tag", "asset_name", "sha256"))
    if not all((pack_id, tag, asset, expected)) or len(expected) != 64:
        raise ValueError("Active pack release configuration is incomplete")
    if not re.fullmatch(r"[A-Za-z0-9_-]+", pack_id) or not re.fullmatch(r"[A-Za-z0-9._-]+", asset) or not re.fullmatch(r"[A-Fa-f0-9]{64}", expected):
        raise ValueError("Unsafe pack identity or asset name")
    root = Path(os.environ.get("CHART_SERVING_DATA_DIR", Path(__file__).parents[1] / "data"))
    destination = root / "packs" / pack_id
    if destination.exists():
        load_pack(destination)
        return destination
    repository = os.environ.get("GITHUB_REPOSITORY")
    if not repository:
        raise ValueError("GITHUB_REPOSITORY required to download a release pack")
    url = f"https://api.github.com/repos/{repository}/releases/tags/{tag}"
    headers = {"Accept": "application/vnd.github+json", "User-Agent": "chart-serving"}
    token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=30) as response:
        release = json.load(response)
    matches = [item for item in release["assets"] if item["name"] == asset]
    if len(matches) != 1:
        raise ValueError("Configured pack asset missing from release")
    headers["Accept"] = "application/octet-stream"
    request = urllib.request.Request(matches[0]["url"], headers=headers)
    archive = root / "packs" / asset
    archive.parent.mkdir(parents=True, exist_ok=True)
    with urllib.request.urlopen(request, timeout=120) as response, archive.open("wb") as target:
        while chunk := response.read(1024 * 1024):
            target.write(chunk)
    if sha256_file(archive) != expected:
        archive.unlink()
        raise ValueError("Pack archive SHA-256 mismatch")
    with tempfile.TemporaryDirectory(dir=root / "packs") as temporary:
        with tarfile.open(archive, "r:gz") as tar:
            members = tar.getmembers()
            if any(member.issym() or member.islnk() or (not member.isfile() and not member.isdir())
                   or Path(member.name).is_absolute() or ".." in Path(member.name).parts
                   or Path(member.name).parts[0] != pack_id for member in members):
                raise ValueError("Unsafe pack archive")
            tar.extractall(temporary, filter="data")
        load_pack(Path(temporary) / pack_id)
        (Path(temporary) / pack_id).replace(destination)
    load_pack(destination)
    return destination



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
