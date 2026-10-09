from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from analysis.text.value_pipeline import supabase_sync


def _track(kind: str, ticker: str = "005930") -> dict[str, Any]:
    if kind == "financial":
        return {"track": "financial", "scope": {"ticker": ticker}}
    return {
        "track": kind,
        "scope": {"ticker": ticker, "company_name": "회사"},
        "status": "ok",
        "coverage": {"relevant_count": 1},
        "backend": "kr-finbert",
    }


def test_live_parser_defaults_to_six_supported_stocks_and_accepts_repeats() -> None:
    parser = supabase_sync.build_parser()

    defaults = supabase_sync.targets_from_args(parser.parse_args(["live"]))
    explicit = supabase_sync.targets_from_args(
        parser.parse_args(
            ["live", "--target", "005930:삼성전자", "--target", "035720:카카오"]
        )
    )

    assert defaults == {
        "005930": "삼성전자",
        "005380": "현대차",
        "035720": "카카오",
        "068270": "셀트리온",
        "035420": "네이버",
        "247540": "에코프로비엠",
    }
    assert explicit == {"005930": "삼성전자", "035720": "카카오"}


def test_backfill_routes_valid_news_and_financial_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    news_path = tmp_path / "news.json"
    financial_path = tmp_path / "financial.json"
    news_path.write_text(json.dumps(_track("historical")), encoding="utf-8")
    financial_path.write_text(json.dumps(_track("financial")), encoding="utf-8")
    news_calls: list[dict[str, Any]] = []
    financial_calls: list[dict[str, Any]] = []
    monkeypatch.setattr(
        supabase_sync.supabase_store,
        "persist_news_track",
        lambda client, track: news_calls.append(track),
    )
    monkeypatch.setattr(
        supabase_sync.supabase_store,
        "persist_financial_track",
        lambda client, track: financial_calls.append(track) or "snapshot-id",
    )

    assert supabase_sync.backfill_news([news_path], client=object()).exit_code == 0
    assert supabase_sync.backfill_financial([financial_path], client=object()).exit_code == 0
    assert [track["track"] for track in news_calls] == ["historical"]
    assert [track["track"] for track in financial_calls] == ["financial"]


def test_backfill_rejects_wrong_track_before_any_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "wrong.json"
    path.write_text(json.dumps(_track("financial")), encoding="utf-8")
    writes: list[dict[str, Any]] = []
    monkeypatch.setattr(
        supabase_sync.supabase_store,
        "persist_news_track",
        lambda client, track: writes.append(track),
    )

    result = supabase_sync.backfill_news([path], client=object())

    assert result.exit_code == 1
    assert writes == []


def test_live_sync_keeps_three_successes_when_second_stock_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    attempted: list[str] = []
    written: list[str] = []

    def fake_cycle(targets, **kwargs):
        ticker = next(iter(targets))
        attempted.append(ticker)
        if ticker == "005380":
            raise RuntimeError("provider failed")
        return {ticker: _track("live", ticker)}

    monkeypatch.setattr(supabase_sync.news_run, "run_live_cycle", fake_cycle)
    monkeypatch.setattr(
        supabase_sync.supabase_store,
        "persist_news_track",
        lambda client, track: written.append(track["scope"]["ticker"]),
    )

    result = supabase_sync.run_live_sync(
        supabase_sync.DEFAULT_TARGETS,
        client=object(),
        fetcher=object(),
    )

    assert attempted == ["005930", "005380", "035720", "068270", "035420", "247540"]
    assert written == ["005930", "035720", "068270", "035420", "247540"]
    assert result.succeeded == ["005930", "035720", "068270", "035420", "247540"]
    assert list(result.failures) == ["005380"]
    assert result.exit_code == 1


def test_live_sync_skips_zero_relevant_without_overwriting_or_failing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class RecordingClient:
        def __init__(self) -> None:
            self.calls: list[dict[str, Any]] = []

        def upsert(self, *args: Any, **kwargs: Any) -> list[dict[str, Any]]:
            self.calls.append({"args": args, "kwargs": kwargs})
            return []

    client = RecordingClient()

    def no_news_cycle(targets, **kwargs):
        ticker = next(iter(targets))
        track = _track("live", ticker)
        track["coverage"]["relevant_count"] = 0
        return {ticker: track}

    monkeypatch.setattr(supabase_sync.news_run, "run_live_cycle", no_news_cycle)

    result = supabase_sync.run_live_sync(
        {"005930": "삼성전자"},
        client=client,
        fetcher=object(),
    )

    assert client.calls == []
    assert result.succeeded == []
    assert result.failures == {}
    assert result.skipped == {"005930": "no_relevant_news"}
    assert result.exit_code == 0


