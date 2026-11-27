import sys
from contextlib import nullcontext
from types import SimpleNamespace

import pandas as pd
import pytest
from shared.data import bulk_prices, providers
from shared.data import prices as shared_prices
from shared.io import atomic_json, atomic_parquet, sha256


def _raw_day(day, codes):
    return pd.DataFrame({"Date": day, "Code": codes, "RawOpen": 100, "RawHigh": 110,
                         "RawLow": 90, "RawClose": 100, "RawChange": 0, "RawVolume": 10,
                         "Amount": 1000, "ListedShares": 100_000})


def test_bulk_cache_resume_corruption_and_missing_stock(tmp_path, monkeypatch):
    days = pd.bdate_range("2024-01-02", periods=3)
    codes = [f"{n:06d}" for n in range(10)]
    metadata = pd.DataFrame({"Code": codes, "ListingDate": days[0], "DelistingDate": pd.NaT})
    calendar = {"trading_days": days.strftime("%Y-%m-%d").tolist()}
    calls = []
    interrupted = [True]

    def fetch(day):
        label = day.strftime("%Y%m%d")
        calls.append(label)
        if label == "20240103" and interrupted[0]:
            raise KeyboardInterrupt()
        return _raw_day(day, codes if label != "20240104" else codes[:-1])

    monkeypatch.setattr(bulk_prices, "request_day", fetch)
    monkeypatch.setattr(bulk_prices.time, "sleep", lambda _: None)
    source = SimpleNamespace(_krx_request_timeout=nullcontext)
    report = {}
    with pytest.raises(KeyboardInterrupt):
        bulk_prices.prepare_bulk_prices(tmp_path, metadata, calendar, report, source)
    assert report["price_day_progress"]["completed_days"] == 1
    assert (tmp_path / "krx_price_day_cache/2024-01-02.parquet").exists()
    interrupted[0] = False
    calls.clear()
    grouped = bulk_prices.prepare_bulk_prices(tmp_path, metadata, calendar, {}, source)
    assert calls == ["20240103", "20240104"]
    assert len(bulk_prices.stock_raw(grouped, codes[0], days)) == 3
    assert bulk_prices.stock_raw(grouped, codes[-1], days) is None
    path = tmp_path / "krx_price_day_cache/2024-01-02.parquet"
    damaged = pd.read_parquet(path).assign(Date=days[-1])
    atomic_parquet(path, damaged)
    atomic_json(path.with_suffix(".json"), {"version": bulk_prices.CACHE_VERSION, "sha256": sha256(path)})
    calls.clear()
    bulk_prices.prepare_bulk_prices(tmp_path, metadata, calendar, {}, source)
    assert calls == ["20240102"]
    calls.clear()
    bulk_prices.prepare_bulk_prices(tmp_path, metadata, calendar, {}, source)
    assert calls == []


@pytest.mark.parametrize("price_provider", ["fdr", "pykrx"])
def test_price_adapter_supplied_raw_skips_individual_krx_request(tmp_path, monkeypatch, price_provider):
    days = pd.bdate_range("2024-01-02", periods=3)
    adjusted_prices = pd.DataFrame(
        {"Open": 50, "High": 51, "Low": 49, "Close": 50, "Volume": 10, "Change": 0.02}, index=days
    )
    raw = pd.DataFrame({"RawOpen": 100, "RawHigh": 102, "RawLow": 98, "RawClose": 100, "RawVolume": 10, "Amount": 1000}, index=days)
    calls = []

    def read_fdr(code, start, end):
        assert (code, start, end) == ("005930", "2024-01-02", "2024-01-04")
        calls.append("fdr")
        return adjusted_prices if price_provider == "fdr" else pd.DataFrame()

    def read_pykrx(start, end, code, *, adjusted):
        assert (start, end, code) == ("20240102", "20240104", "005930")
        assert adjusted
        calls.append("pykrx")
        return adjusted_prices.assign(Change=2).rename(columns={
            "Open": "시가", "High": "고가", "Low": "저가", "Close": "종가", "Volume": "거래량", "Change": "등락률"
        })

    monkeypatch.setitem(sys.modules, "FinanceDataReader", SimpleNamespace(DataReader=read_fdr))
    monkeypatch.setattr(providers.krx, "get_market_ohlcv_by_date", read_pykrx)
    source = SimpleNamespace(_krx_request_timeout=nullcontext, time=SimpleNamespace(sleep=lambda _: None))
    result = shared_prices.fetch_price_window("005930", days, root=tmp_path, raw=raw, source=source)
    assert calls == (["fdr"] if price_provider == "fdr" else ["fdr"] * 3 + ["pykrx"])
    assert result.PriceProvider.tolist() == [price_provider] * 3
    assert result.Change.tolist() == [2] * 3
    assert result.VWAP.tolist() == [50] * 3
    assert result.AdjustmentFactor.tolist() == [0.5] * 3


