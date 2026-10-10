import json
import os
from datetime import date

import pandas as pd
import pytest
from shared.data import providers as price_collector
from shared.data import trading_calendar


def _write_calendar_cache(path, start, end, trading_days):
    path.write_text(
        json.dumps(
            {
                "source": trading_calendar._TRADING_CALENDAR_SOURCE,
                "coverage_start": start,
                "coverage_end": end,
                "fetched_at": "2026-09-02T18:00:00+09:00",
                "trading_days": trading_days,
            }
        ),
        encoding="utf-8",
    )


def test_get_krx_trading_days_uses_kospi_index_and_saves_cache(tmp_path, monkeypatch):
    cache_path = tmp_path / "krx_trading_calendar.json"
    monkeypatch.setattr(trading_calendar, "TRADING_CALENDAR_CACHE_PATH", str(cache_path))

    calls = []

    def fake_index_ohlcv(start, end):
        calls.append((start, end))
        return pd.DataFrame(
            {"종가": [2600.0, 2610.0]},
            index=pd.to_datetime(["2026-08-31", "2026-09-01"]),
        )

    monkeypatch.setattr(trading_calendar, "_fetch_fdr_index", fake_index_ohlcv)

    result = trading_calendar.get_krx_trading_days("2026-08-29", "2026-09-01")

    assert result == {date(2026, 8, 31), date(2026, 9, 1)}
    assert calls == [(pd.Timestamp("2026-08-29"), pd.Timestamp("2026-09-01"))]
    payload = json.loads(cache_path.read_text(encoding="utf-8"))
    assert payload["coverage_start"] == "2026-08-29"
    assert payload["coverage_end"] == "2026-09-01"
    assert payload["provider"] == "FinanceDataReader KS11"
    assert payload["trading_days"] == ["2026-08-31", "2026-09-01"]


def test_get_krx_trading_days_falls_back_to_pykrx_index(tmp_path, monkeypatch):
    cache_path = tmp_path / "krx_trading_calendar.json"
    monkeypatch.setattr(trading_calendar, "TRADING_CALENDAR_CACHE_PATH", str(cache_path))
    monkeypatch.setattr(
        trading_calendar,
        "_fetch_fdr_index",
        lambda *args, **kwargs: (_ for _ in ()).throw(ConnectionError("FDR unavailable")),
    )
    monkeypatch.setattr(
        trading_calendar,
        "_fetch_pykrx_index",
        lambda *args, **kwargs: pd.DataFrame(
            {"종가": [2600.0]}, index=pd.to_datetime(["2026-09-01"])
        ),
    )

    result = trading_calendar.get_krx_trading_days("2026-08-31", "2026-09-01")

    assert result == {date(2026, 9, 1)}
    payload = json.loads(cache_path.read_text(encoding="utf-8"))
    assert payload["provider"] == "KRX KOSPI index 1001 via pykrx"


def test_get_krx_trading_days_uses_only_cache_covering_entire_range(
    tmp_path, monkeypatch
):
    cache_path = tmp_path / "krx_trading_calendar.json"
    _write_calendar_cache(
        cache_path,
        "2026-08-29",
        "2026-09-02",
        ["2026-08-31", "2026-09-01", "2026-09-02"],
    )
    monkeypatch.setattr(trading_calendar, "TRADING_CALENDAR_CACHE_PATH", str(cache_path))
    monkeypatch.setattr(
        trading_calendar,
        "_fetch_fdr_index",
        lambda *args, **kwargs: (_ for _ in ()).throw(ConnectionError("FDR unavailable")),
    )
    monkeypatch.setattr(
        trading_calendar,
        "_fetch_pykrx_index",
        lambda *args, **kwargs: (_ for _ in ()).throw(ConnectionError("KRX unavailable")),
    )

    result = trading_calendar.get_krx_trading_days("2026-08-30", "2026-09-01")

    assert result == {date(2026, 8, 31), date(2026, 9, 1)}


