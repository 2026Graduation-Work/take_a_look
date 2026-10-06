"""Resume-safe, additive BigKinds history import. Never modifies existing scores or Live."""

from __future__ import annotations

import argparse
import calendar
import hashlib
import json
import math
from collections.abc import Mapping
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import pandas as pd

from .. import preprocess
from . import collectors, news_run, news_tracks, supabase_store
from .supabase_sync import DEFAULT_TARGETS, SyncResult, _failure_name

CACHE_VERSION = "historical-additive-v2-batch32"
PROCESSED_DIR = Path(__file__).resolve().parents[1] / "data" / "processed"
DAILY_CSVS = {
    code: PROCESSED_DIR
    / ("news_sentiment_daily.csv" if code == "005930" else f"news_sentiment_daily_{code}.csv")
    for code in ("005930", "005380", "035720", "068270")
}


def dates(start: str, end: str) -> list[str]:
    first, last = date.fromisoformat(start), date.fromisoformat(end)
    if first > last:
        raise ValueError("start must be <= end")
    return [(first + timedelta(days=i)).isoformat() for i in range((last - first).days + 1)]


def source_ranges(ticker: str, company: str, data_dir: Path) -> list[tuple[Path, str, str]]:
    ranges = []
    for path in preprocess.find_corpus_workbooks(data_dir, ticker, company):
        parsed = preprocess._parse_workbook_name(path.name)
        if parsed is None:
            raise ValueError(f"workbook filename needs a date range: {path.name}")
        _, _, start, end = parsed
        ranges.append(
            (path, date.fromisoformat(start).isoformat(), date.fromisoformat(end).isoformat())
        )
    return ranges


def read_daily_csv(path: Path) -> dict[str, dict[str, Any]]:
    """Only reuse explicitly labelled KR-FinBERT aggregates; do not invent missing stats."""
    if not path.exists():
        return {}
    if "KR-FinBERT" not in path.read_text(encoding="utf-8-sig").splitlines()[0]:
        raise ValueError("daily CSV must identify KR-FinBERT provenance")
    frame = pd.read_csv(path, comment="#", encoding="utf-8-sig")
    if not {"date", "n", "score"}.issubset(frame.columns) or frame["date"].duplicated().any():
        raise ValueError("invalid daily CSV columns/duplicates")
    result = {}
    for row in frame.to_dict("records"):
        day = date.fromisoformat(str(row["date"])).isoformat()
        count, score = float(row["n"]), float(row["score"])
        if (
            not math.isfinite(count)
            or count <= 0
            or not count.is_integer()
            or not math.isfinite(score)
            or not -1 <= score <= 1
        ):
            raise ValueError("invalid daily CSV score/count")
        result[day] = {
            "date": day,
            "status": "ok",
            "sentiment_mean": score,
            "sentiment_std": None,
            "article_count": int(count),
            "publisher_count": 0,
        }
    return result


def daily_rows(
    client: Any, ticker: str, *, start: str | None = None, end: str | None = None
) -> list[dict[str, Any]]:
    params = {
        "select": "sentiment_date,status,sentiment_mean,sentiment_std,article_count,publisher_count",
        "stock_code": f"eq.{ticker}",
        "track": "eq.historical",
        "order": "sentiment_date.asc",
    }
    if start is not None or end is not None:
        if start is None or end is None:
            raise ValueError("both date bounds are required")
        dates(start, end)
        params["and"] = f"(sentiment_date.gte.{start},sentiment_date.lte.{end})"
    return client.select("news_sentiment_daily", params=params)


def audit_coverage(
    ticker: str, company: str, start: str, end: str, data_dir: Path, rows: list[dict[str, Any]]
) -> dict[str, Any]:
    ranges = source_ranges(ticker, company, data_dir)
    available = {day for _, first, last in ranges for day in dates(first, last)}
    by_day = {row["sentiment_date"]: row for row in rows}
    result: dict[str, Any] = {
        "ticker": ticker,
        "company": company,
        "start": min(by_day, default=None),
        "end": max(by_day, default=None),
        "total_rows": len(by_day),
        "years": {},
    }
    for year in range(date.fromisoformat(start).year, date.fromisoformat(end).year + 1):
        expected = dates(max(start, f"{year}-01-01"), min(end, f"{year}-12-31"))
        stored = [by_day[d] for d in expected if d in by_day]
        result["years"][str(year)] = {
            "rows": len(stored),
            "scored_days": sum(r["sentiment_mean"] is not None for r in stored),
            "article_count": sum(r["article_count"] for r in stored),
            "source_missing_dates": [d for d in expected if d not in available],
            "database_missing_dates": [d for d in expected if d in available and d not in by_day],
            "no_relevant_article_dates": [
                d for d in expected if d in by_day and by_day[d]["article_count"] == 0
            ],
        }
    return result


