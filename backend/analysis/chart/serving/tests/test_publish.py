import copy
import json
from pathlib import Path

import pytest
from serving import publish as publisher


def fixtures():
    first = json.loads((Path(__file__).parents[1] / "contracts/examples/normal.json").read_text())
    second = copy.deepcopy(first)
    second.update(horizon=20, profile="stable", release_id="r20")
    first["release_id"] = "r5"
    first["batch_id"] = second["batch_id"] = "batch"
    release = {"horizon": 5, "release_id": "r5", "profile": "aggressive", "policy_id": first["cases"]["policy_id"],
               "model_sha256": "0" * 64, "features_sha256": "0" * 64,
               "cases_sha256": "0" * 64, "config_sha256": "0" * 64}
    other = dict(release, horizon=20, release_id="r20", profile="stable")
    batch = {"id": "batch", "as_of": first["data_asof"], "release_h5": "r5",
             "release_h20": "r20", "expected_stock_codes": [first["stock_code"]],
             "status": "staging", "result": {"snapshot_count": 2}}
    return batch, [first, second], [release, other]


def test_partial_upload_never_calls_publish_rpc(monkeypatch):
    calls = []

    def request(method, path, body=None, **kwargs):
        calls.append(path)
        if method == "GET":
            return []
        if path.startswith("chart_signal_snapshots"):
            raise RuntimeError("upload failed")
        return None

    monkeypatch.setattr(publisher, "_request", request)
    with pytest.raises(RuntimeError, match="upload failed"):
        publisher.publish(*fixtures())
    assert "rpc/publish_chart_batch" not in calls


def test_complete_upload_publishes_after_snapshots(monkeypatch):
    calls = []

    def request(method, path, body=None, **kwargs):
        calls.append(path)
        return [] if method == "GET" else None

    monkeypatch.setattr(publisher, "_request", request)
    publisher.publish(*fixtures())
    assert calls.index("rpc/publish_chart_batch") > next(
        index for index, path in enumerate(calls) if path.startswith("chart_signal_snapshots"))


def test_published_batch_replay_is_idempotent(monkeypatch):
    batch, snapshots, releases = fixtures()
    calls = []

    def request(method, path, body=None, **kwargs):
        calls.append(path)
        return [{"status": "published", "result": {"payload_sha256": publisher.canonical_hash(snapshots)}}]

    monkeypatch.setattr(publisher, "_request", request)
    publisher.publish(batch, snapshots, releases)
    assert len(calls) == 1 and calls[0].startswith("chart_batches?")


def test_withdraw_uses_service_rpc(monkeypatch):
    calls = []
    monkeypatch.setattr(publisher, "_request", lambda method, path, body=None: calls.append((method, path, body)))
    publisher.withdraw("batch")
    assert calls == [("POST", "rpc/withdraw_chart_batch", {"p_batch_id": "batch"})]
