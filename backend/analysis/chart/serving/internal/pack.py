"""Validate an immutable H5/H20 model pack and download its release archive."""

import json
import os
import re
import tarfile
import tempfile
import urllib.request
from pathlib import Path

import lightgbm as lgb
import pandas as pd
import yaml
from shared.settings import BUILDER_ID as LOCAL_BUILDER_ID
from shared.settings import processing_contract, serving_root

from .hashing import sha256_file

FORMAT_VERSION = 2
BUILDER_ID = LOCAL_BUILDER_ID


def load_pack(path):
    root = Path(path)
    manifest = json.loads((root / "manifest.json").read_text())
    if manifest.get("format_version") != FORMAT_VERSION or not manifest.get("pack_id") or root.name != manifest["pack_id"]:
        raise ValueError("Pack identity or format mismatch")
    validate_builder(manifest)
    if set(manifest.get("horizons", {})) != {"h5", "h20"}:
        raise ValueError("Pack must contain H5 and H20")
    if manifest.get("calendar_sha256") and sha256_file(root / "calendar.json") != manifest["calendar_sha256"]:
        raise ValueError("Pack calendar checksum mismatch")
    expected_sources = manifest["processing_contract"]["implementation_sha256"]
    if set(manifest.get("builder_sources", {})) != set(expected_sources):
        raise ValueError("Pack builder sources missing")
    for name, digest in expected_sources.items():
        relative = Path(manifest["builder_sources"][name])
        if relative.is_absolute() or ".." in relative.parts or relative.parts[0] != "builder":
            raise ValueError("Unsafe builder source path")
        if sha256_file(root / relative) != digest:
            raise ValueError("Pack builder source checksum mismatch")
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
    root = serving_root()
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



def validate_builder(manifest):
    if manifest.get("feature_builder_id") != LOCAL_BUILDER_ID or manifest.get("processing_contract") != processing_contract():
        raise ValueError("Pack/shared builder settings or implementation checksum mismatch")


def config_path():
    configured = os.environ.get("CHART_SERVING_CONFIG")
    if configured:
        return Path(configured)
    local = Path(__file__).parents[1] / "config.local.yaml"
    return local if local.is_file() else Path(__file__).parents[1] / "config.yaml"
