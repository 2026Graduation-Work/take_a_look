import json
from datetime import date, datetime, timedelta
from urllib.parse import parse_qs, urlsplit

import pytest
from serving import retention


class FakeStore:
    def __init__(self):
        self.calls = []

    def _request(self, method, path, body=None, prefer=None):
        self.calls.append((method, path.split("?")[0], body))
        if path.startswith("/rest/v1/chart_feature_snapshots?as_of=gte."):
            return []
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
                "calendars-v3": [{"name": "2026-08-01.parquet"}, {"name": "2026-10-08.parquet"},
                                 {"name": "README"}],
            }[body["prefix"]]
    assert retention.prune_corrected_inputs(Store(), "2026-09-09", "2026-09-09") == 3
    assert removed == ["raw-prices-v3/2026-08-01/005930.parquet", "investor-flows-v3/2026-08-01.parquet",
                       "calendars-v3/2026-08-01.parquet"]


def test_inputs_follow_oldest_kept_batch_but_flows_keep_30_days(monkeypatch):
    removed = []
    class Store:
        def _request(self, method, path, body=None, prefer=None):
            if path.startswith("/rest/v1/chart_feature_snapshots?as_of=gte."):
                return []
            if path.startswith("/rest/v1/chart_batches"):
                return [{"as_of": "2026-10-02"}]
            if path.startswith("/rest/v1/chart_feature_snapshots?select"):
                return [{"storage_path": "alpha/2026-10-01/h/005930.parquet"}] if "as_of=lt.2026-10-02" in path else []
            if method == "DELETE" and path.startswith("/storage/"):
                removed.extend(body["prefixes"])
            if path.startswith("/storage/v1/object/list/"):
                return {"raw-prices-v3": [{"name": "2026-10-01"}, {"name": "2026-10-02"}],
                        "raw-prices-v3/2026-10-01": [{"name": "005930.parquet"}],
                        "investor-flows-v3": [{"name": "2026-10-01.parquet"}],
                        "calendars-v3": [{"name": "2026-10-01.parquet"}, {"name": "2026-10-02.parquet"}]}[body["prefix"]]
            return 0
    monkeypatch.setattr(retention, "SupabaseStore", Store)
    retention.main(date(2026, 10, 12))
    assert removed == ["alpha/2026-10-01/h/005930.parquet", "raw-prices-v3/2026-10-01/005930.parquet",
                       "calendars-v3/2026-10-01.parquet"]


def test_retention_keeps_shared_objects_referenced_by_retained_batches(monkeypatch):
    class Store(FakeStore):
        def _request(self, method, path, body=None, prefer=None):
            if path.startswith("/rest/v1/chart_feature_snapshots?as_of=gte."):
                return [{"storage_path": "b/2026-08-01/0/x.parquet"}]
            return super()._request(method, path, body, prefer)
    store = Store()
    monkeypatch.setattr(retention, "SupabaseStore", lambda: store)
    retention.main(date(2026, 11, 15))
    removed = [p for method, path, body in store.calls if method == "DELETE" and path.startswith("/storage/")
               for p in body["prefixes"]]
    assert "b/2026-08-01/0/x.parquet" not in removed
    assert len(removed) == 1199


@pytest.mark.parametrize(("today", "cutoff"), [
    (date(2026, 11, 25), date(2026, 7, 28)),
    (date(2027, 1, 1), date(2026, 9, 3)),
    (date(2024, 6, 28), date(2024, 2, 29)),
])
def test_120_day_retention_recovers_after_partial_failure(monkeypatch, today, cutoff):
    kept = [(cutoff + timedelta(days=offset)).isoformat() for offset in range(121)]
    assert kept[-1] == today.isoformat()
    first_removed = (cutoff - timedelta(days=1)).isoformat()
    rows = {
        "/rest/v1/news_articles": [first_removed, *kept],
        "/rest/v1/disclosures": [first_removed, *kept],
    }

    class Store:
        fail_once = True

        def _request(self, method, path, body=None, **options):
            endpoint = urlsplit(path)
            if endpoint.path not in rows:
                return []
            assert method == "DELETE"
            threshold = next(iter(parse_qs(endpoint.query).values()))[0]
            assert threshold == f"lt.{cutoff.isoformat()}"
            if endpoint.path.endswith("/disclosures") and self.fail_once:
                self.fail_once = False
                raise TimeoutError("mock write failure")
            rows[endpoint.path] = [day for day in rows[endpoint.path] if day >= threshold[3:]]
            return []

    store = Store()
    monkeypatch.setattr(retention, "SupabaseStore", lambda: store)
    with pytest.raises(TimeoutError):
        retention.main(today, article_days=120)
    assert rows["/rest/v1/news_articles"] == kept
    assert rows["/rest/v1/disclosures"] == [first_removed, *kept]
    retention.main(today, article_days=120)
    retention.main(today, article_days=120)
    assert list(rows.values()) == [kept, kept]


def test_dry_run_only_reads_dates_and_uses_kst(monkeypatch, capsys):
    calls = []

    class Clock:
        @staticmethod
        def now(zone):
            assert str(zone) == "Asia/Seoul"
            return datetime(2026, 11, 25, 0, 30, tzinfo=zone)

    class Store:
        def _request(self, method, path):
            assert method == "GET"
            endpoint = urlsplit(path)
            options = parse_qs(endpoint.query)
            field = options["select"][0]
            assert options[field] == ["lt.2026-07-28"]
            offset = int(options["offset"][0])
            calls.append((endpoint.path, offset))
            count = 1001 if endpoint.path.endswith("/news_articles") else 1
            return [{field: "2026-07-27"}] * max(0, min(1000, count - offset))

    monkeypatch.setattr(retention, "SupabaseStore", Store)
    monkeypatch.setattr(retention, "datetime", Clock)
    retention.main(article_days=120, dry_run=True)
    result = json.loads(capsys.readouterr().out)
    assert result["article_cutoff"] == "2026-07-28"
    assert result["candidates"] == {
        "news_articles": {"count": 1001, "by_date": {"2026-07-27": 1001}},
        "disclosures": {"count": 1, "by_date": {"2026-07-27": 1}},
    }
    assert calls == [("/rest/v1/news_articles", 0), ("/rest/v1/news_articles", 1000),
                     ("/rest/v1/disclosures", 0)]
