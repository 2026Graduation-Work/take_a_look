"""Regenerate 005930_2018.csv from KRX and Naver. Needs a KRX login, so CI never runs it.

    python shared/tests/fixtures/fetch_price_events_fixture.py [--env path/to/.env]
"""
import argparse
import sys
from datetime import date
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv

CHART_DIR = Path(__file__).resolve().parents[3]
CODE, START, END = "005930", "20180101", "20181231"
OUTPUT = Path(__file__).with_name(f"{CODE}_2018.csv")
KRX_COLUMNS = {"TRD_DD": "Date", "TDD_OPNPRC": "RawOpen", "TDD_HGPRC": "RawHigh", "TDD_LWPRC": "RawLow",
               "TDD_CLSPRC": "RawClose", "ACC_TRDVOL": "RawVolume", "ACC_TRDVAL": "Amount",
               "LIST_SHRS": "ListedShares"}


def krx_raw(isin):
    from pykrx.website.krx.market.core import 개별종목시세

    rows = pd.DataFrame(개별종목시세().read(isuCd=isin, strtDd=START, endDd=END, adjStkPrc=1)["output"])
    frame = rows[list(KRX_COLUMNS)].rename(columns=KRX_COLUMNS)
    numbers = frame.columns.drop("Date")
    frame[numbers] = frame[numbers].apply(lambda column: pd.to_numeric(column.str.replace(",", ""), errors="raise"))
    frame["Date"] = pd.to_datetime(frame.Date, format="%Y/%m/%d")
    return frame.sort_values("Date").reset_index(drop=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env", type=Path, default=CHART_DIR / ".env")
    args = parser.parse_args()
    load_dotenv(args.env)
    sys.path.insert(0, str(CHART_DIR))
    from shared.data.krx import authenticated_stock

    stock = authenticated_stock()
    from pykrx.website.krx.market.ticker import get_stock_ticker_isin

    raw = krx_raw(get_stock_ticker_isin(CODE))
    naver = stock.get_market_ohlcv_by_date(START, END, CODE, adjusted=True)["종가"]
    naver.index = pd.to_datetime(naver.index).normalize()
    if not naver.index.equals(pd.DatetimeIndex(raw.Date)):
        raise ValueError("KRX and Naver trading dates differ")
    raw["NaverClose"] = naver.to_numpy()
    header = (f"# Raw* and ListedShares: KRX MDCSTAT01701 adjStkPrc=1 via pykrx 1.2.9; "
              f"NaverClose: pykrx get_market_ohlcv_by_date adjusted=True (Naver); fetched {date.today()}\n")
    with OUTPUT.open("w", encoding="utf-8", newline="") as handle:
        handle.write(header)
        raw.to_csv(handle, index=False, date_format="%Y-%m-%d")
    print(f"Wrote {len(raw)} rows to {OUTPUT}")


if __name__ == "__main__":
    main()
