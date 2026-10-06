from __future__ import annotations

import pytest
from analysis.text.value_pipeline import historical_backfill as hb


class Client:
    def __init__(self):
        self.rows = {
            ("news_sentiment_tracks", "005930"): {
                "historical": {
                    "stock_code": "005930",
                    "track": "historical",
                    "source": "bigkinds",
                    "backend": "kr-finbert",
                }
            }
        }
        self.calls = []
        self.fail = False

    def select(self, table, *, params):
        ticker = params["stock_code"][3:]
        return list(self.rows.get((table, ticker), {}).values())

    def upsert(self, table, rows, **kwargs):
        self.calls.append((table, rows, kwargs))
        if self.fail and table == "news_sentiment_daily":
            raise RuntimeError("interrupted")
        for row in rows:
            assert row["track"] == "historical"
            key = row.get("sentiment_date") or row.get("news_id") or row["track"]
            self.rows.setdefault((table, row["stock_code"]), {}).setdefault(key, row)
        return []


def source(tmp_path, ticker="005930", period="20250101-20251231"):
    folder = tmp_path / ticker
    folder.mkdir(exist_ok=True)
    (folder / f"삼성전자_{period}.xlsx").write_bytes(b"workbook")


def track(ticker, company, start, end, **kwargs):
    from datetime import date, timedelta

    points = []
    day = date.fromisoformat(start)
    while day <= date.fromisoformat(end):
        points.append(
            {
                "date": str(day),
                "status": "insufficient_data",
                "sentiment_mean": None,
                "sentiment_std": None,
                "article_count": 0,
                "publisher_count": 0,
            }
        )
        day += timedelta(days=1)
    points[0].update(status="ok", sentiment_mean=0.2, article_count=2, publisher_count=1)
    return {
        "track": "historical",
        "source": "bigkinds",
        "backend": "kr-finbert",
        "scope": {"ticker": ticker},
        "timeline": points,
        "articles": [],
    }


def test_source_gap_is_not_article_free_date(tmp_path):
    source(tmp_path, period="20250102-20250103")
    report = hb.audit_coverage(
        "005930",
        "삼성전자",
        "2025-01-01",
        "2025-01-04",
        tmp_path,
        [{"sentiment_date": "2025-01-02", "article_count": 0, "sentiment_mean": None}],
    )
    assert report["years"]["2025"]["source_missing_dates"] == ["2025-01-01", "2025-01-04"]
    assert report["years"]["2025"]["database_missing_dates"] == ["2025-01-03"]
    assert report["years"]["2025"]["no_relevant_article_dates"] == ["2025-01-02"]


def test_reuse_csv_preserve_db_and_resume_failed_write(tmp_path, monkeypatch):
    source(tmp_path)
    csv = tmp_path / "daily.csv"
    csv.write_text("# KR-FinBERT\ndate,n,score\n2025-01-01,3,0.7\n2025-01-02,4,0.8\n")
    client = Client()
    client.rows[("news_sentiment_daily", "005930")] = {
        "2025-01-01": {
            "stock_code": "005930",
            "track": "historical",
            "sentiment_date": "2025-01-01",
            "sentiment_mean": -0.3,
            "article_count": 9,
        }
    }
    calls = []

    def build(*args, **kwargs):
        calls.append(args)
        assert kwargs["require_finbert"] is True
        return track(*args, **kwargs)

    monkeypatch.setattr(hb.news_run, "run_historical_cycle", build)
    options = dict(
        targets={"005930": "삼성전자"},
        date_start="2025-01-01",
        date_end="2025-01-04",
        data_dir=tmp_path,
        cache_dir=tmp_path / "cache",
        client=client,
        daily_csvs={"005930": csv},
    )
    client.fail = True
    assert hb.run_backfill(**options).exit_code == 1
    client.fail = False
    assert hb.run_backfill(**options).exit_code == 0
    assert len(calls) == 1  # analysis survives a failed upload
    rows = client.rows[("news_sentiment_daily", "005930")]
    assert rows["2025-01-01"]["sentiment_mean"] == -0.3
    assert rows["2025-01-02"]["sentiment_mean"] == 0.8
    assert rows["2025-01-04"]["sentiment_mean"] is None
    assert all(kw["ignore_duplicates"] for _, _, kw in client.calls)
    assert hb.run_backfill(**options).exit_code == 0
    assert len(calls) == 1


