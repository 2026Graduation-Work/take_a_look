"""뉴스·재무 분석 트랙을 Supabase에 적재하는 명령행 진입점."""
from __future__ import annotations

import argparse
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from . import news_run, newsapi_ai, supabase_store
from .news_run import _parse_target

DEFAULT_TARGETS: dict[str, str] = {
    "005930": "삼성전자",
    "005380": "현대차",
    "035720": "카카오",
    "068270": "셀트리온",
}


@dataclass
class SyncResult:
    succeeded: list[str] = field(default_factory=list)
    failures: dict[str, str] = field(default_factory=dict)

    @property
    def exit_code(self) -> int:
        return 1 if self.failures else 0


def _failure_name(exc: Exception) -> str:
    """비밀값이 섞일 수 있는 외부 오류 메시지 대신 예외 종류만 남긴다."""
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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="분석 트랙 Supabase 적재")
    subparsers = parser.add_subparsers(dest="command", required=True)
    live = subparsers.add_parser("live", help="4종목 최근 24시간 뉴스를 수집·적재")
    live.add_argument("--target", type=_parse_target, action="append")
    news = subparsers.add_parser("backfill-news", help="뉴스 track JSON 적재")
    news.add_argument("paths", type=Path, nargs="+")
    financial = subparsers.add_parser("backfill-financial", help="재무 track JSON 적재")
    financial.add_argument("paths", type=Path, nargs="+")
    return parser


def targets_from_args(args: argparse.Namespace) -> dict[str, str]:
    return dict(args.target) if args.target else dict(DEFAULT_TARGETS)


def _print_result(result: SyncResult) -> None:
    for item in result.succeeded:
        print(f"{item}: ok")
    for item, error_name in result.failures.items():
        print(f"{item}: failed ({error_name})")


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    client = supabase_store.SupabaseRestClient.from_env()
    if args.command == "live":
        result = run_live_sync(targets_from_args(args), client=client)
    elif args.command == "backfill-news":
        result = backfill_news(args.paths, client=client)
    else:
        result = backfill_financial(args.paths, client=client)
    _print_result(result)
    return result.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