def test_get_krx_trading_days_prefers_covering_cache_without_network(tmp_path, monkeypatch):
    # #107: 종목별 추론이 호출마다 지수를 조회하지 않도록, 범위를 덮는 캐시가 있으면 네트워크를 쓰지 않는다
    cache_path = tmp_path / "krx_trading_calendar.json"
    _write_calendar_cache(cache_path, "2026-08-29", "2026-09-02", ["2026-08-31", "2026-09-01"])
    monkeypatch.setattr(trading_calendar, "TRADING_CALENDAR_CACHE_PATH", str(cache_path))
    calls = []
    monkeypatch.setattr(trading_calendar, "_fetch_fdr_index", lambda *args: calls.append("fdr"))
    monkeypatch.setattr(trading_calendar, "_fetch_pykrx_index", lambda *args: calls.append("pykrx"))

    assert trading_calendar.get_krx_trading_days("2026-08-31", "2026-09-01") == {
        date(2026, 8, 31),
        date(2026, 9, 1),
    }
    assert calls == []


def test_trading_calendar_cache_path_does_not_depend_on_cwd():
    assert os.path.isabs(trading_calendar.TRADING_CALENDAR_CACHE_PATH)
    from pathlib import Path

    from shared.settings import CHART_ROOT
    assert Path(trading_calendar.TRADING_CALENDAR_CACHE_PATH) == CHART_ROOT / "workspace/archive/data/krx_trading_calendar.json"


def test_get_krx_trading_days_fails_closed_for_incomplete_cache(tmp_path, monkeypatch):
    cache_path = tmp_path / "krx_trading_calendar.json"
    _write_calendar_cache(cache_path, "2026-09-01", "2026-09-02", ["2026-09-01"])
    monkeypatch.setattr(trading_calendar, "TRADING_CALENDAR_CACHE_PATH", str(cache_path))
    monkeypatch.setattr(
        trading_calendar,
        "_fetch_fdr_index",
        lambda *args, **kwargs: (_ for _ in ()).throw(ConnectionError("FDR unavailable")),
    )
    monkeypatch.setattr(
        trading_calendar,
        "_fetch_pykrx_index",
        lambda *args, **kwargs: (_ for _ in ()).throw(ConnectionError("KRX unavailable")),
    )

    with pytest.raises(trading_calendar.TradingCalendarError, match="캐시도 없습니다"):
        trading_calendar.get_krx_trading_days("2026-08-01", "2026-09-02")


def test_successful_refresh_replaces_overlap_and_preserves_outer_cache(
    tmp_path, monkeypatch
):
    cache_path = tmp_path / "krx_trading_calendar.json"
    _write_calendar_cache(
        cache_path,
        "2026-08-29",
        "2026-09-02",
        ["2026-08-31", "2026-09-01", "2026-09-02"],
    )
    monkeypatch.setattr(trading_calendar, "TRADING_CALENDAR_CACHE_PATH", str(cache_path))
    monkeypatch.setattr(
        trading_calendar,
        "_fetch_fdr_index",
        lambda *args, **kwargs: pd.DataFrame(
            {"종가": [2610.0, 2620.0]},
            index=pd.to_datetime(["2026-09-01", "2026-09-03"]),
        ),
    )

    trading_calendar.get_krx_trading_days("2026-09-01", "2026-09-03")

    payload = json.loads(cache_path.read_text(encoding="utf-8"))
    assert payload["coverage_start"] == "2026-08-29"
    assert payload["coverage_end"] == "2026-09-03"
    assert payload["trading_days"] == ["2026-08-31", "2026-09-01", "2026-09-03"]


def test_daily_bulk_update_uses_exact_krx_snapshot_date(tmp_path, monkeypatch):
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()
    monkeypatch.setattr(price_collector, "DATA_DIR", str(raw_dir))
    monkeypatch.setattr(
        price_collector,
        "get_krx_trading_days",
        lambda start, end: {date(2026, 8, 31), date(2026, 9, 1)},
    )

    listing_calls = []

    def fake_stock_listing(market):
        listing_calls.append(market)
        return pd.DataFrame(
            {
                "Code": ["005930"] if market == "KOSPI" else [],
                "Open": [70000] if market == "KOSPI" else [],
                "High": [71000] if market == "KOSPI" else [],
                "Low": [69000] if market == "KOSPI" else [],
                "Close": [70500] if market == "KOSPI" else [],
                "Volume": [1000] if market == "KOSPI" else [],
                "Amount": [70400000] if market == "KOSPI" else [],
                "ChagesRatio": [0.5] if market == "KOSPI" else [],
            }
        )

    monkeypatch.setattr(price_collector.fdr, "StockListing", fake_stock_listing)
    stocks = pd.DataFrame(
        [{"Code": "005930", "Name": "삼성전자", "IsDelisted": False}]
    )

    updated, actual_date = price_collector._update_ohlcv_bulk_fdr(stocks)

    assert updated == {"005930"}
    assert actual_date == pd.Timestamp("2026-09-01")
    assert listing_calls == ["KOSPI", "KOSDAQ"]
    stored = pd.read_parquet(raw_dir / "005930.parquet")
    assert stored.loc[0, "Date"] == pd.Timestamp("2026-09-01")
    assert stored.loc[0, "Close"] == 70500
    assert stored.loc[0, "VWAP"] == 70400
    assert stored.loc[0, "Amount"] == 70400000


