"""NewsAPI.ai(Event Registry) 한국어 뉴스 수집 어댑터.

여러 종목 키워드를 OR 한 번으로 묶어 API 토큰 소모를 제한한다. 본문은
FinBERT 추론을 위한 일시 필드(`summary`)로만 반환하며, 저장 계약은
``news_tracks``에서 별도로 강제한다.
"""
from __future__ import annotations

import unicodedata
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

import requests

from .config import SETTINGS

API_URL = "https://eventregistry.org/api/v1/article/getArticles"
KST = ZoneInfo("Asia/Seoul")


@dataclass(frozen=True)
class ArticleBatch:
    """한 번의 공급자 호출 결과와 완전성 메타데이터."""

    articles: list[dict[str, str]]
    total_results: int | None
    returned_count: int
    pages: int | None
    truncated: bool


class NewsApiAiError(RuntimeError):
    """NewsAPI.ai 호출/응답 오류."""


class NewsApiAiConfigurationError(NewsApiAiError):
    """필수 설정 누락."""


def _iso_date(value: str, field_name: str) -> str:
    try:
        return date.fromisoformat(value).isoformat()
    except (TypeError, ValueError) as exc:
        raise NewsApiAiConfigurationError(
            f"{field_name}는 YYYY-MM-DD 형식이어야 합니다."
        ) from exc


def _error_message(payload: dict[str, Any]) -> str:
    error = payload.get("error")
    if isinstance(error, dict):
        return str(error.get("message") or error.get("msg") or error)
    return str(error or "NewsAPI.ai 알 수 없는 오류")


def _optional_int(value: object) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _kst_day(published_at: str) -> str | None:
    if not published_at:
        return None
    try:
        parsed = datetime.fromisoformat(published_at.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(KST).date().isoformat()


def _display_text(value: object) -> str:
    normalized = unicodedata.normalize("NFC", str(value or ""))
    return " ".join(normalized.split())


def _has_broken_characters(value: str) -> bool:
    return "\ufffd" in value or any(ord(character) < 32 for character in value)


def _publisher_domain(source_uri: object, article_url: object) -> str:
    raw_source = _display_text(source_uri)
    if raw_source and "." in raw_source and " " not in raw_source:
        candidate = raw_source if "://" in raw_source else f"https://{raw_source}"
        hostname = urlparse(candidate).hostname
        if hostname:
            return hostname.removeprefix("www.")
    hostname = urlparse(_display_text(article_url)).hostname
    return hostname.removeprefix("www.") if hostname else ""


def _publisher_name(source: dict[str, Any], article_url: object) -> str:
    domain = _publisher_domain(source.get("uri"), article_url)
    if domain:
        return domain
    title = _display_text(source.get("title"))
    looks_like_name = (
        title
        and len(title) <= 32
        and len(title.split()) <= 4
        and not any(mark in title for mark in ("…", "?", "!"))
        and not _has_broken_characters(title)
    )
    if looks_like_name:
        return title
    return title if looks_like_name else ""


def _normalize_article(row: dict[str, Any]) -> dict[str, str] | None:
    news_id = _display_text(row.get("uri"))
    title = _display_text(row.get("title"))
    if not news_id or not title or _has_broken_characters(title):
        return None
    published_at = str(
        row.get("dateTimePub") or row.get("dateTime") or row.get("date") or ""
    ).strip()
    article_date = _kst_day(published_at) or str(
        row.get("date") or published_at[:10]
    ).strip()
    source = row.get("source") if isinstance(row.get("source"), dict) else {}
    article_url = _display_text(row.get("url"))
    return {
        "news_id": news_id,
        "title": title,
        "summary": _display_text(row.get("body")),
        "url": article_url,
        "press": _publisher_name(source, article_url),
        "date": article_date,
        "published_at": published_at,
        "event_id": str(row.get("eventUri") or "").strip(),
    }


def fetch_article_batch(
    keywords: list[str],
    date_start: str,
    date_end: str,
    *,
    page_size: int = 100,
    api_key: str | None = None,
    session: Any = requests,
    timeout: int = 20,
) -> ArticleBatch:
    """한국어 뉴스를 최대 100건 수집하고 공급자 완전성을 함께 반환한다."""
    key = (api_key if api_key is not None else SETTINGS.newsapi_ai_key) or ""
    key = key.strip()
    if not key:
        raise NewsApiAiConfigurationError("NEWSAPI_AI_KEY가 필요합니다.")

    cleaned = list(dict.fromkeys(k.strip() for k in keywords if k and k.strip()))
    if not cleaned:
        raise NewsApiAiConfigurationError("최소 하나의 뉴스 검색어가 필요합니다.")
    start = _iso_date(date_start, "date_start")
    end = _iso_date(date_end, "date_end")
    if start > end:
        raise NewsApiAiConfigurationError("date_start는 date_end보다 늦을 수 없습니다.")
    if not 1 <= page_size <= 100:
        raise NewsApiAiConfigurationError("page_size는 1~100 사이여야 합니다.")

    payload: dict[str, Any] = {
        "action": "getArticles",
        "keyword": cleaned,
        "keywordOper": "or",
        "keywordLoc": "body,title",
        "lang": "kor",
        "dateStart": start,
        "dateEnd": end,
        "dataType": ["news"],
        "isDuplicateFilter": "skipDuplicates",
        "articlesPage": 1,
        "articlesCount": page_size,
        "articlesSortBy": "date",
        "articlesSortByAsc": False,
        "resultType": "articles",
        "articlesArticleBodyLen": -1,
        "apiKey": key,
    }
    try:
        response = session.post(API_URL, json=payload, timeout=timeout)
        response.raise_for_status()
        raw = response.json()
    except Exception as exc:
        raise NewsApiAiError(f"NewsAPI.ai 호출에 실패했습니다: {exc}") from exc

    if not isinstance(raw, dict):
        raise NewsApiAiError("NewsAPI.ai 응답이 JSON 객체가 아닙니다.")
    if raw.get("error"):
        raise NewsApiAiError(_error_message(raw))
    articles = raw.get("articles")
    if not isinstance(articles, dict) or not isinstance(articles.get("results"), list):
        raise NewsApiAiError("NewsAPI.ai 응답에 articles.results가 없습니다.")

    result: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in articles["results"]:
        if not isinstance(item, dict):
            continue
        normalized = _normalize_article(item)
        if normalized is None or normalized["news_id"] in seen:
            continue
        seen.add(normalized["news_id"])
        result.append(normalized)
    total_results = _optional_int(articles.get("totalResults"))
    pages = _optional_int(articles.get("pages"))
    truncated = (pages is not None and pages > 1) or (
        total_results is not None and total_results > len(result)
    )
    return ArticleBatch(
        articles=result,
        total_results=total_results,
        returned_count=len(result),
        pages=pages,
        truncated=truncated,
    )


def fetch_articles(
    keywords: list[str],
    date_start: str,
    date_end: str,
    *,
    page_size: int = 100,
    api_key: str | None = None,
    session: Any = requests,
    timeout: int = 20,
) -> list[dict[str, str]]:
    """기존 수집기 호환용: 기사 목록만 반환한다."""
    return fetch_article_batch(
        keywords,
        date_start,
        date_end,
        page_size=page_size,
        api_key=api_key,
        session=session,
        timeout=timeout,
    ).articles