def test_live_sync_reports_safe_supabase_error_code_without_response_body(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        supabase_sync.news_run,
        "run_live_cycle",
        lambda targets, **kwargs: {"005930": _track("live")},
    )
    monkeypatch.setattr(
        supabase_sync.supabase_store,
        "persist_news_track",
        lambda client, track: (_ for _ in ()).throw(
            supabase_sync.supabase_store.SupabaseWriteError(
                "secret response body", code="supabase_http_400"
            )
        ),
    )

    result = supabase_sync.run_live_sync(
        {"005930": "삼성전자"},
        client=object(),
        fetcher=object(),
    )
    supabase_sync._print_result(result)
    output = capsys.readouterr().out

    assert result.failures == {"005930": "supabase_http_400"}
    assert result.exit_code == 1
    assert "supabase_http_400" in output
    assert "secret response body" not in output


def test_live_sync_prints_safe_internal_validation_detail(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        supabase_sync.news_run,
        "run_live_cycle",
        lambda targets, **kwargs: {"005930": _track("live")},
    )
    monkeypatch.setattr(
        supabase_sync.supabase_store,
        "persist_news_track",
        lambda client, track: (_ for _ in ()).throw(
            supabase_sync.supabase_store.SupabaseWriteError(
                "article.date 날짜가 올바르지 않습니다"
            )
        ),
    )

    result = supabase_sync.run_live_sync(
        {"005930": "삼성전자"},
        client=object(),
        fetcher=object(),
    )
    supabase_sync._print_result(result)
    output = capsys.readouterr().out

    assert "supabase_write_error" in output
    assert "article.date 날짜가 올바르지 않습니다" in output


def test_reset_live_collects_and_validates_before_replacing_each_stock(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, object]] = []

    class Client:
        def delete(self, table: str, *, params: dict[str, str]) -> None:
            calls.append((table, params))

    monkeypatch.setattr(
        supabase_sync.news_run,
        "run_live_cycle",
        lambda targets, **kwargs: calls.append(("collect", dict(targets))) or {
            next(iter(targets)): _track("live", next(iter(targets)))
        },
    )
    monkeypatch.setattr(
        supabase_sync.supabase_store,
        "persist_news_track",
        lambda client, track: calls.append(("persist", track["scope"]["ticker"])),
    )

    result = supabase_sync.reset_live_sync(
        {"005930": "삼성전자", "035420": "네이버"}, client=Client(), fetcher=object(),
    )

    assert calls == [
        ("collect", {"005930": "삼성전자"}),
        ("news_articles", {"stock_code": "in.(005930)", "track": "eq.live"}),
        ("news_sentiment_daily", {"stock_code": "in.(005930)", "track": "eq.live"}),
        ("news_sentiment_tracks", {"stock_code": "in.(005930)", "track": "eq.live"}),
        ("persist", "005930"),
        ("collect", {"035420": "네이버"}),
        ("news_articles", {"stock_code": "in.(035420)", "track": "eq.live"}),
        ("news_sentiment_daily", {"stock_code": "in.(035420)", "track": "eq.live"}),
        ("news_sentiment_tracks", {"stock_code": "in.(035420)", "track": "eq.live"}),
        ("persist", "035420"),
    ]
    assert result.succeeded == ["005930", "035420"]


def test_second_page_only_for_full_truncated_stocks_within_daily_cap(monkeypatch: pytest.MonkeyPatch) -> None:
    from analysis.text.value_pipeline import news_run, newsapi_ai

    pages: list[tuple[str, int]] = []

    def fetcher(keywords, start, end, *, page_size, page=1):
        pages.append((keywords[0], page))
        full = keywords[0] != "카카오"  # 005930은 검색어 덮어쓰기("삼성")가 있다
        count = page_size if full else 30
        articles = [{"news_id": f"{keywords[0]}-{page}-{i}"} for i in range(count)]
        return newsapi_ai.ArticleBatch(articles=articles, total_results=325 if full else 30,
                                       returned_count=count, pages=4 if full else 1, truncated=full)

    seen: dict[str, int] = {}

    def fake_track(items, ticker, *args, provider_metadata=None, **kwargs):
        seen[ticker] = provider_metadata["returned_count"]
        return {"ticker": ticker, "truncated": provider_metadata["truncated"]}

    monkeypatch.setattr(news_run.news_tracks, "build_live_track", fake_track)
    monkeypatch.setattr(supabase_sync.supabase_store, "persist_news_track", lambda client, track: None)

    supabase_sync.run_live_sync({"005930": "삼성전자", "035720": "카카오"}, client=object(), fetcher=fetcher)
    assert [page for _, page in pages] == [1, 2, 1]  # 꽉 찬 종목만 2페이지
    assert seen == {"005930": 200, "035720": 30}

    pages.clear()
    full_day = {f"{i:06d}": "삼성전자" for i in range(supabase_sync.NEWSAPI_DAILY_CALLS)}
    supabase_sync.run_live_sync(full_day, client=object(), fetcher=fetcher)
    assert len(pages) == supabase_sync.NEWSAPI_DAILY_CALLS  # 대상이 상한만큼이면 2페이지 없음
