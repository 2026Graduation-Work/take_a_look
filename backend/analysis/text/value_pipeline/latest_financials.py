"""가장 최근 사업보고서(연간) 기준 재무 스냅샷을 만들어 적재한다(주 1회, 바뀐 종목만).
분기·반기 누적을 ×4·×2로 연환산하면 일회성 이익이 두 배가 돼 비율이 튄다(#292, SK하이닉스 2026 반기
금융수익 82.9조 → ROE 102%). 그래서 비율은 연간 보고서 하나로만 만든다.
- ROE = 지배주주 순이익 ÷ 평균 지배주주지분((당기말 + 전기말) ÷ 2, 같은 보고서의 당기·전기 값)
- 매출 증가율 = 같은 보고서의 당기 매출 ÷ 전기 매출 − 1
"""
from __future__ import annotations

import datetime as dt
import json
import re
from typing import Any

from . import collectors, financial_tracks, supabase_store
from .config import SETTINGS

ANNUAL_REPORT = "11011"
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
               "ifrs-full_Inventories": "inventories", "ifrs-full_RetainedEarnings": "retained_earnings",
               "ifrs-full_ProfitLossAttributableToOwnersOfParent": "net_income_owners",
               "ifrs-full_EquityAttributableToOwnersOfParent": "equity_owners"}
_NET_INCOME_NAME = re.compile(r"^(당기|반기|분기)(순이익|순손익|손이익)")


def _amount(value: object) -> float | None:
    try:
        return float(str(value).replace(",", ""))
    except (TypeError, ValueError):
        return None


def parse_report(frame: Any) -> dict[str, Any]:
    """DART 사업보고서 fnlttSinglAcntAll 프레임 → 표준 재무 dict(당기·전기 금액, 환산 없음)."""
    out: dict[str, Any] = {}
    for _, row in frame.iterrows():
        name, part = str(row.get("account_nm", "")).strip(), str(row.get("sj_div", ""))
        key = _ACCOUNT_ID.get(str(row.get("account_id", "")))
        if part == "BS" and (key or (key := _BALANCE.get(name))) and key not in out:
            out[key] = _amount(row.get("thstrm_amount"))
            out[f"{key}_prev"] = _amount(row.get("frmtrm_amount"))  # 전기말(평균 자본용)
        elif part in ("IS", "CIS") and (
            key or (key := _INCOME.get(name)) or (key := "net_income" if _NET_INCOME_NAME.match(name) else None)
        ) and key not in out:
            out[key] = _amount(row.get("thstrm_amount"))
            out[f"{key}_prev"] = _amount(row.get("frmtrm_amount"))
    if out.get("revenue") is None:
        raise RuntimeError("DART 매핑 실패(매출)")
    # ROE: 지배주주 순이익 ÷ 평균 지배주주지분. 별도재무제표처럼 지배/비지배 구분이 없으면 전체 값
    owners = out.get("equity_owners") is not None
    income = out.get("net_income_owners", out.get("net_income")) if owners else out.get("net_income")
    end, start = (out.get("equity_owners"), out.get("equity_owners_prev")) if owners \
        else (out.get("total_equity"), out.get("total_equity_prev"))
    if income is not None and end is not None and start is not None:
        out.update(roe_net_income=income, roe_equity_end=end, roe_equity_start=start,
                   roe_equity_avg=(end + start) / 2, roe_owners=owners)
    return out


def latest_report(dart: Any, ticker: str, today: dt.date) -> tuple[int, str, Any]:
    """(사업연도, 연결/별도, 프레임). 작년 → 재작년 순으로 가장 최근 사업보고서(올해 것은 내년 3월에 나온다)."""
    for year in (today.year - 1, today.year - 2):
        for statement in ("CFS", "OFS"):
            frame = dart.finstate_all(ticker, year, reprt_code=ANNUAL_REPORT, fs_div=statement)
            if frame is not None and len(frame):
                return year, statement, frame
    raise RuntimeError(f"{ticker}: 최근 2년 사업보고서가 없습니다")


def sync(client: supabase_store.SupabaseRestClient, targets: dict[str, str], today: dt.date | None = None) -> dict:
    today = today or dt.date.today()
    dart = collectors.OpenDartReader(SETTINGS.dart_api_key)
    stored = {row["stock_code"]: row["receipt_no"] for row in client.select(
        "financial_snapshots", params={"select": "stock_code,receipt_no,as_of", "order": "as_of.asc",
                                       "stock_code": f"in.({','.join(targets)})"})}
    result: dict[str, str] = {}
    for ticker, name in targets.items():
        try:
            year, statement, frame = latest_report(dart, ticker, today)
            receipt_no = str(frame["rcept_no"].iloc[0])
            if stored.get(ticker) == receipt_no:
                result[ticker] = "unchanged"
                continue
            raw = parse_report(frame)
            raw["fiscal_year"] = year
            if (shares := collectors._fetch_latest_shares(ticker)) is not None:
                raw["shares_outstanding"] = shares
            if (price := collectors._fetch_price(ticker, today.isoformat())) is not None:
                raw["price"], raw["_price_source"] = price, "fdr"
            track = financial_tracks.build_financial_track(
                ticker=ticker, company_name=name, as_of=today.isoformat(), raw_financials=raw,
                statement=statement, receipt_no=receipt_no,
                filed_at=f"{receipt_no[:4]}-{receipt_no[4:6]}-{receipt_no[6:8]}", validation_errors=[])
            track["filing"]["report_code"] = ANNUAL_REPORT
            track["filing"]["shares_basis"] = "최근 공시 보통주"  # 발행주식수는 _fetch_latest_shares(최근 공시)
            supabase_store.persist_financial_track(client, track)
            result[ticker] = f"{year} 연간"
        except Exception as exc:  # 한 종목 실패가 나머지를 막지 않게
            result[ticker] = f"failed ({type(exc).__name__})"
    print(json.dumps({"event": "financial_latest", "results": result}, ensure_ascii=False))
    return result
