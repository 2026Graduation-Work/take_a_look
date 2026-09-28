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


def test_live_parser_defaults_to_exact_four_supported_stocks_and_accepts_repeats() -> None:
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

    assert attempted == ["005930", "005380", "035720", "068270"]
    assert written == ["005930", "035720", "068270"]
    assert result.succeeded == ["005930", "035720", "068270"]
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
