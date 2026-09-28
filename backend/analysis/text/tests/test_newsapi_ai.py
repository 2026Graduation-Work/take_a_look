from __future__ import annotations

import dataclasses

import pytest
from analysis.text.value_pipeline import collectors, newsapi_ai


class _FakeResponse:
    def __init__(self, payload: dict, status_code: int = 200) -> None:
        self._payload = payload
        self.status_code = status_code

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self) -> dict:
        return self._payload


class _FakeSession:
    def __init__(self, response: dict) -> None:
        self.response = response
        self.calls: list[dict] = []

    def post(self, url: str, *, json: dict, timeout: int) -> _FakeResponse:
        self.calls.append({"url": url, "json": json, "timeout": timeout})
        return _FakeResponse(self.response)


def _api_response() -> dict:
    return {
        "articles": {
            "totalResults": 1,
            "pages": 1,
            "results": [
                {
                    "uri": "kor-article-1",
                    "lang": "kor",
                    "title": "삼성전자 반도체 실적 개선",
                    "body": "삼성전자의 반도체 부문 실적이 개선됐다.",
                    "url": "https://example.com/news/1",
                    "date": "2026-09-18",
                    "dateTimePub": "2026-09-18T01:20:00Z",
                    "source": {"uri": "hankyung.com", "title": "한국경제"},
                    "eventUri": "kor-event-1",
                    "isDuplicate": False,
                }
            ]
        }
    }


def test_fetch_articles_encodes_korean_keyword_request() -> None:
    """공급자 어댑터가 받은 키워드를 한국어 뉴스 검색 조건으로 전달한다."""
    session = _FakeSession(_api_response())

    rows = newsapi_ai.fetch_articles(
        ["삼성전자", "SK하이닉스"],
        "2026-09-18",
        "2026-09-18",
        api_key="test-key",
        session=session,
    )

    assert len(session.calls) == 1
    payload = session.calls[0]["json"]
    assert payload["keyword"] == ["삼성전자", "SK하이닉스"]
    assert payload["keywordOper"] == "or"
    assert payload["keywordLoc"] == "body,title"
    assert payload["lang"] == "kor"
    assert payload["dataType"] == ["news"]
    assert payload["isDuplicateFilter"] == "skipDuplicates"
    assert payload["dateStart"] == "2026-09-18"
    assert payload["dateEnd"] == "2026-09-18"
    assert payload["articlesArticleBodyLen"] == -1
    assert "articleBodyLen" not in payload
    assert payload["apiKey"] == "test-key"

    assert rows == [
        {
            "news_id": "kor-article-1",
            "title": "삼성전자 반도체 실적 개선",
            "summary": "삼성전자의 반도체 부문 실적이 개선됐다.",
            "url": "https://example.com/news/1",
            "press": "한국경제",
            "date": "2026-09-18",
            "published_at": "2026-09-18T01:20:00Z",
            "event_id": "kor-event-1",
        }
    ]


def test_fetch_article_batch_reports_truncated_provider_results() -> None:
    """100건 제한으로 일부만 받은 사실을 완전한 수집처럼 숨기지 않는다."""
    payload = _api_response()
    payload["articles"]["totalResults"] = 137
    payload["articles"]["pages"] = 2
    session = _FakeSession(payload)

    batch = newsapi_ai.fetch_article_batch(
        ["삼성전자", "SK하이닉스"],
        "2026-09-18",
        "2026-09-18",
        api_key="test-key",
        session=session,
    )

    assert batch.articles[0]["news_id"] == "kor-article-1"
    assert batch.total_results == 137
    assert batch.returned_count == 1
    assert batch.pages == 2
    assert batch.truncated is True


def test_article_date_is_normalized_to_kst() -> None:
    """UTC 전날 시각이어도 한국 자정 이후 기사는 한국 날짜로 분류한다."""
    payload = _api_response()
    article = payload["articles"]["results"][0]
    article["date"] = "2026-09-17"
    article["dateTimePub"] = "2026-09-17T15:30:00Z"

    rows = newsapi_ai.fetch_articles(
        ["삼성전자"],
        "2026-09-17",
        "2026-09-18",
        api_key="test-key",
        session=_FakeSession(payload),
    )

    assert rows[0]["date"] == "2026-09-18"


