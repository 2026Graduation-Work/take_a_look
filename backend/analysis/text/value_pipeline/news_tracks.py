"""과거 BigKinds와 최근 NewsAPI.ai가 공유하는 뉴스 심리지수 집계.

두 트랙은 입력 소스와 시간 창만 다르고, 관련성 필터와 감성 산식은
동일한 결정론적 코어를 사용한다. API 본문은 추론 후 결과에 포함하지 않는다.
"""
from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from . import sentiment
from .agents import relevant_indices

KST = ZoneInfo("Asia/Seoul")
_FORBIDDEN_PERSISTED_FIELDS = {"body", "summary", "content"}


def _article_date(item: dict[str, Any]) -> date | None:
    published = _published_datetime(item.get("published_at"))
    if published is not None:
        return published.date()
    value = str(item.get("date") or str(item.get("published_at") or "")[:10])
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def _article_text(item: dict[str, Any]) -> str:
    return f"{item.get('title', '')} {item.get('summary', '')}".strip()


def _score_relevant(
    items: list[dict[str, Any]],
    company_name: str,
    *,
    relevance_key_override: str | None = None,
    require_finbert: bool = False,
) -> tuple[list[tuple[dict[str, Any], float]], str]:
    relevant = [
        items[index]
        for index in relevant_indices(
            items, company_name, key_override=relevance_key_override
        )
    ]
    scores, backend = sentiment.score_texts(
        [_article_text(item) for item in relevant], require_finbert=require_finbert
    )
    return list(zip(relevant, scores, strict=False)), backend


def _stats(
    scored: list[tuple[dict[str, Any], float]], start: date, end: date
) -> dict[str, Any]:
    rows = [pair for pair in scored if (day := _article_date(pair[0])) and start <= day <= end]
    scores = [score for _, score in rows]
    publishers = {str(item.get("press") or "") for item, _ in rows if item.get("press")}
    if scores:
        mean, std = sentiment.aggregate(scores)
        status = "ok"
    else:
        mean, std, status = None, None, "insufficient_data"
    return {
        "start": start.isoformat(),
        "end": end.isoformat(),
        "status": status,
        "sentiment_mean": mean,
        "sentiment_std": std,
        "article_count": len(rows),
        "publisher_count": len(publishers),
    }


def _timeline(
    scored: list[tuple[dict[str, Any], float]], start: date, end: date
) -> list[dict[str, Any]]:
    points = []
    day = start
    while day <= end:
        point = _stats(scored, day, day)
        point["date"] = day.isoformat()
        point.pop("start")
        point.pop("end")
        points.append(point)
        day += timedelta(days=1)
    return points


def _window_stats(
    scored: list[tuple[dict[str, Any], float]], start: datetime, end: datetime
) -> dict[str, Any]:
    scores = [score for _, score in scored]
    publishers = {str(item.get("press") or "") for item, _ in scored if item.get("press")}
    if scores:
        mean, std = sentiment.aggregate(scores)
        status = "ok"
    else:
        mean, std, status = None, None, "insufficient_data"
    return {
        "start": start.isoformat(),
        "end": end.isoformat(),
        "status": status,
        "sentiment_mean": mean,
        "sentiment_std": std,
        "article_count": len(scored),
        "publisher_count": len(publishers),
    }


def _safe_article(item: dict[str, Any], score: float, ticker: str) -> dict[str, Any]:
    article_day = _article_date(item)
    return {
        "news_id": str(item.get("news_id") or ""),
        "ticker": ticker,
        "title": str(item.get("title") or ""),
        "press": str(item.get("press") or ""),
        "url": str(item.get("url") or ""),
        "date": article_day.isoformat() if article_day else "",
        "published_at": str(item.get("published_at") or ""),
        "event_id": str(item.get("event_id") or ""),
        "sentiment_score": round(float(score), 4),
    }


def _published_datetime(value: object) -> datetime | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.replace(tzinfo=KST) if parsed.tzinfo is None else parsed.astimezone(KST)


