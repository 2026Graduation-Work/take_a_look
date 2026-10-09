from datetime import date

import retention


class FakeStore:
    def __init__(self):
        self.calls = []

    def _request(self, method, path, body=None, prefer=None):
        self.calls.append((method, path.split("?")[0], body))
        if path.startswith("/rest/v1/chart_feature_snapshots?select"):
            offset = int(path.rsplit("offset=", 1)[1])
            rows = [{"storage_path": f"b/2026-08-01/{i % 1200}/x.parquet"} for i in range(1500)]
            return rows[offset:offset + 1000]
        if path.startswith("/storage/v1/object/list/"):
            return []
        return 0


def test_retention_deletes_old_inputs_in_batches(monkeypatch):
    store = FakeStore()
    monkeypatch.setattr(retention, "SupabaseStore", lambda: store)
    retention.main(date(2026, 11, 15))
    methods = [(method, path) for method, path, _ in store.calls]
    assert methods[0] == ("POST", "/rest/v1/rpc/prune_chart_batches")
    deletes = [body for method, path, body in store.calls if path == "/storage/v1/object/chart-features"]
    assert [len(body["prefixes"]) for body in deletes] == [1000, 200]  # 1200개 경로를 1000개씩
    assert ("DELETE", "/rest/v1/chart_feature_snapshots") in methods
    assert ("DELETE", "/rest/v1/news_articles") in methods
    assert ("DELETE", "/rest/v1/disclosures") in methods


def test_corrected_retention_preserves_history_and_recent_inputs():
    removed = []
    class Store:
        def _request(self, method, path, body):
            if method == "DELETE":
                removed.extend(body["prefixes"])
                return
            return {
                "raw-prices-v3": [{"name": "2026-08-01"}, {"name": "2026-10-08"}],
                "raw-prices-v3/2026-08-01": [{"name": "005930.parquet"}],
                "investor-flows-v3": [{"name": "2026-08-01.parquet"}, {"name": "2026-10-08.parquet"}],
            }[body["prefix"]]
    assert retention.prune_corrected_inputs(Store(), "2026-09-09") == 2
    assert removed == ["raw-prices-v3/2026-08-01/005930.parquet", "investor-flows-v3/2026-08-01.parquet"]
