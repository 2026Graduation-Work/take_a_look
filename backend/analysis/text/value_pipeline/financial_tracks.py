"""DART 재무 결과를 Supabase 적재에 가까운 행 중심 JSON으로 정규화한다.

테이블명이나 SQL 타입은 팀 합의 전까지 고정하지 않는다. 대신 스냅샷 식별자와
metric upsert 키(ticker, as_of, fiscal_year, metric_key)를 JSON에 명시해 둔다.
원시 DART 계정은 출력하지 않고 화면에서 사용하는 6개 지표와 계산 근거만 남긴다.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from . import metrics

_METRICS: tuple[tuple[str, str, float], ...] = (
    ("per", "multiple", 1.0),
    ("pbr", "multiple", 1.0),
    ("roe", "percent", 100.0),
    ("operating_margin", "percent", 100.0),
    ("debt_ratio", "percent", 100.0),
    ("revenue_growth", "percent", 100.0),
)


def _number(value: object) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _won(value: object) -> str:
    number = _number(value)
    if number is None:
        return "확인 불가"
    if abs(number) >= 1e12:
        return f"{number / 1e12:,.1f}조원"
    return f"{number / 1e8:,.0f}억원"


def _basis(metric_key: str, raw: dict[str, Any]) -> str:
    price = _number(raw.get("price"))
    shares = _number(raw.get("shares_outstanding"))
    net_income = raw.get("net_income")
    equity = raw.get("total_equity")
    revenue = raw.get("revenue")
    operating_profit = raw.get("operating_profit")
    fiscal_year = int(raw["fiscal_year"])
    if metric_key == "per":
        return (
            f"주가 {price:,.0f}원 ÷ 주당순이익"
            f"(당기순이익 {_won(net_income)} ÷ 발행주식수 {shares:,.0f}주)"
            if price is not None and shares is not None
            else "주가 ÷ 주당순이익(당기순이익 ÷ 발행주식수)"
        )
    if metric_key == "pbr":
        return (
            f"주가 {price:,.0f}원 ÷ 주당순자산"
            f"(자본총계 {_won(equity)} ÷ 발행주식수 {shares:,.0f}주)"
            if price is not None and shares is not None
            else "주가 ÷ 주당순자산(자본총계 ÷ 발행주식수)"
        )
    if metric_key == "roe":
        return f"당기순이익 {_won(net_income)} ÷ 자본총계 {_won(equity)}"
    if metric_key == "operating_margin":
        return f"영업이익 {_won(operating_profit)} ÷ 매출 {_won(revenue)}"
    if metric_key == "debt_ratio":
        return f"부채총계 {_won(raw.get('total_liabilities'))} ÷ 자본총계 {_won(equity)}"
    return (
        f"{fiscal_year}년 매출 {_won(revenue)} ÷ "
        f"{fiscal_year - 1}년 매출 {_won(raw.get('revenue_prev'))} − 1"
    )


def build_financial_track(
    *,
    ticker: str,
    company_name: str,
    as_of: str,
    raw_financials: dict[str, Any],
    statement: str,
    receipt_no: str,
    filed_at: str,
    validation_errors: list[str],
) -> dict[str, Any]:
    """표준화 재무 dict를 DB upsert 가능한 재무 스냅샷으로 변환한다."""
    if filed_at > as_of:
        raise ValueError(f"기준일 이후 공시는 사용할 수 없습니다: {filed_at} > {as_of}")
    fiscal_year = int(raw_financials["fiscal_year"])
    calculated = metrics.compute_metrics(raw_financials)
    metric_rows = []
    incomplete = False
    for metric_key, unit, scale in _METRICS:
        raw_value = calculated.get(metric_key)
        value = round(float(raw_value) * scale, 4) if raw_value is not None else None
        negative_earnings = (
            metric_key == "per"
            and value is None
            and (_number(raw_financials.get("net_income")) or 0) < 0
        )
        note = "negative_earnings" if negative_earnings else ("missing_inputs" if value is None else None)
        incomplete = incomplete or (value is None and not negative_earnings)
        metric_rows.append(
            {
                "ticker": ticker,
                "as_of": as_of,
                "fiscal_year": fiscal_year,
                "metric_key": metric_key,
                "value": value,
                "unit": unit,
                "basis": _basis(metric_key, raw_financials),
                "note": note,
            }
        )

    status = "invalid" if validation_errors else ("partial" if incomplete else "ok")
    return {
        "schema_version": "1.0",
        "track": "financial",
        "scope": {"ticker": ticker, "company_name": company_name},
        "source": "dart",
        "as_of": as_of,
        "status": status,
        "filing": {
            "fiscal_year": fiscal_year,
            "statement": statement,
            "receipt_no": receipt_no,
            "filed_at": filed_at,
            "shares_basis": f"{fiscal_year}-12-31 common_shares",
        },
        "price": {
            "value": _number(raw_financials.get("price")),
            "as_of": as_of,
            "source": str(raw_financials.get("_price_source") or "fdr"),
        },
        "metrics": metric_rows,
        "validation": {"errors": list(validation_errors)},
    }


def write_financial_track(output: dict[str, Any], path: Path) -> None:
    """재무 스냅샷을 임시 파일 후 교체 방식으로 저장한다."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(f"{path.suffix}.tmp")
    temporary.write_text(
        json.dumps(output, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)