def test_delisted_listing_uses_authenticated_krx_response(monkeypatch):
    calls = []

    class Response:
        def raise_for_status(self):
            pass

        def json(self):
            return {"output": [{
                "ISU_CD": "123456", "ISU_NM": "과거 종목", "MKT_NM": "KOSDAQ",
                "SECUGRP_NM": "주권", "LIST_DD": "2020/03/02",
                "DELIST_DD": "2020/03/05",
            }]}

    class Session:
        def post(self, url, data, timeout):
            calls.append((url, data, timeout))
            return Response()

    monkeypatch.setattr(price_collector, "get_krx_session", lambda: Session())
    result = price_collector._fetch_delisted_list(pd.Timestamp.today().strftime("%Y-%m-%d"))

    assert result.loc[0, "Symbol"] == "123456"
    assert result.loc[0, "DelistingDate"] == "2020/03/05"
    assert calls[0][1]["bld"] == "dbms/MDC/STAT/issue/MDCSTAT23801"


def test_delisted_listing_requires_krx_session(monkeypatch):
    monkeypatch.setattr(price_collector, "get_krx_session", lambda: None)
    with pytest.raises(RuntimeError, match="KRX_ID와 KRX_PW"):
        price_collector._fetch_delisted_list("2016-01-01")


def test_attach_actual_vwap_matches_adjusted_price_scale():
    dates = pd.to_datetime(["2018-04-27", "2018-05-04"])
    adjusted = pd.DataFrame(
        {
            "Open": [50.0, 52.0],
            "High": [52.0, 55.0],
            "Low": [49.0, 51.0],
            "Close": [50.0, 54.0],
            "Volume": [100.0, 200.0],
            "Change": [0.0, 8.0],
        },
        index=dates,
    )
    raw = pd.DataFrame(
        {
            "시가": [5000.0, 5200.0], "고가": [5200.0, 5500.0], "저가": [4900.0, 5100.0],
            "종가": [5000.0, 5400.0],
            "거래량": [100.0, 200.0],
            "거래대금": [510000.0, 1060000.0],
        },
        index=dates,
    )

    result = price_collector._attach_actual_vwap(adjusted, raw)

    assert result["AdjustmentFactor"].tolist() == pytest.approx([0.01, 0.01])
    assert result["VWAP"].tolist() == pytest.approx([51.0, 53.0])
    assert result["RawClose"].tolist() == [5000.0, 5400.0]
    assert result["RawVolume"].tolist() == [100.0, 200.0]


def test_attach_actual_vwap_rejects_missing_turnover_on_trading_day():
    adjusted = pd.DataFrame(
        {"Close": [100.0], "Volume": [10.0]},
        index=pd.to_datetime(["2026-09-01"]),
    )
    raw = pd.DataFrame(
        {"시가": [100.0], "고가": [100.0], "저가": [100.0], "종가": [100.0], "거래량": [10.0], "거래대금": [0.0]},
        index=adjusted.index,
    )

    with pytest.raises(ValueError, match="거래대금/거래량"):
        price_collector._attach_actual_vwap(adjusted, raw)


