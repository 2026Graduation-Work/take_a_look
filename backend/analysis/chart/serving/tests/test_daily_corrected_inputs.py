import numpy as np
import pandas as pd
import pytest
from serving.internal import flows, pipeline
from serving.internal.features import build_feature_frame
from serving.internal.prices import attach_actual_vwap
from shared.io import canonical_hash
from shared.settings import serving_contract

GOLDEN_SHA256 = "b" * 64
PACK = {"processing_contract": {"sha256": "c" * 64}}


def test_uniform_raw_ohlc_and_outside_range_vwap():
    dates = pd.to_datetime(["2024-01-02"])
    adjusted = pd.DataFrame({"Close": [41310], "High": [41309], "Volume": [1]}, index=dates)
    raw = pd.DataFrame({"시가": [80000], "고가": [82620], "저가": [79000],
                        "종가": [82620], "거래량": [2], "거래대금": [180000]}, index=dates)
    result = attach_actual_vwap(adjusted, raw).iloc[0]
    assert result.High == result.Close == 41310
    assert result.Open == 40000 and result.Volume == 2
    assert result.VWAP == 45000 > result.High


def test_flow_windows_keep_missing_market_sessions():
    days = pd.bdate_range("2024-01-02", periods=75)
    raw = pd.DataFrame({"Date": days, "Code": "005930", "Close": np.arange(75) + 100.,
                        "Open": np.arange(75) + 100., "High": np.arange(75) + 101.,
                        "Low": np.arange(75) + 99., "Volume": 100., "VWAP": np.arange(75) + 100.,
                        "Amount": 10000.})
    for investor in ("Individual", "Institution", "Foreign"):
        raw[f"{investor}_BuyAmount"] = 1200.
        raw[f"{investor}_SellAmount"] = 200.
    full = build_feature_frame(raw, set(days.date))
    assert full.iloc[-1].flow_foreign_20 == pytest.approx(.1)
    raw.loc[70, "Foreign_BuyAmount"] = np.nan
    missing = build_feature_frame(raw, set(days.date))
    assert pd.isna(missing.iloc[-1].flow_foreign_5)
    assert pd.isna(missing.iloc[-1].flow_foreign_20)
    assert missing.iloc[-1].flow_foreign_1 == pytest.approx(.1)
    pd.testing.assert_frame_equal(missing.iloc[:70], build_feature_frame(raw.iloc[:70], set(days[:70].date)))


def test_daily_cache_and_query_failure_are_separate(monkeypatch, tmp_path):
    days = pd.to_datetime(["2024-01-02", "2024-01-03"])
    frame = pd.DataFrame({"Date": [days[0]], "Code": ["005930"],
                          **{c: [1] for c in flows._FLOW_COLUMNS}})
    frame["Institution_BuyAmount"] = pd.NA
    class Store:
        def load_flow_day(self, day):
            return frame if day == "2024-01-02" else None
        def save_flow_day(self, day, value):
            assert day == "2024-01-02"
    monkeypatch.setattr(flows, "_fetch_investor_day", lambda day: (_ for _ in ()).throw(TimeoutError()))
    merged, report = flows.collect_flows(set(days.date), Store())
    assert report["cached_days"] == 1 and report["available_days"] == 1
    assert report["failed_days"] == [{"date": "2024-01-03", "error_type": "TimeoutError"}]
    assert pd.isna(merged.Institution_BuyAmount.iloc[0])


