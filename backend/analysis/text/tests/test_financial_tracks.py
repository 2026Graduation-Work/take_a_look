from __future__ import annotations

import json
from pathlib import Path

import pytest
from analysis.text.value_pipeline import financial_run, financial_tracks


def _raw_financials(*, net_income: float = 20.0) -> dict[str, float | int]:
    return {
        "fiscal_year": 2024,
        "price": 100.0,
        "shares_outstanding": 10.0,
        "revenue": 1000.0,
        "revenue_prev": 800.0,
        "operating_profit": 100.0,
        "net_income": net_income,
        "total_assets": 750.0,
        "total_liabilities": 250.0,
        "total_equity": 500.0,
    }


def test_financial_track_exposes_supabase_upsert_keys_and_six_explainable_metrics() -> None:
    """필드가 프론트 전용 camelCase로 돌아가거나 계산 근거가 빠지는 회귀를 막는다."""
    output = financial_tracks.build_financial_track(
        ticker="035720",
        company_name="카카오",
        as_of="2025-12-30",
        raw_financials=_raw_financials(),
        statement="CFS",
        receipt_no="20250324000901",
        filed_at="2025-03-24",
        validation_errors=[],
    )

    assert output["schema_version"] == "1.0"
    assert output["track"] == "financial"
    assert output["scope"] == {"ticker": "035720", "company_name": "카카오"}
    assert output["source"] == "dart"
    assert output["as_of"] == "2025-12-30"
    assert output["status"] == "ok"
    assert output["filing"] == {
        "fiscal_year": 2024,
        "statement": "CFS",
        "receipt_no": "20250324000901",
        "filed_at": "2025-03-24",
        "shares_basis": "2024-12-31 common_shares",
    }
    assert output["price"] == {"value": 100.0, "as_of": "2025-12-30", "source": "fdr"}

    rows = {row["metric_key"]: row for row in output["metrics"]}
    assert list(rows) == [
        "per",
        "pbr",
        "roe",
        "operating_margin",
        "debt_ratio",
        "revenue_growth",
    ]
    assert {key: row["value"] for key, row in rows.items()} == {
        "per": 50.0,
        "pbr": 2.0,
        "roe": 4.0,
        "operating_margin": 10.0,
        "debt_ratio": 50.0,
        "revenue_growth": 25.0,
    }
    assert all(
        row["ticker"] == "035720"
        and row["as_of"] == "2025-12-30"
        and row["fiscal_year"] == 2024
        and row["basis"]
        for row in rows.values()
    )
    assert "revenue" not in output
    assert output["validation"] == {"errors": []}


def test_financial_track_keeps_negative_earnings_per_null_without_marking_failure() -> None:
    """적자 기업의 PER 결측을 0이나 오류 상태로 바꾸는 회귀를 막는다."""
    output = financial_tracks.build_financial_track(
        ticker="035720",
        company_name="카카오",
        as_of="2025-12-30",
        raw_financials=_raw_financials(net_income=-10.0),
        statement="CFS",
        receipt_no="20250324000901",
        filed_at="2025-03-24",
        validation_errors=[],
    )

    per = next(row for row in output["metrics"] if row["metric_key"] == "per")
    assert per["value"] is None
    assert per["note"] == "negative_earnings"
    assert output["status"] == "ok"


def test_financial_track_rejects_a_filing_published_after_as_of() -> None:
    """기준일 이후 공시가 Supabase 적재 파일에 섞이는 룩어헤드를 막는다."""
    with pytest.raises(ValueError, match="기준일 이후"):
        financial_tracks.build_financial_track(
            ticker="005930",
            company_name="삼성전자",
            as_of="2025-03-01",
            raw_financials=_raw_financials(),
            statement="CFS",
            receipt_no="20250311000600",
            filed_at="2025-03-11",
            validation_errors=[],
        )


def test_write_financial_track_persists_json_without_raw_financials(
    tmp_path: Path,
) -> None:
    """DB 적재 파일에 DART 원시 계정 전체가 우발적으로 저장되는 회귀를 막는다."""
    output = financial_tracks.build_financial_track(
        ticker="005930",
        company_name="삼성전자",
        as_of="2025-12-30",
        raw_financials=_raw_financials(),
        statement="CFS",
        receipt_no="20250311000600",
        filed_at="2025-03-11",
        validation_errors=[],
    )
    path = tmp_path / "005930_financial.json"

    financial_tracks.write_financial_track(output, path)

    persisted = json.loads(path.read_text(encoding="utf-8"))
    assert persisted == output
    assert "raw_financials" not in persisted
    assert not path.with_suffix(".json.tmp").exists()


def test_financial_cycle_builds_one_supabase_ready_track_per_target() -> None:
    """다종목 실행기가 한 종목을 누락하거나 sample 재무를 실데이터로 쓰는 회귀를 막는다."""

    def collect(ticker: str, as_of: str) -> tuple[dict, str]:
        assert as_of == "2025-12-30"
        return {**_raw_financials(), "_price_source": "fdr"}, "dart"

    def filing(ticker: str, fiscal_year: int, as_of: str) -> dict:
        return {
            "statement": "CFS",
            "receipt_no": "20250324000901",
            "filed_at": "2025-03-24",
            "validation_errors": [],
        }

    outputs = financial_run.run_financial_cycle(
        {"035720": "카카오", "068270": "셀트리온"},
        as_of="2025-12-30",
        collector=collect,
        filing_loader=filing,
    )

    assert list(outputs) == ["035720", "068270"]
    assert outputs["035720"]["scope"]["company_name"] == "카카오"
    assert outputs["068270"]["scope"]["company_name"] == "셀트리온"
    assert outputs["035720"]["metrics"][0]["ticker"] == "035720"


def test_financial_cycle_rejects_sample_financials() -> None:
    """DART 실패 시 sample 값이 Supabase 적재용 파일로 위장하는 회귀를 막는다."""

    def collect(ticker: str, as_of: str) -> tuple[dict, str]:
        return _raw_financials(), "sample"

    with pytest.raises(RuntimeError, match="DART 실데이터"):
        financial_run.run_financial_cycle(
            {"005930": "삼성전자"},
            as_of="2025-12-30",
            collector=collect,
            filing_loader=lambda *_: {},
        )