def test_cache_invalidated_when_source_changes(tmp_path, monkeypatch):
    source(tmp_path)
    client = Client()
    client.fail = True
    calls = []

    def build(*args, **kwargs):
        calls.append(args)
        return track(*args, **kwargs)

    monkeypatch.setattr(hb.news_run, "run_historical_cycle", build)
    options = dict(
        targets={"005930": "삼성전자"},
        date_start="2025-01-01",
        date_end="2025-01-02",
        data_dir=tmp_path,
        cache_dir=tmp_path / "cache",
        client=client,
    )
    hb.run_backfill(**options)
    next((tmp_path / "005930").glob("*.xlsx")).write_bytes(b"changed workbook")
    hb.run_backfill(**options)
    assert len(calls) == 2


def test_untrusted_csv_is_rejected(tmp_path):
    path = tmp_path / "daily.csv"
    path.write_text("date,n,score\n2025-01-01,3,0.7\n")
    with pytest.raises(ValueError):
        hb.read_daily_csv(path)


def test_missing_parent_fails_without_creating_placeholder(tmp_path):
    source(tmp_path)
    client = Client()
    client.rows.clear()
    result = hb.run_backfill(
        {"005930": "삼성전자"},
        date_start="2025-01-01",
        date_end="2025-01-02",
        data_dir=tmp_path,
        cache_dir=tmp_path / "cache",
        client=client,
    )
    assert result.exit_code == 1
    assert client.calls == []


def test_audit_failure_still_writes_other_stock_reports(tmp_path, monkeypatch):
    import json
    import sys

    client = Client()
    monkeypatch.setattr(hb.supabase_store.SupabaseRestClient, "from_env", lambda: client)

    def audit(ticker, *args):
        if ticker == "005930":
            raise OSError("unavailable")
        return {"ticker": ticker, "years": {}}

    monkeypatch.setattr(hb, "audit_coverage", audit)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "historical_backfill",
            "--end",
            "2026-10-04",
            "--audit-only",
            "--cache-dir",
            str(tmp_path),
        ],
    )
    assert hb.main() == 1
    payload = json.loads((tmp_path / "coverage.json").read_text())
    assert len(payload["stocks"]) == 6
    assert payload["failures"] == {"005930/audit": "OSError"}
    assert payload["stocks"][1]["ticker"] == "005380"


def test_partial_source_year_is_skipped_and_never_fills_uncovered_dates(tmp_path, monkeypatch):
    source(tmp_path, period="20250102-20250103")
    client = Client()
    monkeypatch.setattr(hb.news_run, "run_historical_cycle", track)
    result = hb.run_backfill(
        {"005930": "삼성전자"},
        date_start="2025-01-01",
        date_end="2025-01-04",
        data_dir=tmp_path,
        cache_dir=tmp_path / "cache",
        client=client,
    )
    assert result.succeeded == []
    assert result.skipped == {"005930/2025": "missing_source_days=2"}
    assert set(client.rows[("news_sentiment_daily", "005930")]) == {"2025-01-02", "2025-01-03"}


def test_confirmation_reads_only_written_month_and_keeps_future_completed_dates(
    tmp_path, monkeypatch
):
    source(tmp_path)
    client = Client()
    client.rows[("news_sentiment_daily", "005930")] = {
        "2025-02-01": {
            "stock_code": "005930",
            "track": "historical",
            "sentiment_date": "2025-02-01",
            "sentiment_mean": 0.9,
            "article_count": 2,
        }
    }
    reads = []
    select = client.select

    def bounded_select(table, *, params):
        rows = select(table, params=params)
        if table == "news_sentiment_daily":
            reads.append(params)
            if "and" in params:
                first, last = params["and"].strip("()").split(",")
                start, end = (
                    first.removeprefix("sentiment_date.gte."),
                    last.removeprefix("sentiment_date.lte."),
                )
                rows = [r for r in rows if start <= r["sentiment_date"] <= end]
        return rows

    client.select = bounded_select
    calls = []

    def build(*args, **kwargs):
        calls.append(args)
        return track(*args, **kwargs)

    monkeypatch.setattr(hb.news_run, "run_historical_cycle", build)
    result = hb.run_backfill(
        {"005930": "삼성전자"},
        date_start="2025-01-01",
        date_end="2025-02-01",
        data_dir=tmp_path,
        cache_dir=tmp_path / "cache",
        client=client,
    )
    assert result.exit_code == 0
    assert len(calls) == 1  # preexisting February day remains completed after January verification
    assert reads[1]["and"] == "(sentiment_date.gte.2025-01-01,sentiment_date.lte.2025-01-31)"
