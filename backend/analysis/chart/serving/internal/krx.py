"""Check KRX access without printing credentials or writing to the database."""

import contextlib
import io
import json
import os
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo


def authenticated_stock():
    if not os.environ.get("KRX_ID") or not os.environ.get("KRX_PW"):
        raise ValueError("KRX_ID and KRX_PW are required")
    # pykrx prints the login ID at import time. Keep credentials out of logs.
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        from pykrx import stock
        from pykrx.website.comm.auth import get_auth_session

        session = get_auth_session()
    if session is None or not session.is_valid():
        raise RuntimeError("KRX authentication failed; verify the data.krx.co.kr account and KRX_ID/KRX_PW secrets")
    return stock


def diagnose():
    stock = authenticated_stock()
    print(json.dumps({"event": "krx_check", "stage": "authentication", "status": "ok"}))
    now = datetime.now(ZoneInfo("Asia/Seoul"))
    end = now.date() if now.hour >= 18 else now.date() - timedelta(days=1)
    start = end - timedelta(days=30)
    index = stock.get_index_ohlcv_by_date(start.strftime("%Y%m%d"), end.strftime("%Y%m%d"), "1001", name_display=False)
    if index.empty:
        raise ValueError("KRX calendar returned no sessions")
    day = index.index.max().strftime("%Y%m%d")
    print(json.dumps({"event": "krx_check", "stage": "calendar", "rows": len(index), "as_of": day}))
    codes = stock.get_market_ticker_list(day, market="KOSPI")
    if not 500 <= len(codes) <= 1200:
        raise ValueError("Invalid KOSPI universe size")
    print(json.dumps({"event": "krx_check", "stage": "universe", "rows": len(codes)}))
    from .prices import fetch_prices

    prices = fetch_prices("005930", start.isoformat(), day)
    if prices.empty or prices.Date.max().strftime("%Y%m%d") != day:
        raise ValueError("KRX prices do not include the confirmed session")
    print(json.dumps({"event": "krx_check", "stage": "prices_and_turnover", "rows": len(prices), "status": "ok"}))
