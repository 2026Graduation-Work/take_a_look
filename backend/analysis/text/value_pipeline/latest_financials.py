"""가장 최신 정기보고서(분기·반기·사업) 기준 재무 스냅샷을 만들어 적재한다(주 1회, 바뀐 종목만).

분기·반기 손익은 누적치를 12개월로 환산한다(1분기 ×4, 반기 ×2, 3분기 ×4/3). 매출 성장률은
같은 기간 누적끼리 비교하므로 환산 배수의 영향을 받지 않는다. 재무상태표 항목은 보고서 기준일 값이다.
"""
from __future__ import annotations

import datetime as dt
import json
import re
from typing import Any

from . import collectors, financial_tracks, supabase_store
from .config import SETTINGS

# (보고서 코드, 누적 개월 수). 최신부터 찾는다.
REPORTS: tuple[tuple[str, int], ...] = (("11014", 9), ("11012", 6), ("11013", 3), ("11011", 12))
REPORT_LABEL = {"11013": "1분기", "11012": "반기", "11014": "3분기", "11011": "사업보고서"}
_BALANCE = {"자산총계": "total_assets", "부채총계": "total_liabilities", "자본총계": "total_equity",
            "유동자산": "current_assets", "유동부채": "current_liabilities", "재고자산": "inventories",
            "이익잉여금": "retained_earnings"}
_INCOME = {"매출액": "revenue", "매출": "revenue", "수익(매출액)": "revenue", "영업수익": "revenue",
           "영업이익": "operating_profit", "영업이익(손실)": "operating_profit",
           "당기순이익": "net_income", "당기순이익(손실)": "net_income", "연결당기순이익": "net_income"}
# 회사마다 계정 이름이 달라(매출/매출액, 반기순이익/반기손이익) 표준 계정 ID를 먼저 본다
_ACCOUNT_ID = {"ifrs-full_Revenue": "revenue", "dart_OperatingIncomeLoss": "operating_profit",
               "ifrs-full_ProfitLoss": "net_income", "ifrs-full_Assets": "total_assets",
               "ifrs-full_Liabilities": "total_liabilities", "ifrs-full_Equity": "total_equity",
               "ifrs-full_CurrentAssets": "current_assets", "ifrs-full_CurrentLiabilities": "current_liabilities",
               "ifrs-full_Inventories": "inventories", "ifrs-full_RetainedEarnings": "retained_earnings"}
_NET_INCOME_NAME = re.compile(r"^(당기|반기|분기)(순이익|순손익|손이익)")


def _amount(value: object) -> float | None:
    try:
        return float(str(value).replace(",", ""))
    except (TypeError, ValueError):
        return None


def parse_report(frame: Any, months: int) -> dict[str, Any]:
    """DART fnlttSinglAcntAll 프레임 → 표준 재무 dict(손익은 12개월 환산)."""
    out: dict[str, Any] = {}
    scale = 12 / months
    for _, row in frame.iterrows():
        name, part = str(row.get("account_nm", "")).strip(), str(row.get("sj_div", ""))
        key = _ACCOUNT_ID.get(str(row.get("account_id", "")))
        if part == "BS" and (key or (key := _BALANCE.get(name))) and key not in out:
            out[key] = _amount(row.get("thstrm_amount"))
        elif part in ("IS", "CIS") and (
            key or (key := _INCOME.get(name)) or (key := "net_income" if _NET_INCOME_NAME.match(name) else None)
        ) and key not in out:
            # 분기·반기는 누적(add_amount), 사업보고서는 당기 금액. 1분기는 누적이 비어 있을 수 있다
            current = _amount(row.get("thstrm_add_amount")) if months < 12 else None
            current = current if current is not None else _amount(row.get("thstrm_amount"))
            previous = _amount(row.get("frmtrm_add_amount")) if months < 12 else None
            previous = previous if previous is not None else _amount(row.get("frmtrm_q_amount" if months < 12 else "frmtrm_amount"))
            out[key] = current * scale if current is not None else None
            out[f"{key}_prev"] = previous * scale if previous is not None else None
    if out.get("revenue") is None:
        raise RuntimeError("DART 매핑 실패(매출)")
    return out


def latest_report(dart: Any, ticker: str, today: dt.date) -> tuple[int, str, int, str, Any]:
    """(사업연도, 보고서 코드, 개월 수, 연결/별도, 프레임). 올해 → 작년 순으로 가장 최신 보고서."""
    for year in (today.year, today.year - 1):
        for code, months in REPORTS:
            for statement in ("CFS", "OFS"):
                frame = dart.finstate_all(ticker, year, reprt_code=code, fs_div=statement)
                if frame is not None and len(frame):
                    return year, code, months, statement, frame
    raise RuntimeError(f"{ticker}: 최근 2년 정기보고서가 없습니다")


def sync(client: supabase_store.SupabaseRestClient, targets: dict[str, str], today: dt.date | None = None) -> dict:
    today = today or dt.date.today()
    dart = collectors.OpenDartReader(SETTINGS.dart_api_key)
    stored = {row["stock_code"]: row["receipt_no"] for row in client.select(
        "financial_snapshots", params={"select": "stock_code,receipt_no,as_of", "order": "as_of.asc",
                                       "stock_code": f"in.({','.join(targets)})"})}
    result: dict[str, str] = {}
    for ticker, name in targets.items():
        try:
            year, code, months, statement, frame = latest_report(dart, ticker, today)
            receipt_no = str(frame["rcept_no"].iloc[0])
            if stored.get(ticker) == receipt_no:
                result[ticker] = "unchanged"
                continue
            raw = parse_report(frame, months)
            raw["fiscal_year"] = year
            if (shares := collectors._fetch_latest_shares(ticker)) is not None:
                raw["shares_outstanding"] = shares
            if (price := collectors._fetch_price(ticker, today.isoformat())) is not None:
                raw["price"], raw["_price_source"] = price, "fdr"
            track = financial_tracks.build_financial_track(
                ticker=ticker, company_name=name, as_of=today.isoformat(), raw_financials=raw,
                statement=statement, receipt_no=receipt_no,
                filed_at=f"{receipt_no[:4]}-{receipt_no[4:6]}-{receipt_no[6:8]}", validation_errors=[])
            track["filing"]["report_code"] = code
            if months < 12:
                for metric in track["metrics"]:
                    metric["basis"] += f" · {year}년 {REPORT_LABEL[code]} 누적을 12개월로 환산"
            supabase_store.persist_financial_track(client, track)
            result[ticker] = f"{year} {REPORT_LABEL[code]}"
        except Exception as exc:  # 한 종목 실패가 나머지를 막지 않게
            result[ticker] = f"failed ({type(exc).__name__})"
    print(json.dumps({"event": "financial_latest", "results": result}, ensure_ascii=False))
    return result
