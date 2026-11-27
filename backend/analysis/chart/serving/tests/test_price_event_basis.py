import json
from datetime import timedelta

import numpy as np
import pandas as pd
import pytest
from serving.internal.prices import price_snapshot
from serving.internal.snapshot import unavailable_snapshot
from serving.internal.storage import SupabaseStore

DIGEST = "a" * 64


@pytest.fixture
def prices():
    dates = pd.bdate_range("2024-01-02", periods=280)
    close = 100 * np.exp(np.cumsum(np.sin(np.arange(len(dates))) / 100))
    return pd.DataFrame({
        "Date": dates, "Close": close, "RawClose": np.where(np.arange(len(dates)) < 250, close * 2, close),
        "Volume": np.where(np.arange(len(dates)) == 219, 0, 100),
    })


def export(frame, expected, **kwargs):
    return price_snapshot(frame, expected[-1].date().isoformat(), expected, DIGEST, **kwargs)


def test_price_event_basis_uses_one_extra_price_and_same_risk_definition(prices):
    from serving.stock_master import classify

    dates = pd.DatetimeIndex(prices.Date)
    payload = export(prices, dates)
    basis = payload["event_basis"]
    assert [bar["date"] for bar in payload["history"]] == dates[-60:].strftime("%Y-%m-%d").tolist()
    assert basis["previous_bar"] == {
        "date": dates[-61].date().isoformat(), "close": prices.Close.iloc[-61], "volume": 0,
    }
    assert basis["previous_bar"]["close"] != prices.RawClose.iloc[-61]
    assert basis["period_start"] == dates[-250].date().isoformat()
    assert basis["period_end"] == dates[-1].date().isoformat()
    assert basis["return_count"] == 250
    assert basis["input_sha256"] == DIGEST
    assert basis["daily_sigma"] == pytest.approx(np.log(prices.Close).diff().tail(250).std(ddof=1))
    universe = pd.DataFrame({"Code": ["005930"], "Name": ["Example"]})
    master = classify(universe, prices.assign(Code="005930", Amount=1000), set())
    assert round(basis["daily_sigma"] * np.sqrt(252), 4) == master[0]["volatility_annual"]
    valid = unavailable_snapshot(
        code="005930", stock_name="Example", as_of=basis["period_end"], horizon=5, pack_id="preview",
        batch_id="b" * 64, reason="flow_window_incomplete", prices=payload, prices_sha256=DIGEST,
    )
    assert valid["prices"] == payload
    with pytest.raises(ValueError, match="disagrees"):
        unavailable_snapshot(
            code="005930", stock_name="Example", as_of=basis["period_end"], horizon=5, pack_id="preview",
            batch_id="b" * 64, reason="flow_window_incomplete", prices=payload, prices_sha256="b" * 64,
        )


@pytest.mark.parametrize("count, available", [(60, False), (61, True)])
def test_minimum_60_returns(prices, count, available):
    prices = prices.tail(count)
    dates = pd.DatetimeIndex(prices.Date)
    assert ("event_basis" in export(prices, dates)) is available


def test_older_gap_preserves_chart_and_visible_gap_fails(prices):
    dates = pd.DatetimeIndex(prices.Date)
    for index in (100, 219):
        partial = export(prices.drop(index), dates)
        assert len(partial["history"]) == 60 and "event_basis" not in partial
    for malformed in (
        prices.drop(279), prices.drop(230), pd.concat([prices, prices.tail(1)]), prices.iloc[::-1],
        pd.concat([prices, prices.tail(1).assign(Date=dates[-1].date() + timedelta(days=1))]),
        prices.assign(Close=prices.Close.mask(prices.index == 279)),
    ):
        with pytest.raises(ValueError):
            export(malformed, dates)
    assert "event_basis" not in export(prices.assign(Close=100), dates)
    assert "event_basis" not in export(prices.assign(Close=prices.Close.mask(prices.index == 100)), dates)


@pytest.mark.parametrize("mode", ["panel", "individual"])
def test_verified_archive_roundtrip_and_metadata_tampering(monkeypatch, prices, mode):
    store = SupabaseStore("https://example.test", "secret")
    objects = {}

    def request(method, path, body=None, **options):
        path = path.replace("/authenticated/", "/")
        if method == "POST":
            objects[path] = body
        elif path not in objects:
            raise FileNotFoundError(path)
        else:
            return objects[path]

    monkeypatch.setattr(store, "_request", request)
    dates = pd.DatetimeIndex(prices.Date)
    as_of = dates[-1].date().isoformat()
    original = export(prices, dates)
    frame = prices.tail(61).copy()
    frame.attrs.update(input_sha256=DIGEST, event_basis=original["event_basis"])
    prefix = f"/storage/v1/object/chart-features/raw-prices-v3/{as_of}/"
    if mode == "panel":
        store.save_raw_price_panel(as_of, {"005930": frame, "000660": frame})
        stem = prefix + "batch"
    else:
        store.save_raw_prices("005930", as_of, frame)
        stem = prefix + "005930"
    key = stem + ".manifest.json"
    manifest_bytes = objects[key]

    def read():
        store._raw_price_frames.clear()
        return store.load_raw_prices("005930", as_of)

    assert export(read(), dates, replay=True) == original
    for damage in ("basis", "stock_code", "as_of", "bars_sha256", "input_sha256"):
        manifest = json.loads(manifest_bytes)
        record = manifest["event_bases"]["005930"] if mode == "panel" else manifest["event_basis"]
        if damage == "basis":
            record["basis"]["daily_sigma"] *= 3
        elif mode == "panel" and damage == "stock_code":
            manifest["event_bases"]["005930"] = manifest["event_bases"]["000660"]
        else:
            record[damage] = "invalid"
        objects[key] = json.dumps(manifest).encode()
        fallback = export(read(), dates, replay=True)
        assert fallback["history"] == original["history"]
        assert "event_basis" not in fallback
    if mode == "panel":
        legacy = json.loads(manifest_bytes)
        del legacy["event_bases"]
        objects[key] = json.dumps(legacy).encode()
        assert "event_basis" not in export(read().tail(60), dates, replay=True)
    objects[key] = manifest_bytes
    objects[stem + ".parquet"] += b"corrupt"
    with pytest.raises(ValueError, match="checksum|magic"):
        read()
