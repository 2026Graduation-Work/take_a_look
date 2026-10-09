"""Daily cache resume and raw adapter parity, without contacting providers."""

from contextlib import nullcontext
from types import SimpleNamespace

import pandas as pd
import pytest
from core import bulk_prices
from core.local_config import atomic_json, atomic_parquet
from core.local_dataset import sha256
from data_collectors import price_collector


def test_bulk_cache_resume_corruption_and_missing_stock(tmp_path, monkeypatch):
    days = pd.bdate_range("2024-01-02", periods=3)
    codes = [f"{n:06d}" for n in range(10)]
    metadata = pd.DataFrame({"Code": codes, "ListingDate": days[0], "DelistingDate": pd.NaT})
    calendar = {"trading_days": days.strftime("%Y-%m-%d").tolist()}
    calls = []
    interrupted = [True]

    def fetch(day, **kwargs):
        assert kwargs == {"market": "ALL", "alternative": False}
        calls.append(day)
        if day == "20240103" and interrupted[0]:
            raise KeyboardInterrupt()
        present = codes if day != "20240104" else codes[:-1]
        return pd.DataFrame({"시가": 100, "고가": 110, "저가": 90, "종가": 100, "거래량": 10, "거래대금": 1000}, index=present)

    source = SimpleNamespace(krx=SimpleNamespace(get_market_ohlcv_by_ticker=fetch),
                             _krx_request_timeout=nullcontext)
    report = {}
    with pytest.raises(KeyboardInterrupt):
        bulk_prices.prepare_bulk_prices(tmp_path, metadata, calendar, "full", report, source)
    assert report["price_day_progress"]["completed_days"] == 1
    assert (tmp_path / "price_day_cache/2024-01-02.parquet").exists()
    interrupted[0] = False
    calls.clear()
    grouped = bulk_prices.prepare_bulk_prices(tmp_path, metadata, calendar, "full", {}, source)
    assert calls == ["20240103", "20240104"]
    assert len(bulk_prices.stock_raw(grouped, codes[0], days)) == 3
    assert bulk_prices.stock_raw(grouped, codes[-1], days) is None
    # A wrong-date cache with an otherwise valid hash must be refetched.
    path = tmp_path / "price_day_cache/2024-01-02.parquet"
    damaged = pd.read_parquet(path).assign(Date=days[-1])
    atomic_parquet(path, damaged)
    atomic_json(path.with_suffix(".json"), {"version": 1, "sha256": sha256(path)})
    calls.clear()
    bulk_prices.prepare_bulk_prices(tmp_path, metadata, calendar, "full", {}, source)
    assert calls == ["20240102"]
    # Update refreshes even good day caches to detect source revisions.
    calls.clear()
    bulk_prices.prepare_bulk_prices(tmp_path, metadata, calendar, "update", {}, source)
    assert calls == ["20240102", "20240103", "20240104"]


def test_price_adapter_supplied_raw_skips_individual_krx_request(monkeypatch):
    days = pd.bdate_range("2024-01-02", periods=3)
    adjusted = pd.DataFrame({"Open": 50, "High": 51, "Low": 49, "Close": 50,
                             "Volume": 10, "Change": 0}, index=days)
    raw = pd.DataFrame({"RawOpen": 100, "RawHigh": 102, "RawLow": 98, "RawClose": 100, "RawVolume": 10, "Amount": 1000}, index=days)
    monkeypatch.setattr(price_collector.fdr, "DataReader", lambda *_: adjusted)

    def forbidden(*args, **kwargs):
        raise AssertionError("individual raw request was repeated")

    monkeypatch.setattr(price_collector.krx, "get_market_ohlcv_by_date", forbidden)
    result = price_collector._fetch_ohlcv_fdr("005930", "2024-01-02", "2024-01-04", raw_df=raw)
    assert result.VWAP.tolist() == [50] * 3
    assert result.AdjustmentFactor.tolist() == [0.5] * 3