def test_fdr_history_joins_unadjusted_krx_turnover(monkeypatch):
    index = pd.to_datetime(["2026-09-01"])
    adjusted = pd.DataFrame(
        {
            "Open": [99.0],
            "High": [102.0],
            "Low": [98.0],
            "Close": [100.0],
            "Volume": [10.0],
            "Change": [0.01],
        },
        index=index,
    )
    raw = pd.DataFrame(
        {"시가": [198.0], "고가": [204.0], "저가": [196.0], "종가": [200.0], "거래량": [10.0], "거래대금": [2020.0]}, index=index
    )
    raw_calls = []
    monkeypatch.setattr(price_collector.fdr, "DataReader", lambda *args: adjusted)

    def fake_raw(fromdate, todate, code, adjusted):
        raw_calls.append((fromdate, todate, code, adjusted))
        return raw

    monkeypatch.setattr(price_collector.krx, "get_market_ohlcv_by_date", fake_raw)

    result = price_collector._fetch_ohlcv_fdr("005930", "2026-09-01", "2026-09-01")

    assert raw_calls == [("20260901", "20260901", "005930", False)]
    assert result.loc[index[0], "Change"] == pytest.approx(1.0)
    assert result.loc[index[0], "VWAP"] == pytest.approx(101.0)
    assert result.loc[index[0], "AdjustmentFactor"] == pytest.approx(0.5)


def test_actual_vwap_completeness_checks_values_not_only_columns():
    frame = pd.DataFrame(
        {
            "Volume": [100.0, 200.0],
            "Amount": [10000.0, pd.NA],
            "RawClose": [100.0, pd.NA],
            "RawVolume": [100.0, pd.NA],
            "AdjustmentFactor": [1.0, pd.NA],
            "VWAP": [100.0, pd.NA],
        }
    )

    assert not price_collector._has_complete_actual_vwap(frame)


def test_update_ohlcv_daily_reports_bulk_failure(monkeypatch):
    monkeypatch.setattr(price_collector, "get_all_tickers", lambda **kwargs: pd.DataFrame())
    monkeypatch.setattr(price_collector, "_update_ohlcv_bulk_fdr", lambda stocks: (set(), pd.Timestamp("2026-09-01")))

    with pytest.raises(RuntimeError, match="업데이트에 실패"):
        price_collector.update_ohlcv_daily()


def test_daily_update_passes_price_date_to_investor_collector(monkeypatch):
    stocks = pd.DataFrame([{"Code": "005930"}])
    monkeypatch.setattr(price_collector, "get_all_tickers", lambda **kwargs: stocks)
    monkeypatch.setattr(
        price_collector,
        "_update_ohlcv_bulk_fdr",
        lambda rows: ({"005930"}, pd.Timestamp("2026-09-01")),
    )
    calls = []
    monkeypatch.setattr(
        price_collector,
        "_cached_investor_day",
        lambda day: (calls.append(day) or pd.DataFrame()),
    )
    monkeypatch.setattr(price_collector, "_merge_investor_flows", lambda *args, **kwargs: None)

    price_collector.update_ohlcv_daily()

    assert calls == [pd.Timestamp("2026-09-01")]


def test_full_collection_runs_investor_backfill_after_price_save(tmp_path, monkeypatch):
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()
    monkeypatch.setattr(price_collector, "DATA_DIR", str(raw_dir))
    monkeypatch.setattr(
        price_collector,
        "get_all_tickers",
        lambda *args: pd.DataFrame([{
            "Code": "005930", "Name": "삼성전자", "IsDelisted": False,
            "ListingDate": pd.NaT, "DelistingDate": pd.NaT,
        }]),
    )
    monkeypatch.setattr(price_collector, "get_krx_trading_days", lambda *args: {date(2026, 9, 1)})
    prices = pd.DataFrame(
        {"Open": [100], "High": [110], "Low": [90], "Close": [105],
         "Volume": [10], "Change": [5], "Amount": [1000], "RawClose": [105],
         "RawVolume": [10], "AdjustmentFactor": [1], "VWAP": [100]},
        index=pd.DatetimeIndex(["2026-09-01"], name="Date"),
    )
    monkeypatch.setattr(price_collector, "_fetch_ohlcv_fdr", lambda *args: prices)
    monkeypatch.setattr(price_collector.time, "sleep", lambda *args: None)
    calls = []

    def backfill(**kwargs):
        assert (raw_dir / "005930.parquet").exists()
        calls.append(kwargs)

    monkeypatch.setattr(price_collector, "_backfill_investor_flows", backfill)

    price_collector.download_ohlcv_full(start_date="2026-09-01")

    assert calls[0]["start_date"] == "2026-09-01"


