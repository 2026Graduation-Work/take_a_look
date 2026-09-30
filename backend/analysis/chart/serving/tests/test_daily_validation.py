from argparse import Namespace
from datetime import datetime

import pytest
from serving import publish_preview, run_daily
from serving.internal import pipeline


@pytest.mark.parametrize("hour,expected", [(1, "2026-09-29"), (19, "2026-09-30")])
def test_confirmed_day_handles_delayed_schedule(monkeypatch, hour, expected):
    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return cls(2026, 9, 30, hour, tzinfo=tz)
    monkeypatch.setattr(pipeline, "datetime", Clock)
    assert pipeline.official_day() == expected


@pytest.mark.parametrize("replay", [False, True])
def test_past_date_only_replays_when_requested(monkeypatch, tmp_path, replay):
    monkeypatch.setenv("CHART_SERVING_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(pipeline, "active_pack", lambda *_: ({"pack_id": "test"}, {}))
    monkeypatch.setattr(pipeline, "SupabaseStore", lambda: object())
    calls = []
    def collect(*args, **kwargs):
        calls.append(kwargs["replay"])
        return None
    monkeypatch.setattr(pipeline, "collect", collect)
    pipeline.run(Namespace(as_of="2026-09-21", replay=replay, historical_test=False, publish=False, dry_run=True))
    assert calls == [replay]


def test_replay_requires_date():
    with pytest.raises(SystemExit):
        run_daily.main(["--replay", "--dry-run"])


def test_preview_validates_both_horizons_and_never_publishes_by_default(monkeypatch):
    batch, snapshots, _ = publish_preview.load_preview()
    assert batch["as_of"] == "2026-09-21"
    assert {s["horizon"] for s in snapshots} == {5, 20}
    monkeypatch.setattr(publish_preview, "SupabaseStore", lambda: pytest.fail("unexpected database access"))
    publish_preview.main([])


def test_preview_rejects_modified_provenance(monkeypatch, tmp_path):
    import json
    batch, snapshots, _ = publish_preview.load_preview()
    snapshots[0]["sources"]["model_sha256"] = "0" * 64
    (tmp_path / "batch.json").write_text(json.dumps(batch))
    (tmp_path / "snapshots.json").write_text(json.dumps(snapshots))
    with pytest.raises(ValueError, match="provenance"):
        publish_preview.load_preview(tmp_path)


def test_missing_krx_secrets_fail_before_import(monkeypatch):
    from serving.internal.krx import authenticated_stock
    monkeypatch.delenv("KRX_ID", raising=False)
    with pytest.raises(ValueError, match="KRX_ID"):
        authenticated_stock()
