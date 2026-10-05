from __future__ import annotations

from typing import Any

import pytest
from analysis.text.value_pipeline import supabase_store


class _Response:
    def __init__(self, payload: object, status_code: int = 201) -> None:
        self._payload = payload
        self.status_code = status_code

    def json(self) -> object:
        return self._payload


class _Session:
    def __init__(self, response: _Response | None = None) -> None:
        self.response = response or _Response([{"id": "snapshot-id"}])
        self.calls: list[dict[str, Any]] = []

    def post(self, url: str, **kwargs: Any) -> _Response:
        self.calls.append({"url": url, **kwargs})
        return self.response

    def delete(self, url: str, **kwargs: Any) -> _Response:
        self.calls.append({"method": "delete", "url": url, **kwargs})
        return self.response


class _SequenceSession(_Session):
    def __init__(self, responses: list[_Response]) -> None:
        super().__init__()
        self.responses = iter(responses)

    def post(self, url: str, **kwargs: Any) -> _Response:
        self.calls.append({"url": url, **kwargs})
        return next(self.responses)


class _RecordingClient:
    def __init__(self, snapshot_rows: list[dict[str, Any]] | None = None) -> None:
        self.snapshot_rows = snapshot_rows if snapshot_rows is not None else [{"id": "snapshot-id"}]
        self.calls: list[dict[str, Any]] = []

    def upsert(
        self,
        table: str,
        rows: list[dict[str, Any]],
        *,
        on_conflict: str,
        return_rows: bool = False,
    ) -> list[dict[str, Any]]:
        self.calls.append(
            {
                "table": table,
                "rows": rows,
                "on_conflict": on_conflict,
                "return_rows": return_rows,
            }
        )
        return self.snapshot_rows if return_rows else []


def _live_track() -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "track": "live",
        "scope": {"ticker": "005930", "company_name": "삼성전자"},
        "source": "newsapi_ai",
        "as_of": "2026-09-18T09:00:00+09:00",
        "backend": "kr-finbert",
        "status": "partial",
        "coverage": {
            "fetched_count": 100,
            "relevant_count": 2,
            "publisher_count": 2,
            "newest_published_at": "2026-09-18T08:30:00+09:00",
            "lag_minutes": 30,
            "provider_total_results": 101,
            "provider_returned_count": 100,
            "provider_pages": 2,
            "provider_truncated": True,
        },
        "window": {
            "start": "2026-09-17T09:00:00+09:00",
            "end": "2026-09-18T09:00:00+09:00",
            "status": "ok",
            "sentiment_mean": 0.25,
            "sentiment_std": 0.15,
            "article_count": 2,
            "publisher_count": 2,
        },
        "timeline": [
            {
                "date": "2026-09-18",
                "status": "ok",
                "sentiment_mean": 0.25,
                "sentiment_std": 0.15,
                "article_count": 2,
                "publisher_count": 2,
            }
        ],
        "articles": [
            {
                "news_id": "n1",
                "ticker": "005930",
                "title": "삼성전자 실적 개선",
                "press": "한국경제",
                "url": "https://example.com/n1",
                "date": "2026-09-18",
                "published_at": "2026-09-18T08:30:00+09:00",
                "event_id": "e1",
                "sentiment_score": 0.4,
            }
        ],
    }


def _financial_track() -> dict[str, Any]:
    keys = ("per", "pbr", "roe", "operating_margin", "debt_ratio", "revenue_growth")
    return {
        "track": "financial",
        "scope": {"ticker": "005930", "company_name": "삼성전자"},
        "source": "dart",
        "as_of": "2025-12-30",
        "status": "ok",
        "filing": {
            "fiscal_year": 2024,
            "statement": "CFS",
            "receipt_no": "20250311000600",
            "filed_at": "2025-03-11",
            "shares_basis": "2024-12-31 common_shares",
        },
        "price": {"value": 60000.0, "as_of": "2025-12-30", "source": "fdr"},
        "metrics": [
            {
                "metric_key": key,
                "value": float(index),
                "unit": "multiple" if key in {"per", "pbr"} else "percent",
                "basis": f"{key} 계산 근거",
                "note": None,
            }
            for index, key in enumerate(keys, start=1)
        ],
        "validation": {"errors": []},
    }


