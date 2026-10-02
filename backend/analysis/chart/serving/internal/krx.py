"""Check KRX access without printing credentials or writing to the database."""

import contextlib
import io
import json
import os
import time
from datetime import datetime, timedelta
from functools import wraps
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

import requests


def install_request_timeout():
    """pykrx omits data-request timeouts; cover refreshed sessions as well."""
    original = requests.Session.request
    if getattr(original, "_chart_serving_timeout", False):
        return

    @wraps(original)
    def bounded(self, method, url, **kwargs):
        if kwargs.get("timeout") is None:
            kwargs["timeout"] = (10, 30)
        is_krx = urlparse(url).hostname == "data.krx.co.kr"
        for attempt in range(3):
            response = original(self, method, url, **kwargs)
            if not is_krx:
                return response
            transient = response.status_code in {408, 429, 500, 502, 503, 504, 520, 521, 522, 523, 524}
            # KRX sometimes returns HTML/empty maintenance responses to login.
            if urlparse(url).path.endswith("MDCCOMS001D1.cmd") and response.status_code == 200:
                try:
                    response.json()
                except requests.exceptions.JSONDecodeError:
                    transient = True
            if not transient:
                response.raise_for_status()
                return response
            status = response.status_code
            response.close()
            if attempt == 2:
                raise RuntimeError(f"KRX returned an unavailable response (HTTP {status}); retry later")
            time.sleep(2 * (attempt + 1))

    bounded._chart_serving_timeout = True
    requests.Session.request = bounded


def authenticated_stock():
    if not os.environ.get("KRX_ID") or not os.environ.get("KRX_PW"):
        raise ValueError("KRX_ID and KRX_PW are required")
    install_request_timeout()
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

    if os.environ.get("SUPABASE_URL") and os.environ.get("SUPABASE_SECRET_KEY"):
        import numpy as np

        from .prices import changed_price_rows, fetch_daily_prices, fetch_incremental_prices
        from .storage import SupabaseStore

        as_of = index.index.max().date().isoformat()
        history_start = (index.index.max() - timedelta(days=240)).date().isoformat()
        stored = SupabaseStore().load_prices("005930", history_start, as_of)
        if not stored.empty:
            fresh = fetch_incremental_prices("005930", history_start, as_of, stored,
                                             {as_of: fetch_daily_prices(as_of)})
            before = stored.set_index("Date").reindex(fresh.Date).reset_index(drop=True)
            fields = {}
            for column in fresh.columns.drop("Date"):
                left, right = fresh[column].to_numpy(float), before[column].to_numpy(float)
                unequal = ~((left == right) | (np.isnan(left) & np.isnan(right)))
                if unequal.any():
                    delta = np.abs(left[unequal] - right[unequal])
                    finite = delta[np.isfinite(delta)]
                    fields[column] = {"rows": int(unequal.sum()),
                                      "max_abs_difference": float(finite.max()) if len(finite) else None}
            print(json.dumps({"event": "incremental_price_check", "stock_code": "005930",
                              "changed_rows": len(changed_price_rows(fresh, stored)),
                              "fields": fields}, allow_nan=False), flush=True)
