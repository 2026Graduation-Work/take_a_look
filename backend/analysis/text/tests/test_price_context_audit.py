import json
from datetime import date

from analysis.text.value_pipeline import price_context_audit
from analysis.text.value_pipeline.supabase_store import SupabaseRestClient, SupabaseWriteError


class PublicSession:
    def __init__(self):
        self.tables = []

    def get(self, url, *, params, headers, timeout):
        table = url.rsplit("/", 1)[-1]
        self.tables.append(table)
        data = {
            "disclosures": [
                {"stock_code": "005930", "filed_on": "2026-11-20"},
                {"stock_code": "005930", "filed_on": "2026-11-23"},
            ],
            "news_articles": [
                {"stock_code": "005930", "article_date": "2026-11-22", "published_at": None,
                 "news_id": "100", "url": "https://example.test/article"},
                {"stock_code": "005930", "article_date": "2026-11-22", "published_at": "2026-11-22T15:00:00Z",
                 "news_id": "100", "url": "https://example.test/article"},
                {"stock_code": "005930", "article_date": "2026-11-22", "published_at": "2026-11-22T14:59:59Z",
                 "news_id": "101", "url": "https://example.test/article"},
            ],
            "market_status": [
                {"status_date": "2026-11-23", "index_quotes": [{"symbol": "KOSPI", "changePercent": 0}]},
                {"status_date": "2026-11-24", "index_quotes": [{"symbol": "KOSDAQ", "changePercent": 1}]},
            ],
        }
        assert "title" not in params["select"]
        return Response(data[table][params["offset"]:params["offset"] + 1])


class Response:
    status_code = 200

    def __init__(self, rows):
        self.rows = rows

    def json(self):
        return self.rows


def test_audit_get_only_reports_source_ranges_missing_and_kst_boundaries():
    session = PublicSession()
    read = SupabaseRestClient("https://db.example.test", "fake-key", session=session).select
    report, failed = price_context_audit.audit(read, [date(2026, 11, day) for day in (23, 24, 25)], radius=3)
    assert not failed
    assert set(session.tables) == {"disclosures", "news_articles", "market_status"}
    assert report["coverage"] == "unverified"
    assert report["disclosures"]["first"] == "2026-11-20"
    assert report["disclosures"]["last"] == "2026-11-23"
    assert report["disclosures"]["count"] == 2
    news = report["news_articles"]
    assert news["missing_published_at"] == 1
    assert news["duplicate_news_id_rows"] == 1
    assert news["duplicate_url_rows"] == 2
    assert news["stocks"]["005930"]["dates"]["2026-11-23"]["counts_by_day"] == {
        "2026-11-22": 2, "2026-11-23": 1,
    }
    assert report["market_status"]["dates"] == {
        "2026-11-23": {"status": "ok", "change_percent": 0},
        "2026-11-24": {"status": "missing_kospi"},
        "2026-11-25": {"status": "missing_market_row"},
    }
    assert "fake-key" not in json.dumps(report) and "example.test" not in json.dumps(report)


def test_audit_preserves_success_when_a_source_cannot_be_read():
    def read(table, **kwargs):
        if table == "news_articles":
            raise SupabaseWriteError("Do not print error details")
        return []

    report, failed = price_context_audit.audit(read, [date(2026, 11, 23)], radius=3)
    assert failed
    assert report["news_articles"] == {"status": "query_failed"}
    assert report["disclosures"]["status"] == "ok" and report["disclosures"]["count"] == 0


def test_audit_rejects_service_key_without_attempting_a_read(monkeypatch, capsys):
    monkeypatch.setenv("NEXT_PUBLIC_SUPABASE_URL", "https://db.example.test")
    monkeypatch.setenv("NEXT_PUBLIC_SUPABASE_ANON_KEY", "sb_secret_fake-key")
    assert price_context_audit.main(["--date", "2026-11-23"]) == 1
    assert json.loads(capsys.readouterr().out)["status"] == "not_configured"