@pytest.mark.parametrize("archive_mode", ["full_raw", "paired_features", "legacy_features", "missing_features"])
def test_replay_uses_archive_without_network(monkeypatch, archive_mode):
    dates = pd.bdate_range("2024-01-02", periods=75)
    raw = pd.DataFrame({"Date": dates, "Code": "005930", "Open": np.arange(75)+100.,
                        "High": np.arange(75)+101., "Low": np.arange(75)+99.,
                        "Close": np.arange(75)+100., "Volume": 10., "VWAP": np.arange(75)+100.})
    class Store:
        def load_calendar(self, day):
            return set(dates.date)
        def load_universe(self, day):
            return pd.DataFrame({"Code": ["005930"], "Name": ["삼성전자"]})
        def load_raw_prices(self, code, day):
            if archive_mode == "full_raw":
                return raw
            saved = raw.tail(60).copy()
            saved.attrs["input_sha256"] = "a" * 64
            return saved
        def load_features(self, code, day, builder, digest):
            key = canonical_hash({**serving_contract(), "golden_sha256": GOLDEN_SHA256})
            assert digest == "a" * 64
            if builder == pipeline.BUILDER_ID + "_" + key[:16]:
                if archive_mode != "paired_features":
                    return None
            else:
                assert builder == pipeline.BUILDER_ID + "_" + PACK["processing_contract"]["sha256"][:16]
                if archive_mode != "legacy_features":
                    return None
            return build_feature_frame(raw, set(dates.date)).tail(1)
        def upload_features(self, *args):
            pytest.fail("Replay wrote feature archive")
        def upload_feature_panel(self, *args):
            pytest.fail("Replay wrote feature panel")
    monkeypatch.setattr(pipeline, "refresh_krx_trading_days", lambda *args: set(dates.date))
    monkeypatch.setattr(pipeline, "collect_flows", lambda *args: pytest.fail("Replay fetched flows"))
    if archive_mode == "missing_features":
        with pytest.raises(ValueError, match="Archived compatible feature input absent"):
            pipeline.collect(dates[-1].date().isoformat(), Store(), pack=PACK, golden_sha256=GOLDEN_SHA256, replay=True)
    else:
        result = pipeline.collect(dates[-1].date().isoformat(), Store(), pack=PACK, golden_sha256=GOLDEN_SHA256, replay=True)
        assert list(result[1]) == ["005930"]


@pytest.mark.parametrize("provider_failure", [False, True])
@pytest.mark.parametrize("recently_listed", [False, True])
def test_live_collect_joins_recent_flows_and_archives_history(monkeypatch, provider_failure, recently_listed):
    dates = pd.bdate_range("2024-01-02", periods=75)
    raw = pd.DataFrame({"Date": dates, "Open": np.arange(75)+100., "High": np.arange(75)+101.,
                        "Low": np.arange(75)+99., "Close": np.arange(75)+100., "Volume": 10.,
                        "VWAP": np.arange(75)+100., "Amount": 1000.})
    flow = pd.DataFrame({"Date": dates[-20:], "Code": "005930"})
    for investor in ("Individual", "Institution", "Foreign"):
        flow[f"{investor}_BuyAmount"] = 200.
        flow[f"{investor}_SellAmount"] = 100.
    archived = []
    class Store:
        def save_calendar(self, *args):
            pass
        def save_universe(self, *args):
            pass
        def load_price_history(self, code):
            return None
        def upsert_prices(self, *args):
            pass
        def save_price_history(self, code, frame):
            archived.append(frame.copy())
        def save_raw_prices(self, *args):
            pass
        def upload_features(self, *args):
            pass
    monkeypatch.setattr(pipeline, "refresh_krx_trading_days", lambda *args: set(dates.date))
    universe = pd.DataFrame({"Code": ["005930", "000660"], "Name": ["삼성전자", "SK하이닉스"]}) if provider_failure else pd.DataFrame({"Code": ["005930"], "Name": ["삼성전자"]})
    universe["ListingDate"] = dates[0] if recently_listed else pd.Timestamp("2000-01-01")
    monkeypatch.setattr(pipeline, "fetch_universe", lambda *args, **kwargs: universe)
    monkeypatch.setattr(pipeline, "collect_flows", lambda *args: (flow, {"available_days": 20}))
    requests = []
    def fetch(code, start, end):
        if code == "000660":
            raise ValueError("Price providers exhausted: mocked missing provider inputs")
        requests.append(start)
        return raw.copy()
    monkeypatch.setattr(pipeline, "_retry_fetch", fetch)
    result = pipeline.collect(dates[-1].date().isoformat(), Store(), pack=PACK, golden_sha256=GOLDEN_SHA256)
    assert result[2] == ({"000660": "price_source_unavailable"} if provider_failure else {})
    assert requests == [dates[0].date().isoformat() if recently_listed else "2016-01-01"]
    assert result[1]["005930"][1]["flow_foreign_20"] == pytest.approx(.1)
    assert result[-1]["complete_current_rows"] == 1
    assert pd.isna(archived[0].Foreign_BuyAmount.iloc[0])
    assert archived[0].attrs[pipeline.VERIFIED_PRICE_FROM] == dates[0].date().isoformat()


