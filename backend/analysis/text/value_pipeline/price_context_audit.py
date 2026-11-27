"""Read public source coverage for selected dates without fetching article bodies."""
from __future__ import annotations

import argparse
import base64
import binascii
import json
import math
import os
from collections import Counter
from collections.abc import Callable
from datetime import date, datetime, timedelta
from typing import Any
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from .supabase_store import SupabaseRestClient, SupabaseWriteError

CODES = ("005930", "005380", "068270", "035720")
KST = ZoneInfo("Asia/Seoul")


def _summary(dates: list[str]) -> dict:
    return {"count": len(dates), "first": min(dates, default=None), "last": max(dates, default=None)}


def _news_date(row: dict) -> str:
    published_at = row["published_at"]
    if published_at is None:
        return row["article_date"]
    timestamp = datetime.fromisoformat(published_at)
    if timestamp.tzinfo is None:
        raise ValueError("published_at has no time zone")
    return timestamp.astimezone(KST).date().isoformat()


def _news_summary(rows: list[dict]) -> dict:
    ids = Counter((row["stock_code"], row["news_id"]) for row in rows if row["news_id"])
    urls = Counter((row["stock_code"], row["url"]) for row in rows if row["url"])
    return {
        **_summary([_news_date(row) for row in rows]),
        "missing_published_at": sum(row["published_at"] is None for row in rows),
        "duplicate_news_id_rows": sum(count - 1 for count in ids.values()),
        "duplicate_url_rows": sum(count - 1 for count in urls.values()),
    }


def _kospi_on_date(quotes: object) -> dict:
    if not isinstance(quotes, list):
        return {"status": "invalid_kospi"}
    matches = [quote for quote in quotes if isinstance(quote, dict) and quote.get("symbol") == "KOSPI"]
    if not matches:
        return {"status": "missing_kospi"}
    change = matches[0].get("changePercent")
    if len(matches) != 1 or type(change) not in (int, float) or not math.isfinite(change):
        return {"status": "invalid_kospi"}
    return {"status": "ok", "change_percent": change}


def _market_report(rows: list[dict], dates: list[date]) -> dict:
    by_day = {row["status_date"]: _kospi_on_date(row["index_quotes"]) for row in rows}
    return {
        **_summary(list(by_day)),
        "dates": {
            day.isoformat(): by_day.get(day.isoformat(), {"status": "missing_market_row"})
            for day in dates
        },
    }


def _stock_report(
    rows: list[dict], dates: list[date], radius: int, get_date: Callable, summarize: Callable,
) -> dict:
    stocks = {}
    for code in CODES:
        own_rows = [row for row in rows if row["stock_code"] == code]
        counts = Counter(date.fromisoformat(get_date(row)) for row in own_rows)
        nearby = {}
        for day in dates:
            first = day - timedelta(days=radius)
            last = day + timedelta(days=radius)
            nearby[day.isoformat()] = {
                "from": first.isoformat(),
                "through": last.isoformat(),
                "counts_by_day": {
                    observed.isoformat(): counts[observed]
                    for observed in sorted(counts)
                    if first <= observed <= last
                },
            }
        stocks[code] = {**summarize(own_rows), "dates": nearby}
    return {**summarize(rows), "stocks": stocks}


def audit(read: Callable[..., list[dict]], dates: list[date], radius: int) -> tuple[dict, bool]:
    filters = {"stock_code": f"in.({','.join(CODES)})"}
    reports = {
        "disclosures": ({
            **filters, "select": "stock_code,filed_on", "order": "filed_on.asc,rcept_no.asc",
        }, lambda rows: _stock_report(
            rows, dates, radius, lambda row: row["filed_on"],
            lambda items: _summary([row["filed_on"] for row in items]),
        )),
        "news_articles": ({
            **filters,
            "select": "stock_code,article_date,published_at,news_id,url",
            "order": "article_date.asc,stock_code.asc,track.asc,news_id.asc",
        }, lambda rows: _stock_report(rows, dates, radius, _news_date, _news_summary)),
        "market_status": ({
            "select": "status_date,index_quotes", "order": "status_date.asc",
        }, lambda rows: _market_report(rows, dates)),
    }
    out: dict[str, Any] = {"coverage": "unverified", "date_zone": "Asia/Seoul"}
    failed = False
    for table, (params, summarize) in reports.items():
        try:
            out[table] = {"status": "ok", **summarize(read(table, params=params))}
        except SupabaseWriteError:
            out[table] = {"status": "query_failed"}
            failed = True
        except (KeyError, TypeError, ValueError, OverflowError):
            out[table] = {"status": "invalid_response"}
            failed = True
    return out, failed


def _publishable_key(key: str) -> bool:
    if key.startswith("sb_publishable_"):
        return True
    try:
        _, payload, _ = key.split(".")
        claims = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
    except (ValueError, binascii.Error, UnicodeError):
        return False
    return isinstance(claims, dict) and claims.get("role") == "anon"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--date", action="append", type=date.fromisoformat, required=True)
    parser.add_argument("--radius", type=int, default=3, choices=range(8), help="주변 자료의 앞뒤 달력일 수")
    args = parser.parse_args(argv)
    base_url = os.getenv("NEXT_PUBLIC_SUPABASE_URL", "").strip()
    key = os.getenv("NEXT_PUBLIC_SUPABASE_ANON_KEY", "").strip()
    try:
        url = urlsplit(base_url)
        configured = url.scheme == "https" and url.hostname and not url.username and _publishable_key(key)
    except ValueError:
        configured = False
    if not configured:
        print(json.dumps({"status": "not_configured", "reason": "public_supabase_credentials_required"}))
        return 1
    result, failed = audit(SupabaseRestClient(base_url, key).select, sorted(set(args.date)), args.radius)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return int(failed)


if __name__ == "__main__":
    raise SystemExit(main())
