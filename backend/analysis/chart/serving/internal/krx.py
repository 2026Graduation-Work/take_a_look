"""Read-only operational diagnostics using the shared KRX authentication policy."""
import json
import os
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from shared.data.krx import authenticated_stock


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
            before = stored.set_index("Date").reindex(fresh.Date).reset_index(drop=True).reindex(columns=fresh.columns)
            fields = {}
            for column in fresh.select_dtypes(include="number").columns:
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