def test_flow_missing_only_blocks_model_that_requires_it(monkeypatch):
    pack = {"pack_id": "test", "feature_builder_id": "builder", "horizons": {
        f"h{h}": {"model_sha256": "a"*64, "samples_sha256": "b"*64,
                   "label_barriers": {"up_mult": 1.5, "down_mult": 1.2}}
        for h in (5, 20)}}
    class Model:
        def __init__(self, model_file):
            self.flow = model_file == "h5"
        def feature_name(self):
            return ["flow_foreign_20"] if self.flow else ["Close"]
    class History:
        def __init__(self, *args):
            pass
        def distribution(self, **kwargs):
            return {}
    calls = []
    monkeypatch.setattr(pipeline.lgb, "Booster", Model)
    monkeypatch.setattr(pipeline.pd, "read_parquet", lambda *args: pd.DataFrame())
    monkeypatch.setattr(pipeline, "SampleIndex", History)
    def infer(model, frame):
        calls.append(len(frame))
        return [({"up": .4, "down": .3, "neutral": .3}, [], "a"*64, 0.)]
    monkeypatch.setattr(pipeline, "infer_batch", infer)
    monkeypatch.setattr(pipeline, "build_snapshot", lambda **kwargs: {
        "inference": kwargs["inference"], "prices": kwargs["prices"]})
    monkeypatch.setattr(pipeline, "unavailable_snapshot", lambda **kwargs: {
        "inference": {"status": "unavailable", "reason": kwargs["reason"]}, "prices": kwargs["prices"]})
    row = {"Close": 100., "Sigma": .02, "flow_foreign_20": np.nan}
    days = pd.bdate_range(end="2024-01-02", periods=61)
    source = pd.DataFrame({"Date": days, "Close": np.arange(61) + 100., "Volume": 100.})
    digest = "c"*64
    prices = pipeline.price_snapshot(source, "2024-01-02", days, digest)
    universe = pd.DataFrame({"Code": ["005930"], "Name": ["삼성전자"]})
    paths = {5: ("h5", "s5"), 20: ("h20", "s20")}
    batch, snapshots = pipeline.build_batch("2024-01-02", pack, paths, universe,
        {"005930": (prices, row, pd.DataFrame())}, {}, {"005930": digest})
    assert calls == [1]
    assert snapshots[0]["inference"]["reason"] == "flow_window_incomplete"
    assert snapshots[1]["inference"]["status"] == "available"
    assert batch["result"]["unavailable_count"] == 1
    assert snapshots[0]["prices"] == snapshots[1]["prices"] == prices
    assert len(prices["history"]) == 60 and "event_basis" in prices
    legacy = {key: value for key, value in prices.items() if key != "event_basis"}
    replay, _ = pipeline.build_batch("2024-01-02", pack, paths, universe,
        {"005930": (legacy, row, pd.DataFrame())}, {}, {"005930": digest})
    assert batch["id"] != replay["id"]


def test_kospi_preferred_alphanumeric_code_is_supported(monkeypatch, verified_listing_provider):
    from serving.internal import calendar
    from shared.data.providers import krx as stock
    monkeypatch.setattr(calendar, "get_krx_trading_days", lambda *_: {pd.Timestamp("2026-10-06").date()})
    monkeypatch.setattr(flows, "_fetch_investor_day", lambda *_: pytest.fail("unexpected flow query"))
    from serving.internal.prices import fetch_prices

    monkeypatch.setattr(stock, "get_market_ticker_name", lambda code: "한화3우B")
    assert pipeline.fetch_universe("2026-10-06", code="00088K").Code.iloc[0] == "00088K"
    source = pd.DataFrame({"시가": [100], "고가": [101], "저가": [99], "종가": [100],
                           "거래량": [10], "거래대금": [1000], "등락률": [0]},
                          index=pd.to_datetime(["2026-10-06"]))
    monkeypatch.setattr(stock, "get_market_ohlcv_by_date", lambda *args, **kwargs: source.copy())
    from shared.data import providers
    monkeypatch.setattr(providers.fdr, "DataReader", lambda *_: pd.DataFrame())
    monkeypatch.setattr(providers.time, "sleep", lambda *_: None)
    assert fetch_prices("00088K", "2026-10-06", "2026-10-06").Close.iloc[0] == 100


