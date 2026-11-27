import json
import os

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


def test_trading_calendar_cache_path_does_not_depend_on_cwd():
    assert os.path.isabs(trading_calendar.TRADING_CALENDAR_CACHE_PATH)
    from pathlib import Path

    from shared.settings import CHART_ROOT
    assert Path(trading_calendar.TRADING_CALENDAR_CACHE_PATH) == CHART_ROOT / "workspace/archive/data/krx_trading_calendar.json"


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


def test_verified_calendar_agrees_with_direct_krx_and_xkrx_and_reuses_cache(tmp_path, monkeypatch):
    path = tmp_path / "calendar.json"
    monkeypatch.setattr(trading_calendar, "TRADING_CALENDAR_CACHE_PATH", str(path))
    days = pd.bdate_range("2024-01-02", "2024-01-05")
    frame = pd.DataFrame({"종가": 2500.0}, index=days)
    calls = []
    monkeypatch.setattr(trading_calendar, "_fetch_pykrx_index", lambda *_: (calls.append("pykrx") or frame))
    monkeypatch.setattr(trading_calendar, "_fetch_direct_index", lambda *_: (calls.append("direct") or frame))
    assert trading_calendar.get_krx_trading_days("2024-01-02", "2024-01-07") == set(days.date)
    assert calls == ["pykrx", "direct"]
    payload = json.loads(path.read_text())
    assert payload["provider"] == trading_calendar._TRADING_CALENDAR_PROVIDER
    trading_calendar.get_krx_trading_days("2024-01-03", "2024-01-05")
    assert calls == ["pykrx", "direct"]


@pytest.mark.parametrize("both_incomplete", [False, True])
def test_calendar_rejects_missing_sessions_without_writing_cache(tmp_path, monkeypatch, both_incomplete):
    path = tmp_path / "calendar.json"
    monkeypatch.setattr(trading_calendar, "TRADING_CALENDAR_CACHE_PATH", str(path))
    frame = pd.DataFrame({"종가": 2500.0}, index=pd.bdate_range("2024-01-02", "2024-01-05"))
    incomplete = frame.drop(index=frame.index[1])
    monkeypatch.setattr(trading_calendar, "_fetch_pykrx_index", lambda *_: incomplete)
    monkeypatch.setattr(trading_calendar, "_fetch_direct_index", lambda *_: incomplete if both_incomplete else frame)
    with pytest.raises(trading_calendar.TradingCalendarError):
        trading_calendar.get_krx_trading_days("2024-01-02", "2024-01-05")
    assert not path.exists()


def test_legacy_calendar_cache_is_reverified(tmp_path, monkeypatch):
    path = tmp_path / "calendar.json"
    monkeypatch.setattr(trading_calendar, "TRADING_CALENDAR_CACHE_PATH", str(path))
    _write_calendar_cache(path, "2024-01-02", "2024-01-05", ["2024-01-02"])
    payload = json.loads(path.read_text())
    payload["source"] = "KOSPI index trading days"
    path.write_text(json.dumps(payload))
    frame = pd.DataFrame({"종가": 2500.0}, index=pd.bdate_range("2024-01-02", "2024-01-05"))
    monkeypatch.setattr(trading_calendar, "_fetch_pykrx_index", lambda *_: frame)
    monkeypatch.setattr(trading_calendar, "_fetch_direct_index", lambda *_: frame)
    assert trading_calendar.get_krx_trading_days("2024-01-02", "2024-01-05") == set(frame.index.date)


def test_verified_calendar_refresh_preserves_outer_cache(tmp_path, monkeypatch):
    path = tmp_path / "calendar.json"
    monkeypatch.setattr(trading_calendar, "TRADING_CALENDAR_CACHE_PATH", str(path))
    _write_calendar_cache(path, "2024-01-02", "2024-01-04", ["2024-01-02", "2024-01-03", "2024-01-04"])
    frame = pd.DataFrame({"종가": 2500.0}, index=pd.bdate_range("2024-01-04", "2024-01-05"))
    monkeypatch.setattr(trading_calendar, "_fetch_pykrx_index", lambda *_: frame)
    monkeypatch.setattr(trading_calendar, "_fetch_direct_index", lambda *_: frame)
    trading_calendar.get_krx_trading_days("2024-01-04", "2024-01-05")
    assert json.loads(path.read_text())["trading_days"] == pd.bdate_range("2024-01-02", "2024-01-05").strftime("%Y-%m-%d").tolist()
