"""Supabase PostgREST 적재와 분석 트랙→테이블 행 매핑."""
from __future__ import annotations

import os
import time
from collections.abc import Mapping
from datetime import date
from typing import Any

import requests


class SupabaseConfigurationError(RuntimeError):
    """Supabase 연결 설정이 없거나 잘못된 경우."""


class SupabaseWriteError(RuntimeError):
    """Supabase 적재 계약 또는 HTTP 요청이 실패한 경우."""

    def __init__(self, message: str, *, code: str = "supabase_write_error") -> None:
        super().__init__(message)
        self.code = code


class SupabaseNoDataError(SupabaseWriteError):
    """새로 적재할 유효 데이터가 없어 기존 행을 유지하는 경우."""


class SupabaseRestClient:
    def __init__(
        self,
        base_url: str,
        secret_key: str,
        *,
        session: Any = requests,
        timeout: int = 30,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.secret_key = secret_key
        self.session = session
        self.timeout = timeout

    @classmethod
    def from_env(cls, *, session: Any = requests) -> SupabaseRestClient:
        base_url = os.getenv("SUPABASE_URL", "").strip()
        secret_key = (
            os.getenv("SUPABASE_SECRET_KEY", "").strip()
            or os.getenv("SUPABASE_SERVICE_ROLE_KEY", "").strip()
        )
        if not base_url:
            raise SupabaseConfigurationError("SUPABASE_URL이 필요합니다")
        if not secret_key:
            raise SupabaseConfigurationError("SUPABASE_SECRET_KEY가 필요합니다")
        return cls(base_url, secret_key, session=session)

    def upsert(
        self,
        table: str,
        rows: list[dict[str, Any]],
        *,
        on_conflict: str,
        return_rows: bool = False,
    ) -> list[dict[str, Any]]:
        prefer_return = "representation" if return_rows else "minimal"
        headers = {
            "apikey": self.secret_key,
            "Authorization": f"Bearer {self.secret_key}",
            "Content-Type": "application/json",
            "Prefer": f"resolution=merge-duplicates,return={prefer_return}",
        }
        url = f"{self.base_url}/rest/v1/{table}"
        response = None
        for attempt in range(3):
            try:
                response = self.session.post(
                    url,
                    params={"on_conflict": on_conflict},
                    headers=headers,
                    json=rows,
                    timeout=self.timeout,
                )
            except requests.RequestException as exc:
                if attempt == 2:
                    raise SupabaseWriteError(
                        "Supabase 네트워크 요청에 실패했습니다",
                        code="supabase_network_error",
                    ) from exc
                time.sleep(float(2**attempt))
                continue
            if response.status_code < 500 or attempt == 2:
                break
            time.sleep(float(2**attempt))

        if response is None or not 200 <= response.status_code < 300:
            status = getattr(response, "status_code", "unknown")
            raise SupabaseWriteError(
                f"Supabase {table} 쓰기에 실패했습니다 (HTTP {status})",
                code=f"supabase_{table}_http_{status}",
            )
        if not return_rows:
            return []
        try:
            payload = response.json()
        except (TypeError, ValueError) as exc:
            raise SupabaseWriteError(
                "Supabase 응답 JSON이 올바르지 않습니다",
                code="supabase_invalid_json",
            ) from exc
        if not isinstance(payload, list) or not all(isinstance(row, dict) for row in payload):
            raise SupabaseWriteError(
                "Supabase 응답 행 형식이 올바르지 않습니다",
                code="supabase_invalid_rows",
            )
        return payload

    def delete(self, table: str, *, params: Mapping[str, str]) -> None:
        """Delete rows selected by explicit PostgREST filters.

        This is intentionally separate from upsert: the only caller is the
        operator-triggered live-track reset, which removes the dependent rows
        before the parent track row.
        """
        headers = {
            "apikey": self.secret_key,
            "Authorization": f"Bearer {self.secret_key}",
            "Prefer": "return=minimal",
        }
        url = f"{self.base_url}/rest/v1/{table}"
        response = None
        for attempt in range(3):
            try:
                response = self.session.delete(
                    url, params=dict(params), headers=headers, timeout=self.timeout
                )
            except requests.RequestException as exc:
                if attempt == 2:
                    raise SupabaseWriteError(
                        "Supabase 삭제 요청에 실패했습니다",
                        code="supabase_network_error",
                    ) from exc
                time.sleep(float(2**attempt))
                continue
            if response.status_code < 500 or attempt == 2:
                break
            time.sleep(float(2**attempt))

        if response is None or not 200 <= response.status_code < 300:
            status = getattr(response, "status_code", "unknown")
            raise SupabaseWriteError(
                f"Supabase {table} 삭제에 실패했습니다 (HTTP {status})",
                code=f"supabase_{table}_delete_http_{status}",
            )


def _iso_date(value: object, *, field: str) -> str:
    raw = str(value or "").strip()[:10]
    try:
        return date.fromisoformat(raw).isoformat()
    except ValueError as exc:
        raise SupabaseWriteError(f"{field} 날짜가 올바르지 않습니다") from exc


def _require_news_track(track: Mapping[str, Any]) -> None:
    if track.get("track") not in {"historical", "live"}:
        raise SupabaseWriteError("지원하지 않는 뉴스 track입니다")
    if track.get("status") == "error":
        raise SupabaseWriteError("오류 뉴스 track은 적재하지 않습니다")
    coverage = track.get("coverage")
    if not isinstance(coverage, Mapping) or int(coverage.get("relevant_count") or 0) <= 0:
        raise SupabaseNoDataError(
            "관련 기사가 없는 뉴스 track은 적재하지 않습니다",
            code="no_relevant_news",
        )
    if track.get("backend") != "kr-finbert":
        raise SupabaseWriteError("KR-FinBERT 뉴스 track만 적재할 수 있습니다")


def persist_news_track(client: SupabaseRestClient, track: Mapping[str, Any]) -> None:
    _require_news_track(track)
    scope = track.get("scope")
    coverage = track.get("coverage")
    window = track.get("window")
    if not isinstance(scope, Mapping) or not isinstance(coverage, Mapping) or not isinstance(window, Mapping):
        raise SupabaseWriteError("뉴스 track 필수 객체가 없습니다")
    stock_code = str(scope.get("ticker") or "")
    track_name = str(track["track"])
    parent = {
        "stock_code": stock_code,
        "track": track_name,
        "source": track.get("source"),
        "backend": track.get("backend"),
        "status": track.get("status"),
        "as_of": track.get("as_of"),
        "window_start": _iso_date(window.get("start"), field="window.start"),
        "window_end": _iso_date(window.get("end"), field="window.end"),
        "sentiment_mean": window.get("sentiment_mean"),
        "sentiment_std": window.get("sentiment_std"),
        "article_count": int(window.get("article_count") or 0),
        "publisher_count": int(window.get("publisher_count") or 0),
        "fetched_count": int(coverage.get("fetched_count") or 0),
        "relevant_count": int(coverage.get("relevant_count") or 0),
        "newest_published_at": coverage.get("newest_published_at"),
        "lag_minutes": coverage.get("lag_minutes"),
        "provider_total_results": coverage.get("provider_total_results"),
        "provider_returned_count": coverage.get("provider_returned_count"),
        "provider_pages": coverage.get("provider_pages"),
        "provider_truncated": bool(coverage.get("provider_truncated", False)),
    }
    client.upsert(
        "news_sentiment_tracks", [parent], on_conflict="stock_code,track"
    )

    daily_rows = [
        {
            "stock_code": stock_code,
            "track": track_name,
            "sentiment_date": _iso_date(point.get("date"), field="timeline.date"),
            "status": point.get("status"),
            "sentiment_mean": point.get("sentiment_mean"),
            "sentiment_std": point.get("sentiment_std"),
            "article_count": int(point.get("article_count") or 0),
            "publisher_count": int(point.get("publisher_count") or 0),
        }
        for point in track.get("timeline", [])
    ]
    if daily_rows:
        client.upsert(
            "news_sentiment_daily",
            daily_rows,
            on_conflict="stock_code,track,sentiment_date",
        )

    article_rows = [
        {
            "stock_code": stock_code,
            "track": track_name,
            "news_id": str(article.get("news_id") or ""),
            "title": str(article.get("title") or ""),
            "press": str(article.get("press") or ""),
            "url": str(article.get("url") or ""),
            "article_date": _iso_date(article.get("date"), field="article.date"),
            "published_at": article.get("published_at") or None,
            "event_id": str(article.get("event_id") or ""),
            "sentiment_score": float(article["sentiment_score"]),
        }
        for article in track.get("articles", [])
    ]
    if article_rows:
        client.upsert(
            "news_articles",
            article_rows,
            on_conflict="stock_code,track,news_id",
        )


def persist_financial_track(
    client: SupabaseRestClient, track: Mapping[str, Any]
) -> str:
    if track.get("track") != "financial" or track.get("source") != "dart":
        raise SupabaseWriteError("DART financial track만 적재할 수 있습니다")
    scope = track.get("scope")
    filing = track.get("filing")
    price = track.get("price")
    validation = track.get("validation")
    if not all(isinstance(value, Mapping) for value in (scope, filing, price, validation)):
        raise SupabaseWriteError("재무 track 필수 객체가 없습니다")
    snapshot = {
        "stock_code": str(scope.get("ticker") or ""),
        "as_of": _iso_date(track.get("as_of"), field="as_of"),
        "fiscal_year": int(filing["fiscal_year"]),
        "source": "dart",
        "status": track.get("status"),
        "statement": filing.get("statement"),
        "receipt_no": str(filing.get("receipt_no") or ""),
        "filed_at": _iso_date(filing.get("filed_at"), field="filing.filed_at"),
        "shares_basis": str(filing.get("shares_basis") or ""),
        "price": price.get("value"),
        "price_as_of": _iso_date(price.get("as_of"), field="price.as_of")
        if price.get("value") is not None
        else None,
        "price_source": price.get("source") if price.get("value") is not None else None,
        "validation_errors": list(validation.get("errors") or []),
    }
    rows = client.upsert(
        "financial_snapshots",
        [snapshot],
        on_conflict="stock_code,as_of,fiscal_year",
        return_rows=True,
    )
    snapshot_id = str(rows[0].get("id") or "") if rows else ""
    if not snapshot_id:
        raise SupabaseWriteError("재무 스냅샷 UUID를 받지 못했습니다")
    metrics = [
        {
            "snapshot_id": snapshot_id,
            "metric_key": metric.get("metric_key"),
            "value": metric.get("value"),
            "unit": metric.get("unit"),
            "basis": str(metric.get("basis") or ""),
            "note": metric.get("note"),
        }
        for metric in track.get("metrics", [])
    ]
    if metrics:
        client.upsert(
            "financial_metrics",
            metrics,
            on_conflict="snapshot_id,metric_key",
        )
    return snapshot_id