def test_client_requires_credentials_before_http(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    monkeypatch.delenv("SUPABASE_SECRET_KEY", raising=False)
    monkeypatch.delenv("SUPABASE_SERVICE_ROLE_KEY", raising=False)
    session = _Session()

    with pytest.raises(supabase_store.SupabaseConfigurationError, match="SUPABASE_URL"):
        supabase_store.SupabaseRestClient.from_env(session=session)

    assert session.calls == []


def test_client_normalizes_url_and_sends_postgrest_upsert_headers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SUPABASE_URL", "https://project.supabase.co/")
    monkeypatch.setenv("SUPABASE_SECRET_KEY", "secret-value")
    session = _Session()
    client = supabase_store.SupabaseRestClient.from_env(session=session)

    rows = client.upsert(
        "financial_snapshots",
        [{"stock_code": "005930"}],
        on_conflict="stock_code,as_of,fiscal_year",
        return_rows=True,
    )

    assert rows == [{"id": "snapshot-id"}]
    call = session.calls[0]
    assert call["url"] == "https://project.supabase.co/rest/v1/financial_snapshots"
    assert call["params"] == {"on_conflict": "stock_code,as_of,fiscal_year"}
    assert call["headers"] == {
        "apikey": "secret-value",
        "Authorization": "Bearer secret-value",
        "Content-Type": "application/json",
        "Prefer": "resolution=merge-duplicates,return=representation",
    }


def test_client_retries_server_errors_and_redacts_secret(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SUPABASE_URL", "https://project.supabase.co")
    monkeypatch.setenv("SUPABASE_SECRET_KEY", "secret-value")
    sleeps: list[float] = []
    monkeypatch.setattr(supabase_store.time, "sleep", sleeps.append)
    session = _SequenceSession(
        [_Response({}, 500), _Response({}, 502), _Response([], 201)]
    )
    client = supabase_store.SupabaseRestClient.from_env(session=session)

    client.upsert("news_articles", [], on_conflict="stock_code,track,news_id")

    assert len(session.calls) == 3
    assert sleeps == [1.0, 2.0]

    failed = supabase_store.SupabaseRestClient.from_env(
        session=_Session(_Response({"message": "secret-value is invalid"}, 401))
    )
    with pytest.raises(supabase_store.SupabaseWriteError) as caught:
        failed.upsert("news_articles", [], on_conflict="stock_code,track,news_id")
    assert "secret-value" not in str(caught.value)
    assert caught.value.code == "supabase_news_articles_http_401"
    assert "news_articles" in str(caught.value)


def test_client_deletes_only_explicitly_filtered_rows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SUPABASE_URL", "https://project.supabase.co")
    monkeypatch.setenv("SUPABASE_SECRET_KEY", "secret-value")
    session = _Session(_Response({}, 204))
    client = supabase_store.SupabaseRestClient.from_env(session=session)

    client.delete(
        "news_articles",
        params={"stock_code": "in.(005930,035420)", "track": "eq.live"},
    )

    assert session.calls == [{
        "method": "delete",
        "url": "https://project.supabase.co/rest/v1/news_articles",
        "params": {"stock_code": "in.(005930,035420)", "track": "eq.live"},
        "headers": {
            "apikey": "secret-value",
            "Authorization": "Bearer secret-value",
            "Prefer": "return=minimal",
        },
        "timeout": 30,
    }]


def test_persist_news_track_maps_parent_daily_and_safe_article_rows() -> None:
    client = _RecordingClient()

    supabase_store.persist_news_track(client, _live_track())

    assert [call["table"] for call in client.calls] == [
        "news_sentiment_tracks",
        "news_sentiment_daily",
        "news_articles",
    ]
    assert [call["on_conflict"] for call in client.calls] == [
        "stock_code,track",
        "stock_code,track,sentiment_date",
        "stock_code,track,news_id",
    ]
    parent = client.calls[0]["rows"][0]
    assert parent == {
        "stock_code": "005930",
        "track": "live",
        "source": "newsapi_ai",
        "backend": "kr-finbert",
        "status": "partial",
        "as_of": "2026-09-18T09:00:00+09:00",
        "window_start": "2026-09-17",
        "window_end": "2026-09-18",
        "sentiment_mean": 0.25,
        "sentiment_std": 0.15,
        "article_count": 2,
        "publisher_count": 2,
        "fetched_count": 100,
        "relevant_count": 2,
        "newest_published_at": "2026-09-18T08:30:00+09:00",
        "lag_minutes": 30,
        "provider_total_results": 101,
        "provider_returned_count": 100,
        "provider_pages": 2,
        "provider_truncated": True,
    }
    article = client.calls[2]["rows"][0]
    assert article["article_date"] == "2026-09-18"
    assert not {"body", "summary", "content"}.intersection(article)


def test_persist_news_track_identifies_zero_relevant_as_no_data() -> None:
    track = _live_track()
    track["coverage"]["relevant_count"] = 0
    track["backend"] = "none"
    client = _RecordingClient()

    with pytest.raises(supabase_store.SupabaseNoDataError) as caught:
        supabase_store.persist_news_track(client, track)

    assert caught.value.code == "no_relevant_news"
    assert client.calls == []


def test_persist_financial_track_uses_returned_uuid_for_all_six_metrics() -> None:
    client = _RecordingClient()

    snapshot_id = supabase_store.persist_financial_track(client, _financial_track())

    assert snapshot_id == "snapshot-id"
    assert [call["table"] for call in client.calls] == [
        "financial_snapshots",
        "financial_metrics",
    ]
    assert client.calls[0]["return_rows"] is True
    assert client.calls[0]["on_conflict"] == "stock_code,as_of,fiscal_year"
    metrics = client.calls[1]["rows"]
    assert len(metrics) == 6
    assert all(row["snapshot_id"] == "snapshot-id" for row in metrics)
    assert client.calls[1]["on_conflict"] == "snapshot_id,metric_key"


def test_persist_financial_track_stops_when_upsert_returns_no_uuid() -> None:
    client = _RecordingClient(snapshot_rows=[])

    with pytest.raises(supabase_store.SupabaseWriteError, match="UUID"):
        supabase_store.persist_financial_track(client, _financial_track())

    assert [call["table"] for call in client.calls] == ["financial_snapshots"]
