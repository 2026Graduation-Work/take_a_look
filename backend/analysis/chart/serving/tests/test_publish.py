import pytest
from serving.internal import storage
from serving.internal.hashing import canonical_hash
from serving.internal.snapshot import unavailable_snapshot


def fixtures():
    snapshots = [unavailable_snapshot(
        code="005930", stock_name="삼성전자", as_of="2024-01-01", horizon=h,
        pack_id="pack", batch_id="batch", reason="no_prices") for h in (5, 20)]
    releases = [{"horizon": h, "release_id": f"pack:h{h}",
                 "profile": "aggressive" if h == 5 else "stable",
                 "policy_id": "multi_stock_up_sigma_001_005_v1",
                 "model_sha256": "0" * 64, "features_sha256": "0" * 64,
                 "cases_sha256": "0" * 64, "config_sha256": "0" * 64} for h in (5, 20)]
    batch = {"id": "batch", "as_of": "2024-01-01", "pack_id": "pack",
             "release_h5": "pack:h5", "release_h20": "pack:h20",
             "expected_stock_codes": ["005930"], "status": "staging",
             "result": {"snapshot_count": 2}}
    return batch, snapshots, releases


def test_partial_upload_never_calls_publish_rpc(monkeypatch):
    calls = []

    def request(self, method, path, body=None, **kwargs):
        calls.append(path)
        if method == "GET":
            return []
        if path.startswith("/rest/v1/chart_signal_snapshots"):
            raise RuntimeError("upload failed")

    monkeypatch.setattr(storage.SupabaseStore, "_request", request)
    store = storage.SupabaseStore("https://example.supabase.co", "secret")
    with pytest.raises(RuntimeError, match="upload failed"):
        store.publish(*fixtures())
    assert "/rest/v1/rpc/publish_chart_batch" not in calls
    assert any(path.startswith("/rest/v1/chart_batches") for path in calls)


def test_complete_upload_publishes_after_snapshots(monkeypatch):
    calls = []

    def request(self, method, path, body=None, **kwargs):
        calls.append(path)
        return [] if method == "GET" else None

    monkeypatch.setattr(storage.SupabaseStore, "_request", request)
    storage.SupabaseStore("https://example.supabase.co", "secret").publish(*fixtures())
    assert calls.index("/rest/v1/rpc/publish_chart_batch") > next(
        i for i, path in enumerate(calls) if path.startswith("/rest/v1/chart_signal_snapshots"))


def test_published_batch_replay_is_idempotent(monkeypatch):
    batch, snapshots, releases = fixtures()
    calls = []

    def request(self, method, path, body=None, **kwargs):
        calls.append(path)
        return [{"status": "published", "result": {"payload_sha256": canonical_hash(snapshots)}}]

    monkeypatch.setattr(storage.SupabaseStore, "_request", request)
    storage.SupabaseStore("https://example.supabase.co", "secret").publish(batch, snapshots, releases)
    assert len(calls) == 1 and calls[0].startswith("/rest/v1/chart_batches?")


def test_withdraw_uses_service_rpc(monkeypatch):
    calls = []
    monkeypatch.setattr(storage.SupabaseStore, "_request", lambda self, method, path, body=None: calls.append((method, path, body)))
    storage.SupabaseStore("https://example.supabase.co", "secret").withdraw("batch")
    assert calls == [("POST", "/rest/v1/rpc/withdraw_chart_batch", {"p_batch_id": "batch"})]
