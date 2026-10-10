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
