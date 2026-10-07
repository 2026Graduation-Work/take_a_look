"""투자자별 순매수 수집(차트 서빙 뒤 별도 step, python -m supply). KRX 로그인 세션은 서빙과 같다.

영업일 하루치를 pykrx get_market_net_purchases_of_equities_by_ticker(day, day, "ALL", 투자자)로
시장 전체 종목을 한 번에 받는다(개인·외국인·기관합계 3회). 종목 마스터(stocks)에 있는 종목만 저장하고,
비어 있는 최근 영업일을 채운 뒤 KEEP_DAYS영업일보다 오래된 날은 지운다.
"""

import json
from urllib.parse import quote

from serving.internal.krx import authenticated_stock
from serving.internal.storage import SupabaseStore

INVESTORS = {"retail": "개인", "foreign_investor": "외국인", "institution": "기관합계"}
KEEP_DAYS = 60
BACKFILL_DAYS = 20  # 화면이 쓰는 기간(최근 20영업일)


def day_rows(fetch, day, codes):
    """fetch(day, investor) → DataFrame(index 티커, '순매수거래량'). 세 투자자를 종목별 한 행으로 합친다."""
    columns = {key: fetch(day, name)["순매수거래량"] for key, name in INVESTORS.items()}
    tickers = set.intersection(*(set(series.index.astype(str)) for series in columns.values())) & codes
    iso = f"{day[:4]}-{day[4:6]}-{day[6:]}"
    return [{"stock_code": code, "trade_date": iso, **{key: int(series[code]) for key, series in columns.items()}}
            for code in sorted(tickers)]


def main():
    store = SupabaseStore()
    stock = authenticated_stock()
    codes = {row["code"] for row in store._request("GET", "/rest/v1/stocks?select=code&limit=5000")}
    # 최근 영업일 = chart_prices에 있는 거래일(KRX 달력 기준으로 서빙이 이미 채움)
    days = sorted({row["trade_date"] for row in store._request(
        "GET", f"/rest/v1/chart_prices?select=trade_date&stock_code=eq.005930&order=trade_date.desc&limit={KEEP_DAYS}")})
    have = {row["trade_date"] for row in store._request(
        "GET", "/rest/v1/supply_demand?select=trade_date&stock_code=eq.005930&order=trade_date.desc&limit=100")}
    missing = [day for day in days[-BACKFILL_DAYS:] if day not in have]

    def fetch(day, investor):
        return stock.get_market_net_purchases_of_equities_by_ticker(day, day, "ALL", investor)

    saved = 0
    for day in missing:
        rows = day_rows(fetch, day.replace("-", ""), codes)
        for offset in range(0, len(rows), 500):
            store._request("POST", "/rest/v1/supply_demand?on_conflict=stock_code,trade_date", rows[offset:offset + 500],
                           prefer="resolution=merge-duplicates,return=minimal")
        saved += len(rows)
    if days:
        store._request("DELETE", "/rest/v1/supply_demand?trade_date=lt." + quote(days[0]), prefer="return=minimal")
    print(json.dumps({"event": "supply", "days_filled": missing, "rows": saved, "keep_from": days[0] if days else None},
                     ensure_ascii=False))


if __name__ == "__main__":
    main()
