"""종목 마스터(stocks)를 차트 서빙 universe 기준으로 넣고 고친다. 지우지 않는다.

차트 서빙 워크플로의 마지막 step에서 돈다(python -m stock_master). 위험 표시는 아래 규칙으로
계산하고, 임계값 표는 docs/stock-master-rules.md에 있다. 관리종목 목록(KIND)을 받지 못하면
아무것도 쓰지 않고 실패한다 — 확인 안 된 종목이 관리종목 회피를 통과하지 않게(하드 제약 보수적).
"""

import argparse
import html
import json
import re
from datetime import UTC, date, datetime, timedelta
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import numpy as np
import pandas as pd
from serving.internal.storage import SupabaseStore

PENNY_CLOSE = 1_000  # 종가(원) 미만 → penny_stock
LIQUIDITY_DAYS = 20  # 평균 거래대금 기간(거래일)
LOW_LIQUIDITY_QUANTILE = 0.10  # 20일 평균 거래대금 하위 10% → low_liquidity
VOLATILITY_DAYS = 250  # 1년 변동성 기간(거래일). 데이터가 짧으면 있는 만큼
MIN_VOLATILITY_DAYS = 60  # 이보다 짧으면 변동성 미확인 → risk_grade 1
HIGH_VOLATILITY_QUANTILE = 0.90  # 1년 변동성 상위 10% → high_volatility
# risk_grade(1 매우 위험 ~ 5 매우 안전): 연 변동성 절대 기준. 아래 임계값 미만이면 5·4·3·2, 그 이상은 1.
# 대형주(시가총액 상위 LARGE_CAP_RANK)는 한 단계 완화. 변동성 미확인·spac·managed_stock은 1.
GRADE_VOLATILITY_CUTS = (0.25, 0.40, 0.60, 0.90)  # → 5, 4, 3, 2
LARGE_CAP_RANK = 100  # KRX 대형주 기준(시가총액 상위 100)
# spac·managed_stock은 1로 내린다.
KOSDAQ_CODES = {"247540"}  # serving/internal/pipeline.py EXTRA_CODES (코스피 밖 서비스 종목)
PREFERRED_NAME = re.compile(r"\d?우[B-C]?(\(전환\))?$")
KIND_URL = "https://kind.krx.co.kr/investwarn/adminissue.do"


def is_preferred(code, name):
    return code[-1] != "0" and bool(PREFERRED_NAME.search(name))


def parse_managed_names(page):
    names = re.findall(r'<td class="first">(.*?)</td>', page, re.S)
    return {html.unescape(re.sub(r"<[^>]+>", " ", cell)).strip() for cell in names} - {""}


def fetch_managed_names():
    body = urlencode({"method": "searchAdminIssueSub", "currentPageSize": 3000, "pageIndex": 1,
                      "orderMode": 1, "orderStat": "D", "marketType": "", "forward": "adminissue_sub"})
    request = Request(KIND_URL, data=body.encode(), headers={"User-Agent": "Mozilla/5.0"})
    with urlopen(request, timeout=30) as response:
        names = parse_managed_names(response.read().decode("utf-8"))
    if not names:
        raise RuntimeError("KIND 관리종목 목록이 비어 있습니다")
    return names


def grade_for(volatility, large_cap):
    if pd.isna(volatility):
        return 1
    grade = 1 + sum(bool(volatility < cut) for cut in GRADE_VOLATILITY_CUTS)
    return min(5, grade + 1) if large_cap else grade


def fetch_large_caps():
    """시가총액 상위 LARGE_CAP_RANK 종목 코드(KRX 상장 목록, 로그인 불필요)."""
    import FinanceDataReader as fdr

    listing = fdr.StockListing("KRX")
    if listing.empty or "Marcap" not in listing:
        raise RuntimeError("KRX 상장 목록(시가총액)을 받지 못했습니다")
    return set(listing.nlargest(LARGE_CAP_RANK, "Marcap")["Code"].astype(str))


def classify(universe, prices, managed_names, large_caps=frozenset()):
    """universe: Code·Name, prices: Code·Date·Close·Amount → stocks 행 목록."""
    prices = prices.sort_values(["Code", "Date"])
    by_code = prices.groupby("Code")
    close = by_code["Close"].last()
    liquidity = by_code["Amount"].apply(lambda s: s.tail(LIQUIDITY_DAYS).mean())
    returns = np.log(prices["Close"]).groupby(prices["Code"]).diff()
    tail = returns.groupby(prices["Code"]).tail(VOLATILITY_DAYS).groupby(prices["Code"])
    # 가격이 한 번도 안 움직였으면(거래정지 등) 변동성을 모르는 것으로 본다.
    volatility = (tail.std() * np.sqrt(252)).where((tail.count() >= MIN_VOLATILITY_DAYS) & (tail.std() > 0))

    liquidity_cut = liquidity.quantile(LOW_LIQUIDITY_QUANTILE)
    volatility_cut = volatility.quantile(HIGH_VOLATILITY_QUANTILE)

    rows = []
    for code, name in zip(universe["Code"], universe["Name"], strict=True):
        flags = []
        if "스팩" in name:
            flags.append("spac")
        if name in managed_names:
            flags.append("managed_stock")
        if is_preferred(code, name):
            flags.append("preferred_stock")
        if close.get(code, np.nan) < PENNY_CLOSE:
            flags.append("penny_stock")
        if liquidity.get(code, np.nan) <= liquidity_cut:
            flags.append("low_liquidity")
        if volatility.get(code, np.nan) >= volatility_cut:
            flags.append("high_volatility")
        grade = grade_for(volatility.get(code, np.nan), code in large_caps)
        if {"spac", "managed_stock"} & set(flags):
            grade = 1
        rows.append({"code": code, "name": name, "market": "KOSDAQ" if code in KOSDAQ_CODES else "KOSPI",
                     "risk_grade": grade, "risk_flags": flags, "is_active": True})
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dry-run", action="store_true", help="쓰지 않고 결과만 JSON으로 출력")
    args = parser.parse_args()

    store = SupabaseStore()
    as_of = store._request("GET", "/rest/v1/chart_universe?select=as_of&order=as_of.desc&limit=1")[0]["as_of"]
    universe = store.load_universe(as_of)
    start = (date.fromisoformat(as_of) - timedelta(days=400)).isoformat()
    panel = store.load_price_panel(start, as_of)
    prices = pd.concat([frame.assign(Code=code) for code, frame in panel.items()], ignore_index=True)
    managed = fetch_managed_names()
    rows = classify(universe, prices, managed, fetch_large_caps())
    matched = sum("managed_stock" in row["risk_flags"] for row in rows)
    print(json.dumps({"event": "stock_master", "as_of": as_of, "stocks": len(rows),
                      "managed_listed": len(managed), "managed_matched": matched}, ensure_ascii=False))
    if args.dry_run:
        print(json.dumps(rows, ensure_ascii=False))
        return
    now = datetime.now(UTC).isoformat()
    for offset in range(0, len(rows), 500):
        store._request("POST", "/rest/v1/stocks?on_conflict=code",
                       [dict(row, updated_at=now) for row in rows[offset:offset + 500]],
                       prefer="resolution=merge-duplicates,return=minimal")


if __name__ == "__main__":
    main()
