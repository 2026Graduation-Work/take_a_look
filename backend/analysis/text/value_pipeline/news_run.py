"""뉴스 심리지수 2-track 실행 진입점."""
from __future__ import annotations

import argparse
import sys
import time
from collections.abc import Callable, Mapping
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from . import collectors, news_tracks, newsapi_ai

KST = ZoneInfo("Asia/Seoul")
Fetcher = Callable[..., newsapi_ai.ArticleBatch | list[dict[str, Any]]]
Loader = Callable[..., list[dict[str, Any]]]

# NewsAPI.ai의 한국어 색인은 '삼성전자' 붙임말 검색을 0건으로 반환한다.
# 수집은 '삼성'으로 넓히되, 삼성생명·삼성 라이온즈 등을 제외하도록
# 관련성 판정은 '삼성전자' 정확 키워드를 유지한다.
LIVE_QUERY_OVERRIDES: dict[str, tuple[str, str]] = {
    "005930": ("삼성", "삼성전자"),
}


def run_live_cycle(
    targets: Mapping[str, str],
    *,
    fetcher: Fetcher = newsapi_ai.fetch_article_batch,
    as_of: datetime | None = None,
    page_size: int = 100,
    require_finbert: bool = False,
    extra_page: bool = False,
) -> dict[str, dict[str, Any]]:
    """종목별 API 검색으로 각 종목의 직전 24시간 트랙을 만든다.

    extra_page면 첫 페이지가 꽉 차고 잘렸을 때만 2페이지(그다음 오래된 100건)를 더 받는다.
    """
    if not targets:
        raise ValueError("최소 하나의 대상 종목이 필요합니다.")
    now = as_of or datetime.now(KST)
    now = now.replace(tzinfo=KST) if now.tzinfo is None else now.astimezone(KST)
    end = now.date()
    start = (now - timedelta(hours=24)).date()
    # KST 자정은 UTC 전날 15시이므로 공급자 날짜 범위를 하루 넓힌 뒤
    # build_live_track에서 KST 날짜로 정확히 잘라낸다.
    query_start = start - timedelta(days=1)
    outputs: dict[str, dict[str, Any]] = {}
    for ticker, company_name in targets.items():
        search_keyword, relevance_key_override = LIVE_QUERY_OVERRIDES.get(
            ticker, (company_name, None)
        )
        fetched = fetcher(
            [search_keyword],
            query_start.isoformat(),
            end.isoformat(),
            page_size=page_size,
        )
        if isinstance(fetched, newsapi_ai.ArticleBatch):
            items = fetched.articles
            if extra_page and fetched.truncated and fetched.returned_count >= page_size:
                more = fetcher([search_keyword], query_start.isoformat(), end.isoformat(), page_size=page_size, page=2)
                seen = {item["news_id"] for item in items}
                items = items + [item for item in more.articles if item["news_id"] not in seen]
            total = fetched.total_results
            provider_metadata = {
                "total_results": total,
                "returned_count": len(items),
                "pages": fetched.pages,
                "truncated": total is not None and total > len(items),
            }
        else:
            items = fetched
            provider_metadata = None
        outputs[ticker] = news_tracks.build_live_track(
            items,
            ticker,
            company_name,
            as_of=now,
            provider_metadata=provider_metadata,
            relevance_key_override=relevance_key_override,
            require_finbert=require_finbert,
        )
    return outputs


def write_live_outputs(outputs: Mapping[str, dict[str, Any]], out_dir: Path) -> None:
    for ticker, output in outputs.items():
        news_tracks.write_track_json(output, out_dir / f"{ticker}_live.json")