def _fingerprint(
    ranges: list[tuple[Path, str, str]], start: str, end: str, csv_path: Path | None, company: str
) -> str:
    from .config import SETTINGS

    digest = hashlib.sha256(
        f"{CACHE_VERSION}:{start}:{end}:{company}:{SETTINGS.finbert_model}".encode()
    )
    for path, first, last in ranges:
        if first <= end and last >= start:
            digest.update(path.name.encode())
            digest.update(path.read_bytes())
    if csv_path and csv_path.exists():
        digest.update(csv_path.read_bytes())
    return digest.hexdigest()


def _insert_chunks(client: Any, table: str, rows: list[dict[str, Any]], key: str) -> None:
    for offset in range(0, len(rows), 500):
        client.upsert(table, rows[offset : offset + 500], on_conflict=key, ignore_duplicates=True)


def _persist_month(
    client: Any, ticker: str, start: str, end: str, payload: dict[str, Any], needed: set[str]
) -> None:
    articles = [
        {
            "stock_code": ticker,
            "track": "historical",
            "news_id": a["news_id"],
            "title": a["title"],
            "press": a["press"],
            "url": a["url"],
            "article_date": a["date"],
            "published_at": a.get("published_at") or None,
            "event_id": a.get("event_id", ""),
            "sentiment_score": a["sentiment_score"],
        }
        for a in payload["articles"]
    ]
    # Daily rows are the completion marker: upload their article children first.
    _insert_chunks(client, "news_articles", articles, "stock_code,track,news_id")
    rows = [
        {
            "stock_code": ticker,
            "track": "historical",
            "sentiment_date": p["date"],
            **{
                k: p[k]
                for k in (
                    "status",
                    "sentiment_mean",
                    "sentiment_std",
                    "article_count",
                    "publisher_count",
                )
            },
        }
        for p in payload["timeline"]
        if p["date"] in needed
    ]
    _insert_chunks(client, "news_sentiment_daily", rows, "stock_code,track,sentiment_date")


