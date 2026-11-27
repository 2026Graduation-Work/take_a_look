import hashlib
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
from shared.golden import GoldenError, check_coverage, compare
from shared.settings import BUILDER_ID as LOCAL_BUILDER_ID
from shared.settings import serving_contract, serving_root

from .hashing import canonical_hash, sha256_file

FORMAT_VERSION = 2
BUILDER_ID = LOCAL_BUILDER_ID
SERVING_DIR = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = SERVING_DIR / "config.yaml"


def load_pack(path, *, golden_sha256=None):
    root = Path(path)
    manifest = json.loads((root / "manifest.json").read_text())
    pack_id = manifest.get("pack_id")
    if (manifest.get("format_version") != FORMAT_VERSION or not isinstance(pack_id, str)
            or not re.fullmatch(r"[A-Za-z0-9_-]+", pack_id) or root.name != pack_id):
        raise ValueError("Pack identity or format mismatch")
    validate_builder(manifest)
    if set(manifest.get("horizons", {})) != {"h5", "h20"}:
        raise ValueError("Pack must contain H5 and H20")
    if manifest.get("calendar_sha256") and sha256_file(root / "calendar.json") != manifest["calendar_sha256"]:
        raise ValueError("Pack calendar checksum mismatch")
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
    digest = _validate_golden(root, manifest, golden_sha256)
    return manifest, paths, digest


def _validate_golden(root, manifest, configured_digest):
    pack_id = manifest["pack_id"]
    manifest_digest = manifest.get("golden_sha256")
    if configured_digest is not None and manifest_digest is not None and configured_digest != manifest_digest:
        raise GoldenError(f"{pack_id}: configured and manifest golden checksums differ")
    digest = configured_digest or manifest_digest
    path = SERVING_DIR / "golden" / f"{pack_id}.json"
    if manifest_digest is not None and not path.is_file():
        path = root / "golden" / f"{pack_id}.json"
    if not path.is_file():
        raise GoldenError(f"{pack_id}: missing golden file {path}")
    if digest is None:
        for config in dict.fromkeys((config_path(), DEFAULT_CONFIG)):
            active = yaml.safe_load(config.read_text())["active_pack"]
            if active["pack_id"] == pack_id and active.get("golden_sha256"):
                digest = active["golden_sha256"]
                break
    if not digest:
        raise GoldenError(f"{pack_id}: missing golden checksum in active pack configuration or manifest")
    data = path.read_bytes()
    if hashlib.sha256(data).hexdigest() != digest:
        raise GoldenError(f"{pack_id}: golden checksum mismatch")
    golden = json.loads(data)
    contract = serving_contract()
    if golden.get("pack_id") != pack_id or any(
        golden.get(key) != contract[key] for key in ("builder_id", "price_basis", "preprocessing")
    ):
        raise GoldenError(f"{pack_id}: golden identity or builder settings mismatch")
    model_features = {name for horizon in manifest["horizons"].values() for name in horizon["feature_names"]}
    check_coverage(golden, model_features)
    compare(golden, model_features)
    return digest


def feature_cache_key(golden_sha256):
    return canonical_hash({**serving_contract(), "golden_sha256": golden_sha256})


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
        load_pack(destination, golden_sha256=config.get("golden_sha256"))
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
        load_pack(Path(temporary) / pack_id, golden_sha256=config.get("golden_sha256"))
        (Path(temporary) / pack_id).replace(destination)
    return destination


def validate_builder(manifest):
    contract = manifest.get("processing_contract", {})
    if manifest.get("feature_builder_id") != LOCAL_BUILDER_ID or any(
        contract.get(key) != expected for key, expected in serving_contract().items()
    ):
        raise ValueError("Pack/shared builder settings mismatch")


def config_path():
    configured = os.environ.get("CHART_SERVING_CONFIG")
    if configured:
        return Path(configured)
    local = SERVING_DIR / "config.local.yaml"
    return local if local.is_file() else DEFAULT_CONFIG
