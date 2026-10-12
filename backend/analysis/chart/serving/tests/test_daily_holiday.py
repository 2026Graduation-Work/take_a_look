from types import SimpleNamespace

import pytest
from serving.internal import pipeline


@pytest.mark.parametrize("as_of", ["2026-10-11", "2026-10-09"])
def test_automatic_closed_session_never_opens_database(monkeypatch, tmp_path, capsys, as_of):
    monkeypatch.setenv("CHART_SERVING_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(pipeline, "official_day", lambda _: as_of)
    monkeypatch.setattr(pipeline, "active_pack", lambda _: ({"pack_id": "flow", "feature_builder_id": pipeline.BUILDER_ID}, {}))

    def forbidden_store():
        pytest.fail("Closed automatic session must not query database archives")

    monkeypatch.setattr(pipeline, "SupabaseStore", forbidden_store)
    pipeline.run(SimpleNamespace(as_of=None, publish=False, dry_run=True, code=None))
    assert '"event": "holiday"' in capsys.readouterr().out


def test_explicit_historical_date_keeps_archive_requirement(monkeypatch, tmp_path):
    monkeypatch.setenv("CHART_SERVING_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(pipeline, "official_day", lambda requested=None: requested or "2026-10-12")  # 최신 확정일은 10-12
    monkeypatch.setattr(pipeline, "active_pack", lambda _: ({"pack_id": "flow", "feature_builder_id": pipeline.BUILDER_ID}, {}))
    monkeypatch.setattr(pipeline, "SupabaseStore", lambda: object())

    def missing_archive(*_, **kwargs):
        assert kwargs["replay"] is True
        raise ValueError("Historical date lacks an archived universe")

    monkeypatch.setattr(pipeline, "collect", missing_archive)
    with pytest.raises(ValueError, match="archived universe"):
        pipeline.run(SimpleNamespace(as_of="2026-10-11", publish=False, dry_run=True, code=None))
