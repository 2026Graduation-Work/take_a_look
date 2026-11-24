"""Regenerate the KRX raw-bar fixtures. Needs a KRX login, so CI never runs it.

    python shared/tests/fixtures/fetch_price_events_fixture.py [--env path/to/.env]
"""
import argparse
import sys
from datetime import date
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv

CHART_DIR = Path(__file__).resolve().parents[3]
FIXTURES = [("005930", "20180101", "20181231", True),
            ("004920", "20260102", "20261120", False),
            ("031820", "20260102", "20261120", False)]
KRX_COLUMNS = {"TRD_DD": "Date", "TDD_OPNPRC": "RawOpen", "TDD_HGPRC": "RawHigh", "TDD_LWPRC": "RawLow",
               "TDD_CLSPRC": "RawClose", "CMPPREVDD_PRC": "RawChange", "ACC_TRDVOL": "RawVolume",
               "ACC_TRDVAL": "Amount", "LIST_SHRS": "ListedShares"}


def krx_raw(isin, start, end):
    from pykrx.website.krx.market.core import 개별종목시세

    rows = pd.DataFrame(개별종목시세().read(isuCd=isin, strtDd=start, endDd=end, adjStkPrc=1)["output"])
    frame = rows[list(KRX_COLUMNS)].rename(columns=KRX_COLUMNS)
    numbers = frame.columns.drop("Date")
    frame[numbers] = frame[numbers].apply(lambda column: pd.to_numeric(column.str.replace(",", ""), errors="raise"))
    frame["Date"] = pd.to_datetime(frame.Date, format="%Y/%m/%d")
    return frame.sort_values("Date").reset_index(drop=True)


def write_fixture(stock, code, start, end, with_naver):
    from pykrx.website.krx.market.ticker import get_stock_ticker_isin

    raw = krx_raw(get_stock_ticker_isin(code), start, end)
    header = "# Raw*, ListedShares: KRX MDCSTAT01701 adjStkPrc=1 via pykrx 1.2.9"
    if with_naver:
        naver = stock.get_market_ohlcv_by_date(start, end, code, adjusted=True)["종가"]
        naver.index = pd.to_datetime(naver.index).normalize()
        if not naver.index.equals(pd.DatetimeIndex(raw.Date)):
            raise ValueError(f"{code}: KRX and Naver trading dates differ")
        raw["NaverClose"] = naver.to_numpy()
        header += "; NaverClose: pykrx get_market_ohlcv_by_date adjusted=True (Naver)"
    output = Path(__file__).with_name(f"{code}_{start[:4]}.csv")
    with output.open("w", encoding="utf-8", newline="") as handle:
        handle.write(f"{header}; fetched {date.today()}\n")
        raw.to_csv(handle, index=False, date_format="%Y-%m-%d")
    print(f"Wrote {len(raw)} rows to {output}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env", type=Path, default=CHART_DIR / ".env")
    args = parser.parse_args()
    load_dotenv(args.env)
    sys.path.insert(0, str(CHART_DIR))
    from shared.data.krx import authenticated_stock

    stock = authenticated_stock()
    for fixture in FIXTURES:
        write_fixture(stock, *fixture)


if __name__ == "__main__":
    main()