@pytest.mark.parametrize("listing", [None, pd.NaT, "2026-10-07"])
def test_current_universe_rejects_unknown_or_future_listing(monkeypatch, tmp_path, listing):
    from shared.data import metadata
    monkeypatch.setattr(metadata, "load_metadata", lambda *args: pd.DataFrame({
        "Code": ["005930"], "ListingDate": [listing]}))
    with pytest.raises(ValueError, match="listing intervals"):
        metadata.fetch_current_universe("2026-10-06", root=tmp_path, code="005930")


def test_price_reads_retry_krx_html_but_do_not_hide_contract_failures(monkeypatch):
    calls, delays = [], []
    def fetch(*args):
        calls.append(args)
        if len(calls) < 3:
            raise pipeline.KrxResponseError("HTTP 200 non-JSON")
        return "confirmed"
    monkeypatch.setattr(pipeline, "fetch_prices", fetch)
    monkeypatch.setattr(pipeline.time, "sleep", delays.append)
    assert pipeline._retry_fetch("005930", "2016-01-01", "2026-10-13") == "confirmed"
    assert delays == [10, 20]
    def broken(*args):
        raise pipeline.KrxResponseError("permanent outage")
    monkeypatch.setattr(pipeline, "fetch_prices", broken)
    with pytest.raises(pipeline.KrxResponseError):
        pipeline._retry_fetch("005930", "2016-01-01", "2026-10-13")
    delays.clear()
    def invalid(*args):
        raise ValueError("calendar contract")
    monkeypatch.setattr(pipeline, "fetch_prices", invalid)
    with pytest.raises(ValueError, match="calendar contract"):
        pipeline._retry_fetch("005930", "2016-01-01", "2026-10-13")
    assert delays == []


@pytest.mark.parametrize("changed_column", ["Close", "RawClose", "RawVolume", "Amount"])
def test_source_revision_merges_recent_rows_without_full_refetch(monkeypatch, changed_column):
    dates = pd.bdate_range("2023-01-02", periods=400)
    values = np.arange(len(dates)) + 100.
    stored = pd.DataFrame({"Date": dates[:-1], "Open": values[:-1], "High": values[:-1]+1,
                           "Low": values[:-1]-1, "Close": values[:-1], "Volume": 10.,
                           "VWAP": values[:-1], "RawClose": values[:-1], "RawVolume": 10., "Amount": 1000.})
    stored.attrs[pipeline.VERIFIED_PRICE_FROM] = dates[0].date().isoformat()
    start = dates[-1] - pd.Timedelta(240, unit="D")
    fresh = pd.concat([stored, pd.DataFrame([{**stored.iloc[-1].to_dict(), "Date": dates[-1]}])], ignore_index=True)
    fresh = fresh.loc[fresh.Date >= start].copy()
    # Both an older overlapping row and the last stored row can be revised.
    fresh.loc[fresh.index.isin([fresh.index[0], fresh.index[-2]]), changed_column] += 1
    saved = []
    class Store:
        def save_calendar(self, *args): pass
        def save_universe(self, *args): pass
        def load_price_history(self, code): return (saved[-1] if saved else stored).copy()
        def upsert_prices(self, code, frame):
            assert frame.Date.min() >= start
        def save_price_history(self, code, frame): saved.append(frame.copy())
        def save_raw_prices(self, *args): pass
        def upload_features(self, *args): pass
    monkeypatch.setattr(pipeline, "refresh_krx_trading_days", lambda *args: set(dates.date))
    universe = pd.DataFrame({"Code": ["005930"], "Name": ["삼성전자"], "ListingDate": pd.Timestamp("2000-01-01")})
    monkeypatch.setattr(pipeline, "fetch_universe", lambda *args, **kwargs: universe)
    monkeypatch.setattr(pipeline, "collect_flows", lambda *args: (pd.DataFrame(), {}))
    requests = []
    def fetch(code, first, last):
        requests.append((first, last))
        return fresh.copy()
    monkeypatch.setattr(pipeline, "_retry_fetch", fetch)
    as_of = dates[-1].date().isoformat()
    result = pipeline.collect(as_of, Store(), pack=PACK, golden_sha256=GOLDEN_SHA256)
    assert requests == [(start.date().isoformat(), as_of)]
    expected = pd.concat([stored, fresh], ignore_index=True).drop_duplicates("Date", keep="last")
    actual = saved[0].drop(columns="Code")
    pd.testing.assert_frame_equal(actual.reset_index(drop=True), expected.reset_index(drop=True))
    assert len(actual) == 400
    assert not result[2]
    event = result[1]["005930"][0]["event_basis"]
    assert event["return_count"] == (len(fresh) - 1 if changed_column == "Close" else 250)
    assert saved[0].attrs[pipeline.VERIFIED_PRICE_FROM] == (
        fresh.Date.min().date().isoformat() if changed_column == "Close" else dates[0].date().isoformat()
    )
    rerun = pipeline.collect(as_of, Store(), pack=PACK, golden_sha256=GOLDEN_SHA256)
    assert rerun[1]["005930"][0] == result[1]["005930"][0]
    assert rerun[3] == result[3]