@pytest.mark.parametrize(
    ("source", "url", "expected_press"),
    [
        (
            {
                "uri": "it.donga.com",
                "title": "GS칼텍스, 인도네시아서 바이오원료 생산 개시… 원료 확보부터 판매까지",
            },
            "https://it.donga.com/106000/",
            "it.donga.com",
        ),
        (
            {"uri": "", "title": "������"},
            "https://www.hankyung.com/article/1",
            "hankyung.com",
        ),
        (
            {"uri": "hankyung.com", "title": "한국경제"},
            "https://www.hankyung.com/article/1",
            "한국경제",
        ),
    ],
)
def test_fetch_articles_uses_only_display_safe_publisher_names(
    source: dict[str, str], url: str, expected_press: str
) -> None:
    """본문 조각과 깨진 문자열을 언론사명으로 저장하지 않는다."""
    payload = _api_response()
    article = payload["articles"]["results"][0]
    article["source"] = source
    article["url"] = url

    rows = newsapi_ai.fetch_articles(
        ["삼성전자"],
        "2026-09-18",
        "2026-09-18",
        api_key="test-key",
        session=_FakeSession(payload),
    )

    assert rows[0]["press"] == expected_press


def test_fetch_articles_drops_title_with_broken_replacement_characters() -> None:
    """사용자가 읽을 수 없는 제목은 대표 기사 후보로 유통시키지 않는다."""
    payload = _api_response()
    payload["articles"]["results"][0]["title"] = "��� 삼성전자 기사"

    rows = newsapi_ai.fetch_articles(
        ["삼성전자"],
        "2026-09-18",
        "2026-09-18",
        api_key="test-key",
        session=_FakeSession(payload),
    )

    assert rows == []


def test_fetch_articles_requires_nonempty_api_key() -> None:
    """빈 키로 네트워크를 호출하며 토큰/오류를 혼동하지 않게 즉시 중단한다."""
    with pytest.raises(newsapi_ai.NewsApiAiConfigurationError, match="NEWSAPI_AI_KEY"):
        newsapi_ai.fetch_articles(
            ["삼성전자"],
            "2026-09-18",
            "2026-09-18",
            api_key="",
            session=_FakeSession(_api_response()),
        )


def test_fetch_articles_rejects_error_payload() -> None:
    """HTTP 200 안의 API 오류를 빈 기사 목록으로 오인하지 않는다."""
    session = _FakeSession({"error": {"message": "Invalid API key"}})

    with pytest.raises(newsapi_ai.NewsApiAiError, match="Invalid API key"):
        newsapi_ai.fetch_articles(
            ["삼성전자"],
            "2026-09-18",
            "2026-09-18",
            api_key="bad-key",
            session=session,
        )


def test_collect_news_uses_newsapi_ai_when_bigkinds_is_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """오늘 뉴스 폴백이 기존 네이버 크롤러로 돌아가는 회귀를 막는다."""
    expected = [
        {
            "news_id": "live-1",
            "title": "삼성전자 실적 개선",
            "date": "2026-09-18",
        }
    ]
    calls: list[dict] = []

    monkeypatch.setattr(collectors.preprocess, "find_news_workbook", lambda *args: None)
    monkeypatch.setattr(
        collectors,
        "SETTINGS",
        dataclasses.replace(collectors.SETTINGS, newsapi_ai_key="configured"),
    )

    def fake_fetch(keywords, date_start, date_end, *, page_size):
        calls.append(
            {
                "keywords": keywords,
                "date_start": date_start,
                "date_end": date_end,
                "page_size": page_size,
            }
        )
        return expected

    monkeypatch.setattr(newsapi_ai, "fetch_articles", fake_fetch)

    rows, source = collectors.collect_news("005930", "삼성전자", "2026-09-18")

    assert rows == expected
    assert source == "newsapi_ai"
    assert calls == [
        {
            "keywords": ["삼성전자"],
            "date_start": "2026-09-17",
            "date_end": "2026-09-18",
            "page_size": 100,
        }
    ]
