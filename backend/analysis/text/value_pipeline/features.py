"""학습용 피처 추출 — 파이프라인 JSON들 → 모델 입력 테이블(CSV).

⚠️ 아직 차트 블록 외부 피처 계약(Date, Code, AvailableDate)과 호환되지 않는다.
`(ticker, date)`로 가격 행에 직접 조인하면 당일 뉴스가 같은 날 학습 행에 들어가는
룩어헤드가 생긴다. 가용 시점 분리(뉴스 다음 개장일·재무 공시일) 전까지 이 CSV를
차트 학습에 쓰지 말 것.

일별과 기간 행은 집계 단위가 달라 한 테이블에 섞지 않는다.

빼는 것과 이유:
- composite_score / value_investment_signal / confidence — 다른 피처들의 고정 공식
  조합이라 정보량이 0이다. 넣으면 모델이 수작업 공식을 복제하는 쪽으로 쏠린다.
- 기간 행의 기사 절대량(article_count 등) — 월 길이·종목별 언론 노출량에 오염되므로
  일평균·비율로 대체한다. 일별 행의 article_count는 이미 '하루' 단위라 그대로 쓴다.

오염 행(회계 항등식 위배·룩어헤드·단위 오류)은 버린다 — 모델이 학습해버리기 때문이다.
결측 행(관련 기사 0건)은 살리고 감성 파생 피처만 NaN으로 둔다 — 소형주는 조용한 날이
많아(실측: 에코프로비엠 2,467일 중 1,888일) 행을 통째로 버리면 대형주 편향이 생긴다.
결측은 0으로 채우지 않는다 — LightGBM은 NaN을 네이티브로 처리하며, 0 대치는 '적자'와
'데이터 없음'을, 감성에서는 '무데이터'와 '중립'을 섞는다.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import math
import sys
from collections.abc import Sequence
from pathlib import Path

_METRIC_COLUMNS = ["per", "pbr", "roe", "revenue_growth", "debt_ratio", "altman_z"]

PERIOD_KEY_COLUMNS = ["ticker", "period", "period_start", "period_end"]
PERIOD_FEATURE_COLUMNS = [
    "news_sentiment",
    "news_impact_score",
    "news_sentiment_std",
    "news_staleness",
    "avg_daily_articles",
    "days_with_articles_ratio",
    "financial_health_score",
    "valuation_score",
    "financial_age_months",
    *_METRIC_COLUMNS,
]

DAILY_KEY_COLUMNS = ["ticker", "date"]
DAILY_FEATURE_COLUMNS = [
    "news_sentiment",
    "news_impact_score",
    "news_sentiment_std",
    "news_staleness",
    "article_count",
    "financial_health_score",
    "valuation_score",
    "financial_age_months",
    *_METRIC_COLUMNS,
]


# 관련 기사 0건 에러의 표식 (agents.validation_agent가 쓰는 문구).
# '무데이터'가 아니라 이 문구로 매칭하는 이유: 워크북 자체가 없는 경우
# (period.py의 커버리지 에러)도 '무데이터'라고 쓰는데, 그건 '뉴스가 없었다'가
# 아니라 '보지 않았다'라서 결측으로 살리면 안 된다 — 오염으로 버려야 한다.
_MISSING_NEWS_MARKER = "관련 기사 0건"
# 기사가 0건이면 값이 없는 것이라 NaN으로 두는 감성 파생 피처.
# 기사 수 계열은 0이 사실이므로 여기 넣지 않는다(결측 지시자 역할).
_SENTIMENT_FEATURES = frozenset(
    {"news_sentiment", "news_impact_score", "news_sentiment_std", "news_staleness"}
)


def _nan_if_none(v: float | int | None) -> float:
    return float(v) if v is not None else math.nan


def row_status(signal: dict) -> str:
    """'ok' | 'news_missing' | 'invalid' — 행을 어떻게 다뤄야 하는지."""
    validation = signal.get("validation") or {}
    if validation.get("ok", False):
        return "ok"
    errors = validation.get("errors") or []
    if errors and all(_MISSING_NEWS_MARKER in e for e in errors):
        return "news_missing"
    return "invalid"


def _financial_age_months(asof_date: str, fiscal_year: int | None) -> float:
    """기준일과 사업연도(12월 결산) 종료월의 간격(개월). 결측이면 NaN."""
    if fiscal_year is None:
        return math.nan
    d = dt.date.fromisoformat(asof_date)
    return (d.year - int(fiscal_year)) * 12 + d.month - 12


def signal_kind(signal: dict) -> str:
    """'period' | 'daily' — 출력 JSON의 종류 판별."""
    return "period" if "period" in signal else "daily"


def columns_for(kind: str) -> tuple[list[str], list[str]]:
    if kind == "period":
        return PERIOD_KEY_COLUMNS, PERIOD_FEATURE_COLUMNS
    return DAILY_KEY_COLUMNS, DAILY_FEATURE_COLUMNS


def extract_row(signal: dict) -> dict | None:
    """ValueSignal/PeriodValueSignal dict → 조인 키 + 피처의 평탄 dict.

    오염 행(invalid)이면 None을 반환한다 — 호출자가 그 행을 버리게 한다.
    결측 행(news_missing)은 감성 파생 피처를 NaN으로 두고 행을 살린다.
    """
    status = row_status(signal)
    if status == "invalid":
        return None
    news_missing = status == "news_missing"

    kind = signal_kind(signal)
    key_columns, feature_columns = columns_for(kind)
    row: dict = {k: signal[k] for k in key_columns}

    period_days = signal.get("period_days") or 0
    metrics = signal.get("financial_metrics") or {}
    asof = signal["period_end"] if kind == "period" else signal["date"]
    for col in feature_columns:
        if news_missing and col in _SENTIMENT_FEATURES:
            row[col] = math.nan
            continue
        if col == "days_with_articles_ratio":
            value = (
                signal.get("days_with_articles", 0) / period_days if period_days else None
            )
        elif col == "financial_age_months" and col not in signal:
            value = _financial_age_months(asof, signal.get("financial_fiscal_year"))
        elif col in metrics:
            value = metrics.get(col)
        else:
            value = signal.get(col)
        row[col] = _nan_if_none(value)
    return row


def build_feature_table(paths: Sequence[Path]) -> tuple[list[dict], list[str], str]:
    """JSON 파일들 → (피처 행 리스트, 제외 사유 리스트, 테이블 종류).

    테이블 종류는 첫 파일로 정해지며, 다른 종류의 행은 제외된다.
    """
    rows: list[dict] = []
    skipped: list[str] = []
    mode = ""
    news_missing = 0
    for p in sorted(paths):
        path = Path(p)
        signal = json.loads(path.read_text(encoding="utf-8"))
        kind = signal_kind(signal)
        if not mode:
            mode = kind
        elif kind != mode:
            skipped.append(f"{path.name}: {mode} 테이블에 {kind} 행 혼입 — 제외")
            continue
        status = row_status(signal)
        row = extract_row(signal)
        if row is None:
            errors = (signal.get("validation") or {}).get("errors", [])
            skipped.append(f"{path.name}: 오염 행 제외 — {errors[:1]}")
            continue
        if status == "news_missing":
            news_missing += 1
        rows.append(row)
    if news_missing:
        skipped.append(
            f"(참고) 뉴스 결측 행 {news_missing}건은 감성 피처만 NaN으로 두고 유지"
        )
    return rows, skipped, mode


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="파이프라인 JSON(일별/기간) → 학습용 피처 테이블(CSV)"
    )
    ap.add_argument("inputs", nargs="+", help="ValueSignal/PeriodValueSignal JSON 파일들")
    ap.add_argument("--out", default="features.csv", help="출력 CSV 경로")
    args = ap.parse_args(argv)

    # 배치 메타(_manifest_*.json, _provenance.json)는 피처가 아니므로 자동 제외
    inputs = [Path(p) for p in args.inputs if not Path(p).name.startswith("_")]
    rows, skipped, mode = build_feature_table(inputs)
    for msg in skipped:
        print(f"[제외] {msg}" if not msg.startswith("(참고)") else f"[정보] {msg}",
              file=sys.stderr)
    if not rows:
        print("[오류] 사용할 수 있는 행이 없습니다.", file=sys.stderr)
        return 1

    import pandas as pd

    key_columns, feature_columns = columns_for(mode)
    frame = pd.DataFrame(rows, columns=key_columns + feature_columns)
    frame.to_csv(args.out, index=False, encoding="utf-8")
    print(
        f"[저장] {Path(args.out).resolve()} — {mode} {len(rows)}행 × "
        f"피처 {len(feature_columns)}개 (제외 {len(skipped)}행)",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