def test_legacy_days_enriched_once_without_overwriting_cache(tmp_path, monkeypatch):
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

    def fetch(day, **kwargs):
        calls.append(day)
        return pd.DataFrame({"시가": 100, "고가": 110, "저가": 90,
                             "종가": 100, "거래량": 10, "거래대금": 1000}, index=codes)

    source = SimpleNamespace(krx=SimpleNamespace(get_market_ohlcv_by_ticker=fetch),
                             _krx_request_timeout=nullcontext)
    grouped = bulk_prices.prepare_bulk_prices(tmp_path, metadata, calendar, "full", {}, source)
    assert calls == days.strftime("%Y%m%d").tolist()
    stock = bulk_prices.stock_raw(grouped, codes[0], days)
    assert stock.RawHigh.tolist() == [110] * 3
    assert originals == {path: sha256(path) for path in originals}
    calls.clear()
    bulk_prices.prepare_bulk_prices(tmp_path, metadata, calendar, "full", {}, source)
    assert calls == []
    # Revisions cannot be silently adopted as supplementary OHLC.
    for path in (tmp_path / "price_ohlc_day_cache").glob("*.parquet"):
        changed = pd.read_parquet(path)
        changed.loc[0, "RawClose"] += 1
        atomic_parquet(path, changed)
        atomic_json(path.with_suffix(".json"), {"version": 1, "sha256": sha256(path)})
    with pytest.raises(RuntimeError, match="3 consecutive"):
        bulk_prices.prepare_bulk_prices(tmp_path, metadata, calendar, "full", {}, source)
    assert originals == {path: sha256(path) for path in originals}


def test_daily_empty_response_retries_without_zero_rows(monkeypatch):
    calls = []
    monkeypatch.setattr(bulk_prices.time, "sleep", lambda *_: None)

    def fetch(*args, **kwargs):
        calls.append(args)
        return pd.DataFrame()

    source = SimpleNamespace(krx=SimpleNamespace(get_market_ohlcv_by_ticker=fetch),
                             _krx_request_timeout=nullcontext)
    with pytest.raises(RuntimeError, match="Empty"):
        bulk_prices.fetch_day(source, pd.Timestamp("2024-01-02"), lambda _: None)
    assert len(calls) == 3


def test_continuous_provider_failure_stops_dates_without_cache(tmp_path, monkeypatch):
    days = pd.bdate_range("2024-01-02", periods=5)
    codes = [f"{n:06d}" for n in range(10)]
    metadata = pd.DataFrame({"Code": codes, "ListingDate": days[0], "DelistingDate": pd.NaT})
    calls, waits = [], []
    monkeypatch.setattr(bulk_prices.time, "sleep", waits.append)

    def fail(day, **kwargs):
        calls.append(day)
        raise RuntimeError("KRX non-JSON response")

    source = SimpleNamespace(krx=SimpleNamespace(get_market_ohlcv_by_ticker=fail),
                             _krx_request_timeout=nullcontext)
    with pytest.raises(RuntimeError, match="3 consecutive"):
        bulk_prices.prepare_bulk_prices(tmp_path, metadata,
            {"trading_days": days.strftime("%Y-%m-%d").tolist()}, "full", {}, source)
    assert calls == [d for d in days[:3].strftime("%Y%m%d") for _ in range(3)]
    assert waits == [5, 15] * 3
    import json

    report = json.loads((tmp_path / "collection_report.json").read_text())
    assert report["status"] == "failed"
    assert report["price_day_progress"]["consecutive_failures"] == 3
    assert not list(tmp_path.glob("price_day_cache/*.parquet"))


def test_failure_history_records_every_attempt_and_survives_rerun(tmp_path, monkeypatch):
    import json

    from core.local_config import append_collection_event
    from data_collectors.price_collector import KrxResponseError

    days = pd.bdate_range("2024-01-02", periods=4)
    codes = [f"{n:06d}" for n in range(10)]
    metadata = pd.DataFrame({"Code": codes, "ListingDate": days[0], "DelistingDate": pd.NaT})
    monkeypatch.setattr(bulk_prices.time, "sleep", lambda *_: None)

    def fail(*args, **kwargs):
        raise KrxResponseError("KRX non-JSON response", http_status=200,
                               content_type="text/html", response_bytes=25, response_kind="non_json")

    source = SimpleNamespace(krx=SimpleNamespace(get_market_ohlcv_by_ticker=fail),
                             _krx_request_timeout=nullcontext)
    for _ in range(2):
        with pytest.raises(RuntimeError, match="3 consecutive"):
            bulk_prices.prepare_bulk_prices(tmp_path, metadata,
                {"trading_days": days.strftime("%Y-%m-%d").tolist()}, "full", {}, source)
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