def test_legacy_adjustment_prefix_stays_out_of_basis_across_daily_runs(monkeypatch):
    dates = pd.bdate_range("2024-01-02", periods=285)
    close = 100 * np.exp(np.cumsum(np.sin(np.arange(len(dates))) / 100))
    adjusted = pd.DataFrame({"Date": dates, "Close": close, "Volume": 100.})
    cached = adjusted.iloc[:-2].copy()
    cached.loc[cached.Date < dates[-3] - pd.Timedelta(245, unit="D"), "Close"] *= 2
    saved, requests = [], []

    class Store:
        def save_calendar(self, *args): pass
        def save_universe(self, *args): pass
        def upsert_prices(self, *args): pass
        def upload_features(self, *args): pass
        def save_raw_prices(self, *args): pass
        def load_price_history(self, code): return saved[-1].copy() if saved else cached.copy()
        def save_price_history(self, code, frame): saved.append(frame.copy())

    def provider(code, start, end):
        requests.append((start, end))
        return adjusted.loc[adjusted.Date.between(start, end)].copy()

    def compute_row(raw, days):
        return raw.tail(1).assign(Sigma=.02)

    monkeypatch.setattr(pipeline, "refresh_krx_trading_days", lambda start, end: set(dates[dates <= end].date))
    monkeypatch.setattr(pipeline, "fetch_universe", lambda *args, **kwargs: pd.DataFrame({
        "Code": ["005930"], "Name": ["가상종목"], "ListingDate": dates[0],
    }))
    monkeypatch.setattr(pipeline, "_retry_fetch", provider)
    monkeypatch.setattr(pipeline, "collect_flows", lambda *args: (pd.DataFrame(), {}))
    monkeypatch.setattr(pipeline, "build_feature_frame", compute_row)
    events = []
    for day in dates[-2:]:
        as_of = day.date().isoformat()
        result = pipeline.collect(as_of, Store(), pack=PACK, golden_sha256=GOLDEN_SHA256)
        assert not result[2]
        events.append(result[1]["005930"][0]["event_basis"])

    first_verified_date = saved[0].attrs[pipeline.VERIFIED_PRICE_FROM]
    assert first_verified_date == saved[1].attrs[pipeline.VERIFIED_PRICE_FROM]
    for event in events:
        fresh = adjusted.loc[adjusted.Date.between(first_verified_date, event["period_end"])]
        assert event["return_count"] == len(fresh) - 1 < 250
        assert event["daily_sigma"] == pytest.approx(np.log(fresh.Close).diff().std(ddof=1))
        assert event["period_start"] == fresh.Date.iloc[1].date().isoformat()
    assert len(requests) == 2
    assert saved[1].Close.iloc[0] == close[0] * 2
