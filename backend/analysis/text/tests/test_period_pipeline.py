"""기간(월/년) 요약 파이프라인 검증.

- 재무는 '기간 종료일' 기준 point-in-time (collect_financials(period_end) 재사용)
- 뉴스는 빅카인즈 엑셀 전용, 관련성 필터(규칙) 후 기사 단위 가중 집계
- LLM은 기간 경로에서 아예 호출되지 않는다 — 점수·이벤트 모두 100% 결정론
"""
from __future__ import annotations

import math

import pytest
from analysis.text.value_pipeline import agents as agents_mod
from analysis.text.value_pipeline import features as features_mod
from analysis.text.value_pipeline import period as period_mod
from analysis.text.value_pipeline import schema as schema_mod


@pytest.fixture(autouse=True)
def _llm_must_not_be_called(monkeypatch: pytest.MonkeyPatch) -> None:
    """기간 경로는 LLM을 아예 부르지 않아야 한다 — 호출되면 즉시 실패."""

    def boom(prompt, schema):
        raise AssertionError("기간 파이프라인 경로에서 LLM이 호출되면 안 된다")

    monkeypatch.setattr(agents_mod, "structured", boom)


@pytest.fixture(autouse=True)
def _deterministic_sentiment(monkeypatch: pytest.MonkeyPatch) -> None:
    """감성 백엔드를 결정론 대역으로 고정 (FinBERT 로드/다운로드 배제, 헤르메틱)."""

    def fake(texts: list[str]) -> tuple[list[float], str]:
        texts = [t for t in texts if t and t.strip()]
        if not texts:
            return [], "none"
        return [
            0.5 if "호재" in t else (-0.5 if "악재" in t else 0.0) for t in texts
        ], "lexicon"

    monkeypatch.setattr(period_mod, "score_texts", fake)


def _fin(**over) -> dict:
    """정합적인 표준 재무 dict (항등식 자산=부채+자본 성립)."""
    base = {
        "revenue": 3.0e14, "revenue_prev": 2.7e14, "net_income": 4.0e13,
        "total_assets": 4.0e14, "total_liabilities": 1.0e14, "total_equity": 3.0e14,
        "current_assets": 2.0e14, "current_liabilities": 5.0e13,
        "shares_outstanding": 5.97e9, "price": 60000.0,
        "sector_per": 15.0, "sector_pbr": 1.5, "company_name": "삼성전자",
        "fiscal_year": 2021,
    }
    base.update(over)
    return base


def _item(title: str, nid: str, date: str) -> dict:
    return {"news_id": nid, "title": title, "summary": "", "url": "",
            "press": "", "date": date}


def _patch_sources(
    monkeypatch: pytest.MonkeyPatch,
    news_by_date: dict[str, list[dict]],
    fin: dict,
    covered: str | set[str] = "all",
) -> dict:
    """수집기를 대역으로 치환. covered: 'all' | 'none' | 커버 날짜 집합 (워크북 존재 여부)."""
    seen: dict[str, str] = {}

    def fake_fin(ticker, date):
        seen["fin_date"] = date
        return dict(fin), "dart"

    def fake_workbook(name, d, data_dir, ticker=""):
        if isinstance(covered, set):
            return object() if d in covered else None
        return object() if covered == "all" else None

    monkeypatch.setattr(period_mod.collectors, "collect_financials", fake_fin)
    monkeypatch.setattr(
        period_mod.collectors, "collect_prior_news", lambda t, n, d, c: []
    )
    monkeypatch.setattr(
        period_mod.collectors.preprocess, "find_news_workbook", fake_workbook
    )
    monkeypatch.setattr(
        period_mod.collectors.preprocess, "load_daily_news",
        lambda name, d, data_dir, limit=None, ticker="": list(news_by_date.get(d, [])),
    )
    return seen


def test_parse_period_month_year_and_leap() -> None:
    assert period_mod.parse_period("2022") == ("2022-01-01", "2022-12-31")
    assert period_mod.parse_period("2022-01") == ("2022-01-01", "2022-01-31")
    assert period_mod.parse_period("2024-02") == ("2024-02-01", "2024-02-29")  # 윤년
    for bad in ("2022-13", "2022-00", "202201", "2022-1", "abcd", ""):
        with pytest.raises(ValueError):
            period_mod.parse_period(bad)


def test_period_financials_use_period_end(monkeypatch: pytest.MonkeyPatch) -> None:
    """재무 수집은 기간 종료일로 호출된다 → look-ahead 방지가 그대로 적용된다."""
    seen = _patch_sources(monkeypatch, {}, _fin())
    out = period_mod.run_period_pipeline("005930", "2022-06", "삼성전자")

    assert seen["fin_date"] == "2022-06-30"
    assert out["period_start"] == "2022-06-01"
    assert out["period_end"] == "2022-06-30"
    assert out["financial_fiscal_year"] == 2021  # 2022-06-30 시점 공시분