def test_new_daily_source_keeps_legacy_cache_unchanged(tmp_path, monkeypatch):
    days = pd.bdate_range("2024-01-02", periods=3)
    codes = [f"{n:06d}" for n in range(10)]
    metadata = pd.DataFrame({"Code": codes, "ListingDate": days[0], "DelistingDate": pd.NaT})
    calendar = {"trading_days": days.strftime("%Y-%m-%d").tolist()}
    originals = {}
    for day in days:
        path = tmp_path / "price_day_cache" / f"{day:%Y-%m-%d}.parquet"
        frame = pd.DataFrame({"Date": day, "Code": codes, "RawClose": 100, "RawVolume": 10, "Amount": 1000})
        atomic_parquet(path, frame)
        originals[path] = sha256(path)
        atomic_json(path.with_suffix(".json"), {"version": 1, "sha256": originals[path]})
    calls = []
    monkeypatch.setattr(bulk_prices.time, "sleep", lambda _: None)

    def fetch(day):
        calls.append(day.strftime("%Y%m%d"))
        return _raw_day(day, codes)

    monkeypatch.setattr(bulk_prices, "request_day", fetch)
    source = SimpleNamespace(_krx_request_timeout=nullcontext)
    grouped = bulk_prices.prepare_bulk_prices(tmp_path, metadata, calendar, {}, source)
    assert calls == days.strftime("%Y%m%d").tolist()
    stock = bulk_prices.stock_raw(grouped, codes[0], days)
    assert stock.RawHigh.tolist() == [110] * 3
    assert originals == {path: sha256(path) for path in originals}
    calls.clear()
    bulk_prices.prepare_bulk_prices(tmp_path, metadata, calendar, {}, source)
    assert calls == []


def test_daily_empty_response_retries_without_zero_rows(monkeypatch):
    calls = []
    monkeypatch.setattr(bulk_prices.time, "sleep", lambda *_: None)

    def fetch(*args, **kwargs):
        calls.append(args)
        return pd.DataFrame()

    monkeypatch.setattr(bulk_prices, "request_day", fetch)
    source = SimpleNamespace(_krx_request_timeout=nullcontext)
    with pytest.raises(ValueError, match="Empty"):
        bulk_prices.fetch_day(source, pd.Timestamp("2024-01-02"), lambda _: None)
    assert len(calls) == 3


def test_continuous_provider_failure_stops_dates_without_cache(tmp_path, monkeypatch):
    days = pd.bdate_range("2024-01-02", periods=5)
    codes = [f"{n:06d}" for n in range(10)]
    metadata = pd.DataFrame({"Code": codes, "ListingDate": days[0], "DelistingDate": pd.NaT})
    calls, waits = [], []
    monkeypatch.setattr(bulk_prices.time, "sleep", waits.append)

    def fail(day):
        calls.append(day.strftime("%Y%m%d"))
        raise RuntimeError("KRX non-JSON response")

    monkeypatch.setattr(bulk_prices, "request_day", fail)
    source = SimpleNamespace(_krx_request_timeout=nullcontext)
    with pytest.raises(RuntimeError, match="3 consecutive"):
        bulk_prices.prepare_bulk_prices(tmp_path, metadata,
            {"trading_days": days.strftime("%Y-%m-%d").tolist()}, {}, source)
    assert calls == [d for d in days[:3].strftime("%Y%m%d") for _ in range(3)]
    assert waits == [5, 15] * 3
    import json

    report = json.loads((tmp_path / "collection_report.json").read_text())
    assert report["status"] == "failed"
    assert report["price_day_progress"]["consecutive_failures"] == 3
    assert not list(tmp_path.glob("krx_price_day_cache/*.parquet"))


def test_failure_history_records_every_attempt_and_survives_rerun(tmp_path, monkeypatch):
    import json

    from experiments.config import append_collection_event
    from shared.data.providers import KrxResponseError

    days = pd.bdate_range("2024-01-02", periods=4)
    codes = [f"{n:06d}" for n in range(10)]
    metadata = pd.DataFrame({"Code": codes, "ListingDate": days[0], "DelistingDate": pd.NaT})
    monkeypatch.setattr(bulk_prices.time, "sleep", lambda *_: None)

    def fail(*args, **kwargs):
        raise KrxResponseError("KRX non-JSON response", http_status=200,
                               content_type="text/html", response_bytes=25, response_kind="non_json")

    monkeypatch.setattr(bulk_prices, "request_day", fail)
    source = SimpleNamespace(_krx_request_timeout=nullcontext)
    for _ in range(2):
        with pytest.raises(RuntimeError, match="3 consecutive"):
            bulk_prices.prepare_bulk_prices(tmp_path, metadata,
                {"trading_days": days.strftime("%Y-%m-%d").tolist()}, {}, source)
    events = [json.loads(line) for line in (tmp_path / "collection_events.jsonl").read_text().splitlines()]
    attempts = [event for event in events if event["state"] == "request_failed"]
    assert len(attempts) == 18
    assert [event["attempt"] for event in attempts[:3]] == [1, 2, 3]
    assert attempts[0]["date"] == "2024-01-02"
    assert attempts[0]["http_status"] == 200
    assert attempts[0]["response_kind"] == "non_json"
    assert attempts[0]["exception_type"] == "KrxResponseError"
    assert "timestamp" in attempts[0] and "elapsed_seconds" in attempts[0]
    append_collection_event(tmp_path, {"stage": "flows", "state": "failed", "investor": "Foreign"})
    assert len((tmp_path / "collection_events.jsonl").read_text().splitlines()) == len(events) + 1
