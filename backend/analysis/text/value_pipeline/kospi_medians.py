"""코스피 재무 지표 중간값(종목 상세 재무 탭의 비교 기준, #372).

DART 다중회사 주요계정(사업보고서) + 코스피 시가총액으로 종목별 6개 지표를 계산하고 중간값만 JSON으로 남긴다.
화면은 이 파일을 읽기만 한다(매번 계산하지 않음). 업종 분류가 DB에 없어 비교 기준은 코스피 전체다.

계산(종목 하나 기준, latest_financials와 같은 정의. ROE만 지배주주 구분이 없어 전체 순이익 ÷ 평균 자본):
- PER = 시가총액 ÷ 당기순이익(흑자만), PBR = 시가총액 ÷ 자본총계(자본 > 0만)
- ROE, 영업이익률, 부채비율, 매출 증가율(전기 매출 > 0만)
실행: python -m value_pipeline.kospi_medians [사업연도]  (backend/analysis/text에서, DART_API_KEY 필요)
"""
from __future__ import annotations

import datetime as dt
import json
import statistics
import sys
from pathlib import Path

from .config import SETTINGS
from .latest_financials import ANNUAL_REPORT, _amount

OUT = Path(__file__).resolve().parents[4] / "frontend" / "lib" / "financial-medians.json"
_ACCOUNTS = {"매출액": "revenue", "영업이익": "operating_profit", "당기순이익(손실)": "net_income",
             "당기순이익": "net_income", "부채총계": "total_liabilities", "자본총계": "total_equity"}
# ponytail: 다중회사 API 한 번에 100개까지. 942종목이면 10번 호출(DART 일 한도 2만 회 안)
_BATCH = 100


def _ratio(a: float | None, b: float | None) -> float | None:
    return None if a is None or b is None or b <= 0 else a / b


def _pct(a: float | None, b: float | None) -> float | None:
    return None if (ratio := _ratio(a, b)) is None else ratio * 100


def company_metrics(accounts: dict[str, float | None], marcap: float | None) -> dict[str, float | None]:
    """계정(당기·전기) + 시가총액 → 지표 6개. 계산할 수 없으면 None(적자 PER 등)."""
    ni, eq, eq_prev = accounts.get("net_income"), accounts.get("total_equity"), accounts.get("total_equity_prev")
    rev, rev_prev = accounts.get("revenue"), accounts.get("revenue_prev")
    avg_eq = (eq + eq_prev) / 2 if eq is not None and eq_prev is not None else None
    growth = _ratio(rev, rev_prev)
    return {
        "per": _ratio(marcap, ni) if ni and ni > 0 else None,
        "pbr": _ratio(marcap, eq),
        "roe": _pct(ni, avg_eq),
        "operating_margin": _pct(accounts.get("operating_profit"), rev),
        "debt_ratio": _pct(accounts.get("total_liabilities"), eq),
        "revenue_growth": (growth - 1) * 100 if growth is not None else None,
    }


def medians(rows: list[dict[str, float | None]]) -> dict[str, dict[str, float | int]]:
    out = {}
    for key in ("per", "pbr", "roe", "operating_margin", "debt_ratio", "revenue_growth"):
        values = [row[key] for row in rows if row.get(key) is not None]
        if values:
            out[key] = {"median": round(statistics.median(values), 2), "count": len(values)}
    return out


def _parse(frame) -> dict[str, dict[str, float | None]]:
    """다중회사 프레임 → {종목코드: 계정}. 연결(CFS)이 있으면 연결, 없으면 별도."""
    by_code: dict[str, dict[str, dict[str, float | None]]] = {}
    for _, row in frame.iterrows():
        key = _ACCOUNTS.get(str(row.get("account_nm", "")).strip())
        if not key:
            continue
        accounts = by_code.setdefault(str(row["stock_code"]), {}).setdefault(str(row["fs_div"]), {})
        if key not in accounts:
            accounts[key] = _amount(row.get("thstrm_amount"))
            accounts[f"{key}_prev"] = _amount(row.get("frmtrm_amount"))
    return {code: parts.get("CFS") or parts.get("OFS") or {} for code, parts in by_code.items()}


def main(year: int) -> None:
    import FinanceDataReader as fdr

    from .collectors import OpenDartReader

    listing = fdr.StockListing("KOSPI")
    # 보통주만(우선주는 같은 회사라 두 번 세지 않는다)
    listing = listing[listing["Code"].str.endswith("0")]
    marcap = dict(zip(listing["Code"], listing["Marcap"].astype(float), strict=True))
    dart = OpenDartReader(SETTINGS.dart_api_key)
    # DART 고유번호(8자리)로 부른다. 영문이 섞인 새 종목코드는 라이브러리가 회사명으로 찾다 실패하고,
    # 고유번호가 없는 종목(리츠 등)이 하나라도 있으면 묶음 전체가 실패한다
    corp = {row.stock_code: row.corp_code for row in dart.corp_codes.itertuples() if row.stock_code in marcap}
    codes = sorted(corp)
    accounts: dict[str, dict[str, float | None]] = {}
    for start in range(0, len(codes), _BATCH):
        batch = ",".join(corp[code] for code in codes[start:start + _BATCH])
        frame = dart.finstate(batch, year, reprt_code=ANNUAL_REPORT)
        if frame is not None and len(frame):
            accounts.update(_parse(frame))
    rows = [company_metrics(accounts[code], marcap[code]) for code in codes if code in accounts]
    result = {
        "basis": "코스피",
        "fiscal_year": year,
        "as_of": dt.date.today().isoformat(),
        "companies": len(rows),
        "metrics": medians(rows),
    }
    OUT.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else dt.date.today().year - 1)