def test_period_lookahead_fiscal_year_fails_validation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """기간 종료일(2022-01-31) 시점엔 FY2021이 미공시 → 룩어헤드로 잡혀야 한다."""
    _patch_sources(monkeypatch, {}, _fin(fiscal_year=2021))
    out = period_mod.run_period_pipeline("005930", "2022-01", "삼성전자")

    assert not out["validation"]["ok"]
    assert any("룩어헤드" in e for e in out["validation"]["errors"])


def _june_news() -> dict[str, list[dict]]:
    return {
        "2022-06-01": [
            _item("삼성전자 호재 A", "n1", "2022-06-01"),
            _item("삼성전자 악재 B", "n2", "2022-06-01"),
            _item("두산 호재 무관 기사", "n3", "2022-06-01"),  # 관련성 필터 대상
        ],
        "2022-06-02": [_item("삼성전자 호재 C", "n4", "2022-06-02")],
    }


def test_period_aggregates_are_article_weighted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_sources(monkeypatch, _june_news(), _fin())
    out = period_mod.run_period_pipeline("005930", "2022-06", "삼성전자")

    # 두산 기사는 관련성 필터로 제외 — 집계에 들어가면 안 된다
    assert out["article_count"] == 3
    assert out["article_count_raw"] == 4
    # 기사 단위 평균: (+0.5 - 0.5 + 0.5) / 3
    assert out["news_sentiment"] == pytest.approx(1 / 6, abs=1e-3)
    assert out["period_days"] == 30
    assert out["days_with_articles"] == 2
    assert out["days_covered"] == 30
    assert out["avg_daily_articles"] == pytest.approx(3 / 30, abs=1e-4)
    # 재무 나이: 2022-06 종료월 기준 FY2021(2021-12월 말) 재무 → 6개월
    assert out["financial_age_months"] == 6
    assert out["news_source"] == "bigkinds"
    # 일별 감사 행만으로 기간 평균을 재계산할 수 있어야 한다 (self-auditing)
    total = sum(
        dm["news_sentiment"] * dm["article_count"] for dm in out["daily_metrics"]
    )
    n = sum(dm["article_count"] for dm in out["daily_metrics"])
    assert out["news_sentiment"] == pytest.approx(total / n, abs=1e-3)