def test_full_collects_delisted_only_within_listing_period(tmp_path, monkeypatch):
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()
    monkeypatch.setattr(price_collector, "DATA_DIR", str(raw_dir))
    monkeypatch.setattr(
        price_collector, "get_all_tickers",
        lambda *args: pd.DataFrame([{
            "Code": "123456", "Name": "과거 종목", "IsDelisted": True,
            "ListingDate": pd.Timestamp("2020-03-02"),
            "DelistingDate": pd.Timestamp("2020-03-05"),
        }]),
    )
    monkeypatch.setattr(
        price_collector, "get_krx_trading_days",
        lambda *args: {date(2020, 3, 2), date(2020, 3, 3), date(2020, 3, 4)},
    )
    calls = []
    prices = pd.DataFrame(
        {"Open": [100], "High": [105], "Low": [95], "Close": [101],
         "Volume": [10], "Amount": [1000], "Change": [1], "RawClose": [101],
         "RawVolume": [10], "AdjustmentFactor": [1], "VWAP": [100]},
        index=pd.DatetimeIndex(["2020-03-04"], name="Date"),
    )
    monkeypatch.setattr(
        price_collector, "_fetch_delisted_pykrx",
        lambda code, start, end: (calls.append((code, start, end)) or prices),
    )
    monkeypatch.setattr(price_collector.time, "sleep", lambda *args: None)
    monkeypatch.setattr(price_collector, "_backfill_investor_flows", lambda **kwargs: None)

    price_collector.download_ohlcv_full(start_date="2019-01-01")

    assert calls == [("123456", "2020-03-02", "2020-03-04")]
    stored = pd.read_parquet(raw_dir / "123456.parquet")
    assert stored.loc[0, "IsDelisted"]
    assert stored.loc[0, "Date"] == pd.Timestamp("2020-03-04")


def test_delisted_pykrx_adjusts_turnover_vwap_to_price_scale(monkeypatch):
    raw = pd.DataFrame(
        {"시가": [100], "고가": [110], "저가": [90], "종가": [105],
         "거래량": [10], "거래대금": [1020], "등락률": [5]},
        index=pd.DatetimeIndex(["2020-03-04"], name="Date"),
    )
    calls = []
    adjusted_prices = pd.DataFrame(
        {"시가": [50], "고가": [55], "저가": [45], "종가": [52.5],
         "거래량": [10], "등락률": [5.0]},
        index=raw.index,
    )
    def fake_ohlcv(start, end, code, adjusted):
        calls.append((start, end, code, adjusted))
        return adjusted_prices if adjusted else raw

    monkeypatch.setattr(
        price_collector.krx,
        "get_market_ohlcv_by_date",
        fake_ohlcv,
    )

    result = price_collector._fetch_delisted_pykrx("123456", "2020-03-02", "2020-03-04")

    assert calls == [
        ("20200302", "20200304", "123456", False),
        ("20200302", "20200304", "123456", True),
    ]
    assert result.loc[pd.Timestamp("2020-03-04"), "Change"] == pytest.approx(5)
    assert result.loc[pd.Timestamp("2020-03-04"), "RawClose"] == 105
    assert result.loc[pd.Timestamp("2020-03-04"), "AdjustmentFactor"] == pytest.approx(0.5)
    assert result.loc[pd.Timestamp("2020-03-04"), "VWAP"] == pytest.approx(51)


def test_investor_day_keeps_buy_and_sell_volumes(monkeypatch):
    calls = []

    def fake_flow(start, end, market, investor):
        calls.append(investor)
        return pd.DataFrame(
            {"매수거래량": [12], "매도거래량": [10], "순매수거래량": [2],
             "매수거래대금": [1200], "매도거래대금": [1000],
             "순매수거래대금": [200]},
            index=pd.Index(["005930"], name="티커"),
        )

    monkeypatch.setattr(price_collector.krx, "get_market_net_purchases_of_equities_by_ticker", fake_flow)
    monkeypatch.setattr(price_collector.time, "sleep", lambda *args: None)

    from types import SimpleNamespace

    import requests

    monkeypatch.setattr(price_collector, "get_krx_session", lambda: SimpleNamespace(session=requests.Session()))
    result = price_collector._fetch_investor_day(pd.Timestamp("2020-03-04"))

    assert calls == ["개인", "기관합계", "외국인"]
    assert result.loc[0, "Individual_BuyVolume"] == 12
    assert result.loc[0, "Foreign_SellAmount"] == 1000


