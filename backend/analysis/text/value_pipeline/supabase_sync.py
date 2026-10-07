"""뉴스·재무 분석 트랙을 Supabase에 적재하는 명령행 진입점."""
from __future__ import annotations

import argparse
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any

import requests

from . import disclosures, latest_financials, news_run, newsapi_ai, supabase_store
from .config import SETTINGS
from .news_run import _parse_target

DEFAULT_TARGETS: dict[str, str] = {
    "005930": "삼성전자",
    "005380": "현대차",
    "035720": "카카오",
    "068270": "셀트리온",
    "035420": "네이버",
    "247540": "에코프로비엠",
}


NEWSAPI_DAILY_CALLS = 20  # 하루 총 호출 상한(docs/ops/free-tier-budget.md). 종목당 1회


def dynamic_targets(client: Any, today: date | None = None) -> dict[str, str]:
    """기본 6종목 + 전체 사용자의 보유 ∪ 활성 관심 종목. 상한을 넘으면 절반은 최근 등록 순, 나머지는 날마다 순환."""
    today = today or date.today()
    latest: dict[str, str] = {}
    for table, params in (("portfolio_holdings", {}), ("watchlist", {"is_active": "eq.true"})):
        for row in client.select(table, params={"select": "stock_code,created_at", "order": "created_at.desc", **params}):
            latest[row["stock_code"]] = max(latest.get(row["stock_code"], ""), row["created_at"])
    extra = [code for code, _ in sorted(latest.items(), key=lambda item: item[1], reverse=True)
             if code not in DEFAULT_TARGETS]
    slots = NEWSAPI_DAILY_CALLS - len(DEFAULT_TARGETS)
    if len(extra) > slots:
        recent, rest = extra[: slots - slots // 2], extra[slots - slots // 2:]
        start = today.toordinal() * (slots // 2) % len(rest)
        extra = recent + [rest[(start + i) % len(rest)] for i in range(slots // 2)]
    names = {row["code"]: row["name"] for row in client.select(
        "stocks", params={"select": "code,name", "code": f"in.({','.join(extra) or '000000'})", "order": "code"})}
    return {**DEFAULT_TARGETS, **{code: names[code] for code in extra if code in names}}


def newsapi_remaining() -> int | None:
    """NewsAPI.ai 남은 횟수(무료 2,000회 중). 실패하면 None."""
    try:
        usage = requests.post("https://eventregistry.org/api/v1/usage",
                              json={"apiKey": SETTINGS.newsapi_ai_key}, timeout=20).json()
        return int(usage["availableTokens"]) - int(usage["usedTokens"])
    except Exception:
        return None


@dataclass
class SyncResult:
    succeeded: list[str] = field(default_factory=list)
    skipped: dict[str, str] = field(default_factory=dict)
    failures: dict[str, str] = field(default_factory=dict)

    @property
    def exit_code(self) -> int:
        return 1 if self.failures else 0


def _failure_name(exc: Exception) -> str:
    """비밀값이 섞일 수 있는 외부 오류 메시지 대신 예외 종류만 남긴다."""
    if isinstance(exc, supabase_store.SupabaseWriteError):
        if exc.code == "supabase_write_error":
            return f"{exc.code}: {exc}"
        return exc.code
    return type(exc).__name__


def run_live_sync(
    targets: Mapping[str, str],
    *,
    client: Any,
    fetcher: Any = newsapi_ai.fetch_article_batch,
    as_of: datetime | None = None,
) -> SyncResult:
    result = SyncResult()
    for ticker, company_name in targets.items():
        try:
            output = news_run.run_live_cycle(
                {ticker: company_name},
                fetcher=fetcher,
                as_of=as_of,
                page_size=100,
                require_finbert=True,
            )[ticker]
            supabase_store.persist_news_track(client, output)
        except supabase_store.SupabaseNoDataError as exc:
            result.skipped[ticker] = exc.code
        except Exception as exc:
            result.failures[ticker] = _failure_name(exc)
        else:
            result.succeeded.append(ticker)
    return result


def clear_live_news(targets: Mapping[str, str], *, client: Any) -> None:
    """Remove only live-news rows for the requested stocks, child-first.

    Historical BigKinds rows are deliberately excluded, so the reset can be
    used before the first new NewsAPI.ai collection without losing history.
    """
    codes = ",".join(targets)
    filters = {"stock_code": f"in.({codes})", "track": "eq.live"}
    for table in ("news_articles", "news_sentiment_daily", "news_sentiment_tracks"):
        client.delete(table, params=filters)


def reset_live_sync(
    targets: Mapping[str, str], *, client: Any,
    fetcher: Any = newsapi_ai.fetch_article_batch, as_of: datetime | None = None,
) -> SyncResult:
    """Replace each stock's live rows only after its replacement is ready.

    A provider failure or a zero-result window leaves that stock's last usable
    live view intact. Historical rows are never selected by ``clear_live_news``.
    """
    result = SyncResult()
    for ticker, company_name in targets.items():
        try:
            output = news_run.run_live_cycle(
                {ticker: company_name},
                fetcher=fetcher,
                as_of=as_of,
                page_size=100,
                require_finbert=True,
            )[ticker]
            # Validate before deleting any persisted live rows.
            supabase_store._require_news_track(output)
            clear_live_news({ticker: company_name}, client=client)
            supabase_store.persist_news_track(client, output)
        except supabase_store.SupabaseNoDataError as exc:
            result.skipped[ticker] = exc.code
        except Exception as exc:
            result.failures[ticker] = _failure_name(exc)
        else:
            result.succeeded.append(ticker)
    return result


def _read_track(path: Path, expected: set[str]) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("JSON 파일을 읽을 수 없습니다") from exc
    if not isinstance(value, dict) or value.get("track") not in expected:
        raise ValueError(f"기대 track: {sorted(expected)}")
    return value


def _backfill(paths: Sequence[Path], expected: set[str], persist: Any, client: Any) -> SyncResult:
    result = SyncResult()
    for path in paths:
        try:
            persist(client, _read_track(path, expected))
        except Exception as exc:
            result.failures[str(path)] = _failure_name(exc)
        else:
            result.succeeded.append(str(path))
    return result


def backfill_news(paths: Sequence[Path], *, client: Any) -> SyncResult:
    return _backfill(paths, {"historical", "live"}, supabase_store.persist_news_track, client)


def backfill_financial(paths: Sequence[Path], *, client: Any) -> SyncResult:
    return _backfill(paths, {"financial"}, supabase_store.persist_financial_track, client)


def backfill_historical(
    targets: Mapping[str, str], *, date_start: str, date_end: str, client: Any,
) -> SyncResult:
    result = SyncResult()
    for ticker, company_name in targets.items():
        try:
            track = news_run.run_historical_cycle(ticker, company_name, date_start, date_end)
            supabase_store.persist_news_track(client, track)
        except Exception as exc:
            result.failures[ticker] = _failure_name(exc)
        else:
            result.succeeded.append(ticker)
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="분석 트랙 Supabase 적재")
    subparsers = parser.add_subparsers(dest="command", required=True)
    live = subparsers.add_parser("live", help="6종목 최근 24시간 뉴스를 수집·적재")
    live.add_argument("--target", type=_parse_target, action="append")
    live.add_argument("--dynamic", action="store_true", help="기본 6 + 보유·관심 종목(하루 20회 상한)")
    subparsers.add_parser("disclosures", help="DART 하루 전체 공시를 받아 종목에 맞춰 적재")
    subparsers.add_parser("financial-latest", help="기본 6 + 보유·관심 종목의 최신 정기보고서 재무(바뀐 종목만)")
    reset_live = subparsers.add_parser(
        "reset-live", help="지정 종목의 live 행만 지운 뒤 최근 24시간 뉴스를 다시 적재"
    )
    reset_live.add_argument("--target", type=_parse_target, action="append")
    reset_live.add_argument("--dynamic", action="store_true")
    news = subparsers.add_parser("backfill-news", help="뉴스 track JSON 적재")
    news.add_argument("paths", type=Path, nargs="+")
    financial = subparsers.add_parser("backfill-financial", help="재무 track JSON 적재")
    financial.add_argument("paths", type=Path, nargs="+")
    historical = subparsers.add_parser("backfill-historical", help="BigKinds 과거 뉴스 수집·적재")
    historical.add_argument("--target", type=_parse_target, action="append")
    historical.add_argument("--start", required=True)
    historical.add_argument("--end", required=True)
    return parser


def targets_from_args(args: argparse.Namespace, client: Any = None) -> dict[str, str]:
    if getattr(args, "dynamic", False):
        return dynamic_targets(client)
    return dict(args.target) if args.target else dict(DEFAULT_TARGETS)


def _print_result(result: SyncResult) -> None:
    for item in result.succeeded:
        print(f"{item}: ok")
    for item, reason in result.skipped.items():
        print(f"{item}: skipped ({reason})")
    for item, error_name in result.failures.items():
        print(f"{item}: failed ({error_name})")


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    client = supabase_store.SupabaseRestClient.from_env()
    if args.command == "disclosures":
        disclosures.sync(client)
        return 0
    if args.command == "financial-latest":
        results = latest_financials.sync(client, dynamic_targets(client))
        return 1 if any(value.startswith("failed") for value in results.values()) else 0
    if args.command == "live":
        targets = targets_from_args(args, client)
        print(json.dumps({"event": "newsapi_targets", "count": len(targets), "codes": sorted(targets),
                          "remaining_before": newsapi_remaining()}, ensure_ascii=False))
        result = run_live_sync(targets, client=client)
        print(json.dumps({"event": "newsapi_usage", "remaining_after": newsapi_remaining()}))
    elif args.command == "reset-live":
        result = reset_live_sync(targets_from_args(args, client), client=client)
    elif args.command == "backfill-news":
        result = backfill_news(args.paths, client=client)
    elif args.command == "backfill-historical":
        result = backfill_historical(targets_from_args(args), date_start=args.start, date_end=args.end, client=client)
    else:
        result = backfill_financial(args.paths, client=client)
    _print_result(result)
    return result.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