def test_period_key_events_are_rule_based_with_sources(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """핵심 이벤트는 감성 절댓값 상위 헤드라인 + 출처 news_id (LLM 미사용)."""
    _patch_sources(monkeypatch, _june_news(), _fin())
    out = period_mod.run_period_pipeline("005930", "2022-06", "삼성전자")

    events = {e["event"]: e["news_ids"] for e in out["key_events"]}
    assert "두산 호재 무관 기사" not in events
    assert events["삼성전자 호재 A"] == ["n1"]
    assert all(ids for ids in events.values())  # 출처 없는 이벤트 없음


def test_period_staleness_rolls_forward_within_period(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """전날과 완전히 같은 기사는 이튿날 staleness=1.0 — 풀이 기간 안에서 굴러간다."""
    news = {
        "2022-06-01": [_item("삼성전자 반도체 실적 개선 전망", "n1", "2022-06-01")],
        "2022-06-02": [_item("삼성전자 반도체 실적 개선 전망", "n2", "2022-06-02")],
    }
    _patch_sources(monkeypatch, news, _fin())
    out = period_mod.run_period_pipeline("005930", "2022-06", "삼성전자")

    by_date = {dm["date"]: dm for dm in out["daily_metrics"]}
    assert by_date["2022-06-01"]["staleness"] == 0.0  # 직전 풀 없음
    assert by_date["2022-06-02"]["staleness"] == 1.0  # 전날 기사와 완전 중복


def test_period_row_is_self_auditing(monkeypatch: pytest.MonkeyPatch) -> None:
    """행 하나만 보고 composite·signal을 재계산할 수 있어야 한다."""
    _patch_sources(monkeypatch, _june_news(), _fin())
    out = period_mod.run_period_pipeline("005930", "2022-06", "삼성전자")

    composite = (
        out["valuation_score"] * 0.6
        + out["financial_health_score"] * 0.4
        + out["news_sentiment"] * (out["news_impact_score"] / 10.0) * 2.0
    )
    composite = max(0.0, min(10.0, composite))
    assert out["composite_score"] == pytest.approx(composite, abs=1e-3)
    assert out["value_investment_signal"] == agents_mod._to_signal(composite)
    assert out["validation"]["ok"], out["validation"]["errors"]


def test_period_without_workbook_fails_validation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """워크북이 기간을 아예 못 덮으면 무데이터 — 정상 행처럼 보이면 안 된다.

    '뉴스가 없었다'(결측, 행 유지)와 달리 '보지 않았다'(수집 실패)이므로
    features.py도 이 행을 오염으로 보고 버린다.
    """
    _patch_sources(monkeypatch, {}, _fin(), covered="none")
    out = period_mod.run_period_pipeline("005930", "2022-06", "삼성전자")

    assert out["days_covered"] == 0
    assert out["news_source"] == "none"
    assert not out["validation"]["ok"]
    assert any("워크북" in e for e in out["validation"]["errors"])


def test_period_partial_coverage_is_excluded_not_zero_filled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """워크북이 일부 날짜만 덮으면 비관측일을 기사 0건으로 채우지 않고 행을 제외한다.

    0으로 채우면 30일 중 10일 관측·5일 기사 → 비율 5/30으로 과소평가되어
    수집 누락이 '조용한 종목'처럼 학습된다.
    """
    covered = {f"2022-06-{d:02d}" for d in range(1, 11)}  # 30일 중 10일만
    _patch_sources(monkeypatch, _june_news(), _fin(), covered=covered)
    out = period_mod.run_period_pipeline("005930", "2022-06", "삼성전자")

    assert out["period_days"] == 30
    assert out["days_covered"] == 10
    assert {dm["date"] for dm in out["daily_metrics"]} == covered  # 비관측일 미기록
    assert not out["validation"]["ok"]
    assert any("부분 커버리지" in e for e in out["validation"]["errors"])
    assert features_mod.row_status(out) == "invalid"  # 결측으로 살리지 않는다


def test_period_pipeline_is_deterministic(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_sources(monkeypatch, _june_news(), _fin())
    a = period_mod.run_period_pipeline("005930", "2022-06", "삼성전자")
    b = period_mod.run_period_pipeline("005930", "2022-06", "삼성전자")
    assert a == b  # 결정론(같은 입력 → 같은 출력)


_EXPECTED_FIELDS = {
    "ticker", "period", "period_start", "period_end", "company_name",
    "news_sentiment", "news_impact_score", "news_sentiment_std", "news_staleness",
    "key_events", "article_count", "article_count_raw", "avg_daily_articles",
    "period_days", "days_with_articles", "days_covered",
    "financial_health_score", "valuation_score", "financial_metrics",
    "financial_fiscal_year", "financial_age_months",
    "composite_score", "value_investment_signal", "confidence", "reasoning",
    "news_source", "financial_source", "validation", "daily_metrics",
}


def test_period_signal_field_contract() -> None:
    assert set(schema_mod.PeriodValueSignal.model_fields) == _EXPECTED_FIELDS


def test_impact_score_shared_rule() -> None:
    """일별·기간이 공유하는 영향력 규칙: 3 + min(4, 기사수//3) + round(|감성|*3)."""
    assert agents_mod.impact_score(0, 0.0) == 3
    assert agents_mod.impact_score(9, 1.0) == 9
    assert agents_mod.impact_score(12, 1.0) == 10  # 상한


def test_feature_extraction_drops_derived_and_text_fields(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """공식 조합(composite 등)·텍스트·감사 메타는 모델 입력에서 빠져야 한다."""
    _patch_sources(monkeypatch, _june_news(), _fin())
    out = period_mod.run_period_pipeline("005930", "2022-06", "삼성전자")
    row = features_mod.extract_row(out)

    assert row is not None
    assert set(row) == set(
        features_mod.PERIOD_KEY_COLUMNS + features_mod.PERIOD_FEATURE_COLUMNS
    )
    for banned in (
        "composite_score", "value_investment_signal", "confidence",
        "reasoning", "key_events", "daily_metrics", "validation",
        "article_count", "article_count_raw",
    ):
        assert banned not in row
    assert row["days_with_articles_ratio"] == pytest.approx(2 / 30)
    assert row["avg_daily_articles"] == pytest.approx(3 / 30, abs=1e-4)
    assert row["financial_age_months"] == 6
    assert row["per"] == pytest.approx(out["financial_metrics"]["per"])


def test_feature_extraction_keeps_missing_as_nan(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """결측은 NaN — 0으로 채우면 '적자'와 '데이터 없음'이 섞인다."""
    fin = _fin()
    del fin["shares_outstanding"]  # → per/pbr/altman_z 결측
    _patch_sources(monkeypatch, _june_news(), fin)
    out = period_mod.run_period_pipeline("005930", "2022-06", "삼성전자")
    row = features_mod.extract_row(out)

    assert row is not None
    assert math.isnan(row["per"])
    assert math.isnan(row["altman_z"])
    assert not math.isnan(row["roe"])  # 있는 값은 그대로


def test_feature_extraction_rejects_invalid_rows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """validation.ok=False 행은 학습 테이블에 들어가면 안 된다."""
    _patch_sources(monkeypatch, {}, _fin(), covered="none")
    out = period_mod.run_period_pipeline("005930", "2022-06", "삼성전자")
    assert not out["validation"]["ok"]
    assert features_mod.extract_row(out) is None
