"""배치 러너·수집 캐시·일별 피처 추출 검증.

- batch.run_batch: LLM 강제 OFF, 하루 실패가 배치를 죽이지 않음, manifest 기록
- collectors 캐시: DART는 (종목, 사업연도)당 1콜, 반환 dict 변형이 캐시를 오염 안 함
- features: 일별(ValueSignal) 행 지원 + 일별/기간 혼입 거부
"""
from __future__ import annotations

import dataclasses
import json
import math
from pathlib import Path

import pandas as pd
import pytest
from analysis.text.value_pipeline import batch as batch_mod
from analysis.text.value_pipeline import collectors as collectors_mod
from analysis.text.value_pipeline import features as features_mod
from analysis.text.value_pipeline import llm as llm_mod


@pytest.fixture(autouse=True)
def _llm_switch_reset():
    yield
    llm_mod.set_llm_enabled(True)


# ── 배치 러너 ──────────────────────────────────────────────────────
def _ok_signal(date: str, ok: bool = True) -> dict:
    return {
        "ticker": "005930", "date": date,
        "validation": {"ok": ok, "errors": [] if ok else ["e"], "warnings": []},
    }


def test_run_batch_forces_llm_off_and_survives_daily_errors(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    seen: dict[str, bool] = {}

    def fake_pipeline(ticker, date, name):
        seen["llm_disabled"] = llm_mod._FORCE_DISABLED
        if date == "2022-06-02":
            raise RuntimeError("그날만 실패")
        return _ok_signal(date, ok=(date != "2022-06-03"))

    monkeypatch.setattr(batch_mod, "run_pipeline", fake_pipeline)
    manifest = batch_mod.run_batch(
        "005930", "삼성전자", "2022-06-01", "2022-06-04", tmp_path
    )

    assert seen["llm_disabled"] is True          # LLM 강제 OFF 상태에서 실행됨
    assert manifest["ok"] == 2                    # 06-01, 06-04
    assert manifest["validation_failed"] == 1     # 06-03
    assert [e["date"] for e in manifest["errors"]] == ["2022-06-02"]  # 계속 진행됨
    # 에러 난 날짜만 파일이 없다 + manifest 파일이 남는다
    assert not (tmp_path / "005930_2022-06-02.json").exists()
    assert (tmp_path / "005930_2022-06-01.json").exists()
    assert (tmp_path / "_manifest_005930_2022-06-01_2022-06-04.json").exists()


def test_run_batch_skip_existing_resumes(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    (tmp_path / "005930_2022-06-01.json").write_text("{}", encoding="utf-8")
    (tmp_path / "_provenance.json").write_text(
        json.dumps(batch_mod.provenance()), encoding="utf-8"
    )
    calls: list[str] = []

    def fake_pipeline(ticker, date, name):
        calls.append(date)
        return _ok_signal(date)

    monkeypatch.setattr(batch_mod, "run_pipeline", fake_pipeline)
    manifest = batch_mod.run_batch(
        "005930", "삼성전자", "2022-06-01", "2022-06-02", tmp_path, skip_existing=True
    )

    assert calls == ["2022-06-02"]  # 이미 있는 날짜는 건너뜀
    assert manifest["skipped_existing"] == 1


def test_run_batch_skip_existing_refuses_mixed_provenance(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """생성 조건이 다르거나 기록이 없는 기존 산출물에 이어 쓰지 않는다 (0Cracker 4)."""
    (tmp_path / "005930_2022-06-01.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(batch_mod, "run_pipeline", lambda t, d, n: _ok_signal(d))

    with pytest.raises(ValueError, match="재개 거부"):  # 기록 없음
        batch_mod.run_batch(
            "005930", "삼성전자", "2022-06-01", "2022-06-02", tmp_path, skip_existing=True
        )

    other = {**batch_mod.provenance(), "finbert_model": "다른/모델"}
    (tmp_path / "_provenance.json").write_text(json.dumps(other), encoding="utf-8")
    with pytest.raises(ValueError, match="재개 거부"):  # 조건 불일치
        batch_mod.run_batch(
            "005930", "삼성전자", "2022-06-01", "2022-06-02", tmp_path, skip_existing=True
        )


def test_run_batch_skip_existing_regenerates_corrupt_json(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """중단으로 깨진 JSON은 스킵하지 않고 다시 만든다."""
    (tmp_path / "005930_2022-06-01.json").write_text('{"ticker": "00', encoding="utf-8")
    (tmp_path / "_provenance.json").write_text(
        json.dumps(batch_mod.provenance()), encoding="utf-8"
    )
    calls: list[str] = []

    def fake_pipeline(ticker, date, name):
        calls.append(date)
        return _ok_signal(date)

    monkeypatch.setattr(batch_mod, "run_pipeline", fake_pipeline)
    batch_mod.run_batch(
        "005930", "삼성전자", "2022-06-01", "2022-06-01", tmp_path, skip_existing=True
    )

    assert calls == ["2022-06-01"]
    json.loads((tmp_path / "005930_2022-06-01.json").read_text(encoding="utf-8"))
    assert not list(tmp_path.glob("*.tmp"))  # 임시 파일이 남지 않는다


def test_run_batch_aborts_on_financials_unavailable(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """재무 확보 실패는 구조적 문제 — 날짜별 skip이 아니라 즉시 중단해야 한다."""

    def fake_pipeline(ticker, date, name):
        raise collectors_mod.FinancialsUnavailableError("키 없음")

    monkeypatch.setattr(batch_mod, "run_pipeline", fake_pipeline)
    with pytest.raises(collectors_mod.FinancialsUnavailableError):
        batch_mod.run_batch("005930", "삼성전자", "2022-06-01", "2022-06-03", tmp_path)


# ── 수집 캐시 ──────────────────────────────────────────────────────
class _CountingDart:
    """OpenDartReader 대역 — API 호출 횟수를 센다."""

    calls = {"finstate": 0, "report": 0}

    def __init__(self, key):
        pass

    def finstate_all(self, corp, bsns_year, **kw):
        _CountingDart.calls["finstate"] += 1
        return pd.DataFrame([
            {"account_nm": "매출액", "thstrm_amount": "300", "frmtrm_amount": "270"},
        ])

    def report(self, corp, kind, year, **kw):
        _CountingDart.calls["report"] += 1
        return pd.DataFrame([{"istc_totqy": "1000"}])


def test_dart_fetch_is_cached_per_fiscal_year(monkeypatch: pytest.MonkeyPatch) -> None:
    """같은 사업연도의 날짜들은 DART를 재호출하지 않아야 한다 (배치 한도 보호)."""
    _CountingDart.calls = {"finstate": 0, "report": 0}
    monkeypatch.setattr(collectors_mod, "OpenDartReader", _CountingDart)
    monkeypatch.setattr(
        collectors_mod, "SETTINGS",
        dataclasses.replace(collectors_mod.SETTINGS, dart_api_key="x"),
    )

    a = collectors_mod._fetch_dart_financials("005930", "2022-06-15")  # FY2021
    b = collectors_mod._fetch_dart_financials("005930", "2022-11-01")  # FY2021 (동일)
    collectors_mod._fetch_dart_financials("005930", "2023-06-15")      # FY2022 (새 연도)

    assert _CountingDart.calls["finstate"] == 2  # FY2021 1회 + FY2022 1회
    # 호출자가 dict를 변형해도(price 주입) 캐시 원본은 오염되지 않는다
    a["price"] = 99999.0
    assert "price" not in b


# ── 일별 피처 추출 ─────────────────────────────────────────────────
def _daily_signal(**over) -> dict:
    base = {
        "ticker": "005930", "date": "2022-06-15", "company_name": "삼성전자",
        "news_sentiment": -0.1, "news_impact_score": 6, "news_sentiment_std": 0.2,
        "news_staleness": 0.15, "key_events": [], "article_count": 12,
        "article_count_raw": 30,
        "financial_health_score": 8.0, "valuation_score": 5.0,
        "financial_metrics": {"per": 10.0, "pbr": 1.2, "roe": 0.13,
                              "revenue_growth": 0.05, "debt_ratio": 0.4,
                              "altman_z": None},
        "financial_fiscal_year": 2021,
        "composite_score": 6.0, "value_investment_signal": "HOLD",
        "confidence": 0.7, "reasoning": "…",
        "news_source": "bigkinds", "financial_source": "dart",
        "validation": {"ok": True, "errors": [], "warnings": []},
    }
    base.update(over)
    return base


def test_daily_feature_extraction_contract() -> None:
    row = features_mod.extract_row(_daily_signal())

    assert row is not None
    assert set(row) == set(
        features_mod.DAILY_KEY_COLUMNS + features_mod.DAILY_FEATURE_COLUMNS
    )
    assert row["date"] == "2022-06-15"
    assert row["article_count"] == 12
    # 파생: 2022-06 기준 FY2021 재무 → 6개월
    assert row["financial_age_months"] == 6
    for banned in ("composite_score", "value_investment_signal", "confidence"):
        assert banned not in row


def test_news_missing_row_survives_with_nan_sentiment() -> None:
    """관련 기사 0건은 '결측'이지 '오염'이 아니다 — 재무 피처는 살리고 감성만 NaN.

    행을 통째로 버리면 조용한 날이 많은 소형주가 데이터셋에서 사실상 사라져
    대형주 편향이 생긴다(실측: 에코프로비엠 2,467일 중 1,888일이 이 사유).
    """
    signal = _daily_signal(
        news_sentiment=0.0, news_impact_score=3, news_sentiment_std=0.0,
        news_staleness=0.0, article_count=0, article_count_raw=2,
        validation={"ok": False, "errors": ["관련 기사 0건(수집 2건) → … '무데이터'."],
                    "warnings": []},
    )
    assert features_mod.row_status(signal) == "news_missing"
    row = features_mod.extract_row(signal)

    assert row is not None
    # 감성 파생 피처는 NaN — 0.0을 '중립'으로 학습하면 안 된다
    for col in ("news_sentiment", "news_impact_score", "news_sentiment_std",
                "news_staleness"):
        assert math.isnan(row[col]), col
    # 기사 수는 0이 사실(결측 지시자), 재무 피처는 그대로 유효
    assert row["article_count"] == 0
    assert row["financial_health_score"] == 8.0
    assert row["per"] == 10.0


def test_corrupt_row_is_still_dropped() -> None:
    """회계 오류 등 '오염' 행은 계속 버린다 — 결측과 구분된다."""
    corrupt = _daily_signal(
        validation={"ok": False,
                    "errors": ["회계 항등식 위배: 자산 != 부채+자본"], "warnings": []},
    )
    assert features_mod.row_status(corrupt) == "invalid"
    assert features_mod.extract_row(corrupt) is None

    # 결측 + 오염이 섞이면 오염으로 본다
    both = _daily_signal(
        validation={"ok": False,
                    "errors": ["관련 기사 0건 → '무데이터'.", "룩어헤드: FY2025 재무"],
                    "warnings": []},
    )
    assert features_mod.row_status(both) == "invalid"


def test_feature_table_rejects_mixed_daily_and_period(tmp_path: Path) -> None:
    """일별과 기간 행은 집계 단위가 달라 한 테이블에 섞이면 안 된다."""
    daily_p = tmp_path / "daily.json"
    daily_p.write_text(json.dumps(_daily_signal()), encoding="utf-8")
    period_p = tmp_path / "period.json"
    period_sig = _daily_signal()
    del period_sig["date"]
    period_sig.update({
        "period": "2022-06", "period_start": "2022-06-01",
        "period_end": "2022-06-30", "period_days": 30, "days_with_articles": 20,
        "avg_daily_articles": 10.0, "financial_age_months": 6,
    })
    period_p.write_text(json.dumps(period_sig), encoding="utf-8")

    rows, skipped, mode = features_mod.build_feature_table([daily_p, period_p])

    assert mode == "daily"          # 첫 파일(정렬순) 기준
    assert len(rows) == 1
    assert any("혼입" in s for s in skipped)
