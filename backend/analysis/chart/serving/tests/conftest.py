"""Contract tests use preserved metadata without downloading historical models."""
import json
from pathlib import Path

import pytest


@pytest.fixture
def legacy_preview_pack(monkeypatch):
    from serving import publish_preview
    manifest = json.loads((Path(__file__).parent / "fixtures/legacy-preview-pack.json").read_text())
    monkeypatch.setattr(publish_preview, "load_pack", lambda _: (manifest, {}))
    return manifest


@pytest.fixture
def verified_listing_provider(monkeypatch, tmp_path):
    import pandas as pd
    from shared.data import metadata
    codes = [f"{i:06d}" for i in range(499)] + ["00104K", "005930", "00088K"]
    monkeypatch.setattr(metadata, "load_metadata", lambda *_: pd.DataFrame({"Code": codes, "ListingDate": pd.Timestamp("2000-01-01")}))
    monkeypatch.setenv("CHART_SERVING_DATA_DIR", str(tmp_path))