def _coverage(
    fetched_count: int,
    scored: list[tuple[dict[str, Any], float]],
    as_of: datetime,
) -> dict[str, Any]:
    publishers = {str(item.get("press") or "") for item, _ in scored if item.get("press")}
    published = [
        parsed
        for item, _ in scored
        if (parsed := _published_datetime(item.get("published_at"))) is not None
    ]
    newest = max(published) if published else None
    lag = max(0, round((as_of - newest).total_seconds() / 60)) if newest else None
    return {
        "fetched_count": fetched_count,
        "relevant_count": len(scored),
        "publisher_count": len(publishers),
        "newest_published_at": newest.isoformat() if newest else None,
        "lag_minutes": lag,
    }


def build_live_track(
    items: list[dict[str, Any]],
    ticker: str,
    company_name: str,
    *,
    as_of: datetime | None = None,
    provider_metadata: Mapping[str, Any] | None = None,
    relevance_key_override: str | None = None,
    require_finbert: bool = False,
) -> dict[str, Any]:
    """기준시각 직전 24시간의 뉴스 심리지수를 만든다."""
    now = as_of or datetime.now(KST)
    now = now.replace(tzinfo=KST) if now.tzinfo is None else now.astimezone(KST)
    window_start = now - timedelta(hours=24)
    end = now.date()
    start = window_start.date()
    bounded = [
        item
        for item in items
        if (published := _published_datetime(item.get("published_at"))) is not None
        and window_start <= published <= now
    ]
    in_window, backend = _score_relevant(
        bounded,
        company_name,
        relevance_key_override=relevance_key_override,
        require_finbert=require_finbert,
    )
    coverage = _coverage(len(items), in_window, now)
    if provider_metadata:
        coverage.update(
            {
                "provider_total_results": provider_metadata.get("total_results"),
                "provider_returned_count": provider_metadata.get("returned_count"),
                "provider_pages": provider_metadata.get("pages"),
                "provider_truncated": bool(provider_metadata.get("truncated")),
            }
        )
    is_partial = bool(provider_metadata and provider_metadata.get("truncated"))
    return {
        "schema_version": "1.0",
        "track": "live",
        "scope": {"ticker": ticker, "company_name": company_name},
        "source": "newsapi_ai",
        "as_of": now.isoformat(),
        "backend": backend,
        "status": "partial" if is_partial else ("ok" if in_window else "insufficient_data"),
        "coverage": coverage,
        "window": _window_stats(in_window, window_start, now),
        "today": _stats(in_window, end, end),
        "recent_7d": _stats(in_window, start, end),
        "timeline": _timeline(in_window, start, end),
        "articles": [_safe_article(item, score, ticker) for item, score in in_window],
    }


def build_historical_track(
    items: list[dict[str, Any]],
    ticker: str,
    company_name: str,
    *,
    date_start: str,
    date_end: str,
) -> dict[str, Any]:
    """BigKinds 수동 다운로드 기사로 일별 심리지수를 만든다."""
    start = date.fromisoformat(date_start)
    end = date.fromisoformat(date_end)
    if start > end:
        raise ValueError("date_start는 date_end보다 늦을 수 없습니다.")
    bounded = [
        item
        for item in items
        if (day := _article_date(item)) is not None and start <= day <= end
    ]
    scored, backend = _score_relevant(bounded, company_name)
    return {
        "schema_version": "1.0",
        "track": "historical",
        "scope": {"ticker": ticker, "company_name": company_name},
        "source": "bigkinds",
        "as_of": datetime.combine(end, datetime.max.time(), tzinfo=KST).isoformat(),
        "backend": backend,
        "status": "ok" if scored else "insufficient_data",
        "coverage": _coverage(len(bounded), scored, datetime.combine(end, datetime.max.time(), tzinfo=KST)),
        "window": _stats(scored, start, end),
        "timeline": _timeline(scored, start, end),
        "articles": [_safe_article(item, score, ticker) for item, score in scored],
    }


def _assert_safe_to_persist(value: object) -> None:
    if isinstance(value, dict):
        overlap = _FORBIDDEN_PERSISTED_FIELDS.intersection(value)
        if overlap:
            raise ValueError(f"본문 저장 금지 필드: {sorted(overlap)}")
        for child in value.values():
            _assert_safe_to_persist(child)
    elif isinstance(value, list):
        for child in value:
            _assert_safe_to_persist(child)


def write_track_json(output: dict[str, Any], path: Path) -> None:
    """본문 미포함을 검증한 후 JSON을 원자적으로 저장한다."""
    _assert_safe_to_persist(output)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(f"{path.suffix}.tmp")
    temporary.write_text(
        json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    temporary.replace(path)