def test_flow_timeout_restored_and_only_failed_investor_retried(monkeypatch):
    from types import SimpleNamespace

    import requests

    session = requests.Session()
    observed = []
    original = session.request

    def request(*args, **kwargs):
        observed.append(kwargs["timeout"])
        if len(observed) == 1:
            raise requests.Timeout("slow response")
        return pd.DataFrame(
            {"매수거래량": [12], "매도거래량": [10], "순매수거래량": [2],
             "매수거래대금": [1200], "매도거래대금": [1000], "순매수거래대금": [200]},
            index=["005930"],
        )

    monkeypatch.setattr(session, "request", request)
    monkeypatch.setattr(price_collector, "get_krx_session", lambda: SimpleNamespace(session=session))
    calls = []

    def fetch(*args, investor, **kwargs):
        calls.append(investor)
        return session.request("POST", "https://example.invalid")

    monkeypatch.setattr(price_collector.krx, "get_market_net_purchases_of_equities_by_ticker", fetch)
    monkeypatch.setattr(price_collector.time, "sleep", lambda *_: None)
    events = []
    frame = price_collector._fetch_investor_day(pd.Timestamp("2020-03-04"), progress=events.append)
    assert len(frame) == 1
    assert calls == ["개인", "개인", "기관합계", "외국인"]
    assert observed == [(10, 30)] * 4
    assert events[1]["state"] == "request_failed"
    assert session.request is request
    session.request = original


def test_flow_request_exhaustion_is_bounded(monkeypatch):
    from types import SimpleNamespace

    import requests

    session = requests.Session()
    monkeypatch.setattr(price_collector, "get_krx_session", lambda: SimpleNamespace(session=session))
    calls = []

    def fail(*args, **kwargs):
        calls.append(kwargs["investor"])
        raise requests.Timeout("slow response")

    monkeypatch.setattr(price_collector.krx, "get_market_net_purchases_of_equities_by_ticker", fail)
    monkeypatch.setattr(price_collector.time, "sleep", lambda *_: None)
    with pytest.raises(RuntimeError, match="failed after 3 attempts"):
        price_collector._fetch_investor_day(pd.Timestamp("2020-03-04"))
    assert calls == ["개인"] * 3
    assert "request" not in session.__dict__


def test_krx_non_json_auth_response_is_not_swallowed(monkeypatch):
    from types import SimpleNamespace

    import requests

    session = requests.Session()
    response = requests.Response()
    response.status_code = 200
    response._content = b"LOGOUT"
    response.headers["Content-Type"] = "text/html"
    monkeypatch.setattr(session, "request", lambda *args, **kwargs: response)
    authenticated = SimpleNamespace(session=session, expiry_time=100)
    monkeypatch.setattr(price_collector, "get_krx_session", lambda: authenticated)
    with pytest.raises(price_collector.KrxResponseError, match="authentication lost") as caught:
        with price_collector._krx_request_timeout():
            session.post("https://data.krx.co.kr/comm/bldAttendant/getJsonData.cmd")
    assert authenticated.expiry_time == 0
    assert caught.value.details["http_status"] == 200
    assert caught.value.details["response_kind"] == "auth_expired"


def test_krx_non_json_service_error_does_not_force_login(monkeypatch):
    from types import SimpleNamespace

    import requests

    session = requests.Session()
    response = requests.Response()
    response.status_code = 200
    response._content = b"<html>service unavailable</html>"
    response.headers["Content-Type"] = "text/html"
    monkeypatch.setattr(session, "request", lambda *args, **kwargs: response)
    authenticated = SimpleNamespace(session=session, expiry_time=100)
    monkeypatch.setattr(price_collector, "get_krx_session", lambda: authenticated)
    with pytest.raises(price_collector.KrxResponseError, match="non-JSON response"):
        with price_collector._krx_request_timeout():
            session.post("https://data.krx.co.kr/comm/bldAttendant/getJsonData.cmd")
    assert authenticated.expiry_time == 100