def run_backfill(
    targets: Mapping[str, str],
    *,
    date_start: str,
    date_end: str,
    data_dir: Path,
    cache_dir: Path,
    client: Any,
    daily_csvs: Mapping[str, Path] | None = None,
) -> SyncResult:
    dates(date_start, date_end)
    result = SyncResult()
    for ticker, company in targets.items():
        try:
            parents = client.select(
                "news_sentiment_tracks",
                params={
                    "select": "stock_code,source,backend",
                    "stock_code": f"eq.{ticker}",
                    "track": "eq.historical",
                    "order": "stock_code.asc",
                },
            )
            if (
                not parents
                or parents[0].get("source") != "bigkinds"
                or parents[0].get("backend") != "kr-finbert"
            ):
                raise supabase_store.SupabaseWriteError(
                    "existing validated BigKinds historical parent required",
                    code="historical_parent_required",
                )
            ranges = source_ranges(ticker, company, data_dir)
            available = {d for _, first, last in ranges for d in dates(first, last)}
            stored = {r["sentiment_date"] for r in daily_rows(client, ticker)}
            csv_path = (daily_csvs or {}).get(ticker)
            reused = read_daily_csv(csv_path) if csv_path else {}
        except Exception as exc:
            result.failures[ticker] = _failure_name(exc)
            print(f"{ticker}: failed ({result.failures[ticker]})", flush=True)
            continue
        for year in range(
            date.fromisoformat(date_start).year, date.fromisoformat(date_end).year + 1
        ):
            label = f"{ticker}/{year}"
            missing_source = (
                set(dates(max(date_start, f"{year}-01-01"), min(date_end, f"{year}-12-31")))
                - available
            )
            if missing_source:
                result.skipped[label] = f"missing_source_days={len(missing_source)}"
                print(f"{label}: missing source {len(missing_source)} days", flush=True)
            failed = False
            for month in range(1, 13):
                start = max(date_start, f"{year}-{month:02}-01")
                end = min(date_end, f"{year}-{month:02}-{calendar.monthrange(year, month)[1]}")
                if start > end:
                    continue
                needed = set(dates(start, end)) & available - stored
                if not needed:
                    continue
                try:
                    fingerprint = _fingerprint(ranges, start, end, csv_path, company)
                    path = cache_dir / ticker / f"{year}-{month:02}.json"
                    payload = json.loads(path.read_text()) if path.exists() else None
                    if (
                        not payload
                        or payload.get("fingerprint") != fingerprint
                        or not needed <= {p["date"] for p in payload["timeline"]}
                    ):
                        csv_days = needed & reused.keys()
                        infer_days = needed - csv_days
                        print(
                            f"{label}/{month:02}: start reuse={len(csv_days)} infer_days={len(infer_days)}",
                            flush=True,
                        )

                        def loader(
                            *args: Any, wanted: set[str] = infer_days, **kwargs: Any
                        ) -> list[dict[str, Any]]:
                            return [
                                a
                                for a in preprocess.load_news_range(*args, **kwargs)
                                if a["date"] in wanted
                            ]

                        if infer_days:
                            track = news_run.run_historical_cycle(
                                ticker,
                                company,
                                start,
                                end,
                                data_dir=data_dir,
                                loader=loader,
                                require_finbert=True,
                                inference_batch_size=32,
                            )
                            if track["backend"] != "kr-finbert" and track["articles"]:
                                raise ValueError("historical inference requires KR-FinBERT")
                        else:
                            track = {"timeline": [], "articles": []}
                        payload = {
                            "fingerprint": fingerprint,
                            "timeline": [p for p in track["timeline"] if p["date"] in infer_days]
                            + [reused[d] for d in sorted(csv_days)],
                            "articles": track["articles"],
                            "reused_csv_dates": sorted(csv_days),
                        }
                        news_tracks.write_track_json(payload, path)
                    _persist_month(client, ticker, start, end, payload, needed)
                    # Confirm persisted dates; never trust a success-only local checkpoint.
                    confirmed = {
                        r["sentiment_date"]
                        for r in daily_rows(client, ticker, start=start, end=end)
                    }
                    if not needed <= confirmed:
                        raise ValueError("daily write verification failed")
                    stored.update(confirmed)
                    print(f"{label}/{month:02}: ok {len(needed)} days", flush=True)
                except Exception as exc:
                    failed = True
                    result.failures[f"{label}/{month:02}"] = _failure_name(exc)
                    print(f"{label}/{month:02}: failed ({_failure_name(exc)})", flush=True)
            if not failed:
                status = "partial" if missing_source else "ok"
                if not missing_source:
                    result.succeeded.append(label)
                print(
                    f"{label}: {status} stored={sum(d.startswith(str(year)) for d in stored)}",
                    flush=True,
                )
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", type=news_run._parse_target, action="append")
    parser.add_argument("--start", default="2016-01-01")
    parser.add_argument("--end", required=True)
    parser.add_argument("--data-dir", type=Path, default=collectors.DATA_DIR)
    parser.add_argument("--cache-dir", type=Path, default=Path("out/historical_backfill"))
    parser.add_argument("--audit-only", action="store_true")
    args = parser.parse_args()
    client = supabase_store.SupabaseRestClient.from_env()
    targets = dict(args.target) if args.target else DEFAULT_TARGETS
    result = (
        SyncResult()
        if args.audit_only
        else run_backfill(
            targets,
            date_start=args.start,
            date_end=args.end,
            data_dir=args.data_dir,
            cache_dir=args.cache_dir,
            client=client,
            daily_csvs=DAILY_CSVS,
        )
    )
    reports = []
    for ticker, company in targets.items():
        try:
            reports.append(
                audit_coverage(
                    ticker, company, args.start, args.end, args.data_dir, daily_rows(client, ticker)
                )
            )
        except Exception as exc:
            result.failures[f"{ticker}/audit"] = _failure_name(exc)
            reports.append({"ticker": ticker, "company": company, "error": _failure_name(exc)})
    report_path = args.cache_dir / "coverage.json"
    news_tracks.write_track_json(
        {
            "start": args.start,
            "end": args.end,
            "stocks": reports,
            "failures": result.failures,
            "skipped": result.skipped,
        },
        report_path,
    )
    print(f"coverage report: {report_path}", flush=True)
    return result.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