def run_historical_cycle(
    ticker: str,
    company_name: str,
    date_start: str,
    date_end: str,
    *,
    loader: Loader = collectors.preprocess.load_news_range,
    data_dir: Path = collectors.DATA_DIR,
    require_finbert: bool = False,
    inference_batch_size: int = 16,
) -> dict[str, Any]:
    """BigKinds 워크북에서 기간 기사를 읽어 과거 트랙을 만든다."""
    start = date.fromisoformat(date_start)
    end = date.fromisoformat(date_end)
    if start > end:
        raise ValueError("date_start는 date_end보다 늦을 수 없습니다.")
    items = loader(
        company_name,
        start.isoformat(),
        end.isoformat(),
        data_dir,
        ticker=ticker,
    )
    return news_tracks.build_historical_track(
        items,
        ticker,
        company_name,
        date_start=date_start,
        date_end=date_end,
        require_finbert=require_finbert,
        inference_batch_size=inference_batch_size,
    )


def _parse_target(value: str) -> tuple[str, str]:
    ticker, separator, company = value.partition(":")
    if not separator or not ticker.strip() or not company.strip():
        raise argparse.ArgumentTypeError("대상은 종목코드:회사명 형식이어야 합니다.")
    return ticker.strip(), company.strip()


def _live_command(args: argparse.Namespace) -> None:
    if args.watch and args.interval_minutes <= 0:
        raise ValueError("--interval-minutes는 1 이상이어야 합니다.")
    targets = dict(args.target)
    failure_count = 0
    while True:
        try:
            outputs = run_live_cycle(
                targets,
                page_size=args.page_size,
                require_finbert=getattr(args, "require_finbert", False),
            )
        except newsapi_ai.NewsApiAiConfigurationError:
            raise
        except newsapi_ai.NewsApiAiError as exc:
            if not args.watch:
                raise
            failure_count += 1
            retry_seconds = min(60 * (2 ** (failure_count - 1)), 15 * 60)
            print(
                f"NewsAPI.ai 일시 오류: {exc}. {retry_seconds}초 후 재시도합니다.",
                file=sys.stderr,
            )
            time.sleep(retry_seconds)
            continue
        failure_count = 0
        write_live_outputs(outputs, args.out_dir)
        for ticker, output in outputs.items():
            coverage = output["coverage"]
            print(
                f"{ticker}: status={output['status']} "
                f"relevant={coverage['relevant_count']} backend={output['backend']}"
            )
        if not args.watch:
            return
        time.sleep(args.interval_minutes * 60)


def _historical_command(args: argparse.Namespace) -> None:
    ticker, company_name = args.target
    output = run_historical_cycle(
        ticker,
        company_name,
        args.start,
        args.end,
        data_dir=args.data_dir,
    )
    output_path = args.out or Path(f"out/news_tracks/{ticker}_historical.json")
    news_tracks.write_track_json(output, output_path)
    print(
        f"{ticker}: status={output['status']} "
        f"relevant={output['coverage']['relevant_count']} backend={output['backend']}"
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="뉴스 심리지수 수집·집계")
    subparsers = parser.add_subparsers(dest="command", required=True)
    live = subparsers.add_parser("live", help="NewsAPI.ai 최근 7일/오늘 트랙")
    live.add_argument(
        "--target", type=_parse_target, action="append", required=True, metavar="TICKER:COMPANY"
    )
    live.add_argument("--out-dir", type=Path, default=Path("out/news_tracks"))
    live.add_argument("--page-size", type=int, default=100)
    live.add_argument("--require-finbert", action="store_true")
    live.add_argument("--watch", action="store_true", help="1시간 주기 반복 수집")
    live.add_argument("--interval-minutes", type=int, default=60)
    live.set_defaults(handler=_live_command)

    historical = subparsers.add_parser("historical", help="BigKinds 과거 일별 트랙")
    historical.add_argument("--target", type=_parse_target, required=True, metavar="TICKER:COMPANY")
    historical.add_argument("--start", required=True, help="YYYY-MM-DD")
    historical.add_argument("--end", required=True, help="YYYY-MM-DD")
    historical.add_argument("--data-dir", type=Path, default=collectors.DATA_DIR)
    historical.add_argument("--out", type=Path, default=None)
    historical.set_defaults(handler=_historical_command)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    args.handler(args)


if __name__ == "__main__":
    main()
