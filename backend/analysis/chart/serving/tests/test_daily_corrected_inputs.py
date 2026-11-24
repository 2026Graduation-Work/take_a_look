import numpy as np
import pandas as pd
import pytest
from serving.internal import flows, pipeline
from serving.internal.features import build_feature_frame
from serving.internal.prices import PriceBasisError, attach_actual_vwap, merge_price_history
from serving.internal.storage import PRICE_COLUMNS, SupabaseStore


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


@pytest.mark.parametrize("archive_mode", ["full_raw", "paired_features", "missing_features"])
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
            from shared.settings import processing_contract
            assert builder == pipeline.BUILDER_ID + "_" + processing_contract()["sha256"][:16]
            assert digest == "a" * 64
            return None if archive_mode == "missing_features" else build_feature_frame(raw, set(dates.date)).tail(1)
        def upload_features(self, *args):
            pytest.fail("Replay wrote feature archive")
        def upload_feature_panel(self, *args):
            pytest.fail("Replay wrote feature panel")
    monkeypatch.setattr(pipeline, "refresh_krx_trading_days", lambda *args: set(dates.date))
    monkeypatch.setattr(pipeline, "collect_flows", lambda *args: pytest.fail("Replay fetched flows"))
    if archive_mode == "missing_features":
        with pytest.raises(ValueError, match="Archived compatible feature input absent"):
            pipeline.collect(dates[-1].date().isoformat(), Store(), replay=True)
    else:
        result = pipeline.collect(dates[-1].date().isoformat(), Store(), replay=True)
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
    result = pipeline.collect(dates[-1].date().isoformat(), Store())
    assert result[2] == ({"000660": "price_source_unavailable"} if provider_failure else {})
    assert requests == [dates[0].date().isoformat() if recently_listed else "2016-01-01"]
    assert result[1]["005930"][1]["flow_foreign_20"] == pytest.approx(.1)
    assert result[-1]["complete_current_rows"] == 1
    assert pd.isna(archived[0].Foreign_BuyAmount.iloc[0])


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
    monkeypatch.setattr(pipeline, "build_snapshot", lambda **kwargs: {"inference": kwargs["inference"]})
    monkeypatch.setattr(pipeline, "unavailable_snapshot", lambda **kwargs: {"inference": {"status": "unavailable", "reason": kwargs["reason"]}})
    monkeypatch.setattr(pipeline, "price_snapshot", lambda *args: {"status": "available", "source": "test", "history": []})
    row = {"Close": 100., "Sigma": .02, "flow_foreign_20": np.nan}
    batch, snapshots = pipeline.build_batch("2024-01-02", pack, {5: ("h5", "s5"), 20: ("h20", "s20")},
        pd.DataFrame({"Code": ["005930"], "Name": ["삼성전자"]}),
        {"005930": (pd.DataFrame(), row, pd.DataFrame())}, {}, {"005930": "c"*64})
    assert calls == [1]
    assert snapshots[0]["inference"]["reason"] == "flow_window_incomplete"
    assert snapshots[1]["inference"]["status"] == "available"
    assert batch["result"]["unavailable_count"] == 1


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
                           "VWAP": values[:-1], "RawClose": values[:-1], "RawVolume": 10., "Amount": 1000.,
                           "AdjustmentFactor": 1.})
    start = dates[-1] - pd.Timedelta(240, unit="D")
    fresh = pd.concat([stored, pd.DataFrame([{**stored.iloc[-1].to_dict(), "Date": dates[-1]}])], ignore_index=True)
    fresh = fresh.loc[fresh.Date >= start].copy()
    # Both an older overlapping row and the last stored row can be revised.
    fresh.loc[fresh.index.isin([fresh.index[0], fresh.index[-2]]), changed_column] += 1
    saved = []
    class Store:
        def save_calendar(self, *args): pass
        def save_universe(self, *args): pass
        def load_price_history(self, code): return stored.copy()
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
    result = pipeline.collect(as_of, Store())
    assert requests == [(start.date().isoformat(), as_of)]
    expected = pd.concat([stored, fresh], ignore_index=True).drop_duplicates("Date", keep="last")
    actual = saved[0].drop(columns="Code")
    pd.testing.assert_frame_equal(actual.reset_index(drop=True), expected.reset_index(drop=True))
    assert len(actual) == 400
    assert not result[2]


@pytest.mark.parametrize(
    ("action_factor", "failure"),
    [(0.2, None), (5., None), (0.98, None), (0.2, "database"), (0.2, "fallback"), (0.2, "storage"), (0.2, "marker")],
)
def test_corporate_action_rebases_saved_history_and_chart_prices(monkeypatch, action_factor, failure):
    code = "005930"
    dates = pd.bdate_range("2023-01-02", periods=600 if failure else 400)
    cutoff = dates[-1] - pd.Timedelta(240, unit="D")
    close = pd.Series(np.arange(len(dates)) + 100., index=dates)
    factor = pd.Series(action_factor, index=dates)
    factor.iloc[-1] = 1.
    volume = np.arange(len(dates)) + 10.
    expected = pd.DataFrame({
        "Open": close - 0.5,
        "High": close + 1.,
        "Low": close - 1.,
        "Close": close,
        "VWAP": close + 0.5,
        "Volume": volume,
        "RawVolume": volume,
        "Change": close.pct_change() * 100,
        "AdjustmentFactor": factor,
    }, index=dates.rename("Date"))
    expected.index.freq = None
    for column in ("Open", "High", "Low", "Close"):
        expected[f"Raw{column}"] = expected[column] / factor
    expected["Amount"] = expected.VWAP / factor * expected.Volume

    adjusted_columns = ["Open", "High", "Low", "Close", "VWAP"]
    stored = expected.iloc[:-1].copy()
    stored[adjusted_columns] = stored[adjusted_columns].div(stored.AdjustmentFactor, axis=0)
    stored["AdjustmentFactor"] = 1.
    fresh = expected.loc[cutoff:].reset_index()
    archive = None
    upserted = {}
    db_requests, storage_requests = [], []

    class Store(SupabaseStore):
        def _request(self, method, path, body=None, **kwargs):
            nonlocal archive
            if method == "GET":
                return archive
            if path.startswith("/rest/v1/chart_prices?"):
                db_requests.append(len(body))
                if failure in {"database", "fallback"} and len(db_requests) == 2:
                    raise RuntimeError("second DB request failed")
                upserted.update({row["trade_date"]: row for row in body})
                return None
            assert path.endswith(f"/raw-history-v3/{code}.parquet")
            storage_requests.append(path)
            if failure == "marker" and len(storage_requests) == 2:
                raise RuntimeError("pending Storage write failed")
            if failure == "storage" and len(storage_requests) == 3:
                raise RuntimeError("final Storage write failed")
            archive = body
            return None

        def save_calendar(self, *args): pass
        def save_universe(self, *args): pass
        def save_raw_price_panel(self, *args): pass
        def upload_feature_panel(self, *args): pass

    store = Store("http://localhost", "test")
    store.save_price_history(code, stored.reset_index())

    universe = pd.DataFrame({"Code": [code], "Name": ["삼성전자"], "ListingDate": [dates[0]]})
    monkeypatch.setattr(pipeline, "refresh_krx_trading_days", lambda *args: set(dates.date))
    monkeypatch.setattr(pipeline, "fetch_universe", lambda *args, **kwargs: universe)
    monkeypatch.setattr(pipeline, "collect_flows", lambda *args: (pd.DataFrame(), {}))
    monkeypatch.setattr(pipeline, "_retry_fetch", lambda *args: fresh.copy())

    as_of = dates[-1].date().isoformat()
    if failure:
        with pytest.raises(RuntimeError, match="request failed|write failed"):
            pipeline.collect(as_of, store)
        rows_written = {"database": 500, "fallback": 500, "storage": 600, "marker": 0}
        assert len(upserted) == rows_written[failure]
        pending_history = store.load_price_history(code)
        pd.testing.assert_frame_equal(pending_history.set_index("Date"), stored)
        assert pending_history.attrs.get("price_rebase_pending", False) is (failure != "marker")
        if failure == "fallback":
            expected = pd.concat([stored, expected.iloc[-1:]])
            fresh = expected.loc[cutoff:].reset_index()

    result = pipeline.collect(as_of, store)

    history = store.load_price_history(code).set_index("Date").sort_index()
    assert "price_rebase_pending" not in history.attrs
    assert "price_rebase_pending" not in result[1][code][0].attrs
    pd.testing.assert_series_equal(history.AdjustmentFactor, expected.AdjustmentFactor)
    pd.testing.assert_series_equal(history.Close.pct_change(), expected.Close.pct_change())
    raw_columns = ["RawOpen", "RawHigh", "RawLow", "RawClose", "RawVolume", "Amount", "Volume"]
    pd.testing.assert_frame_equal(history[raw_columns], expected[raw_columns])
    pd.testing.assert_frame_equal(history[adjusted_columns], expected[adjusted_columns])

    chart_prices = pd.DataFrame(upserted.values()).rename(columns={db: source for source, db in PRICE_COLUMNS.items()})
    chart_prices["Date"] = pd.to_datetime(chart_prices.Date)
    chart_prices = chart_prices.set_index("Date").sort_index()
    basis_columns = [*adjusted_columns, "AdjustmentFactor"]
    pd.testing.assert_frame_equal(chart_prices[basis_columns], expected[basis_columns])
    if failure:
        assert db_requests[-2:] == [500, 100]
    assert len(storage_requests) == 3 + (failure in {"marker", "storage"})

    prior_writes = len(storage_requests)
    pipeline.collect(as_of, store)
    pd.testing.assert_frame_equal(store.load_price_history(code).set_index("Date").sort_index(), history)
    assert db_requests[-1] == len(fresh)
    assert len(storage_requests) == prior_writes + 1


def test_nonuniform_overlap_excludes_only_the_affected_stock(monkeypatch):
    dates = pd.bdate_range("2024-01-02", periods=75)
    close = np.arange(len(dates)) + 100.
    good = pd.DataFrame({"Date": dates, "Open": close, "High": close + 1, "Low": close - 1,
                         "Close": close, "VWAP": close, "Volume": 10., "Amount": close * 10,
                         "AdjustmentFactor": 1.})
    bad = good.copy()
    bad.loc[1, ["AdjustmentFactor", "Open", "High", "Low", "Close", "VWAP"]] *= 0.98
    price_writes = []

    class Store:
        def save_calendar(self, *args): pass
        def save_universe(self, *args): pass
        def load_price_history(self, code): return good.iloc[:-1].copy()
        def save_price_history(self, code, frame): price_writes.append(("storage", code))
        def upsert_prices(self, code, frame): price_writes.append(("database", code))
        def save_raw_prices(self, code, *args): price_writes.append(("snapshot", code))
        def upload_features(self, code, *args): price_writes.append(("features", code))

    universe = pd.DataFrame({"Code": ["000660", "005930"], "Name": ["SK하이닉스", "삼성전자"],
                             "ListingDate": dates[0]})
    sources = {"000660": bad, "005930": good}
    monkeypatch.setattr(pipeline, "refresh_krx_trading_days", lambda *args: set(dates.date))
    monkeypatch.setattr(pipeline, "fetch_universe", lambda *args, **kwargs: universe)
    monkeypatch.setattr(pipeline, "collect_flows", lambda *args: (pd.DataFrame(), {}))
    monkeypatch.setattr(pipeline, "_retry_fetch", lambda code, *args: sources[code].copy())

    _, frames, unavailable, _, _ = pipeline.collect(dates[-1].date().isoformat(), Store())

    assert list(frames) == ["005930"]
    assert unavailable == {"000660": "price_adjustment_basis_inconsistent"}
    assert price_writes == [(target, "005930") for target in ("database", "storage", "snapshot", "features")]


@pytest.mark.parametrize("factor", [0., np.nan, np.inf])
def test_merge_price_history_rejects_invalid_traded_factor(factor):
    previous = pd.DataFrame({"Date": pd.to_datetime(["2024-01-02"]), "Close": [100.],
                             "Volume": [1.], "AdjustmentFactor": [1.]})
    with pytest.raises(PriceBasisError, match="Invalid overlapping adjustment factor"):
        merge_price_history(previous, previous.assign(AdjustmentFactor=factor))


def test_merge_price_history_requires_overlap_with_turnover():
    previous = pd.DataFrame({"Date": pd.to_datetime(["2024-01-02", "2024-01-03"]), "Close": [100., 0.],
                             "Volume": [1., 0.], "AdjustmentFactor": [1., np.nan]})
    fresh = previous.iloc[1:].copy()
    with pytest.raises(PriceBasisError, match="No overlapping observations with turnover"):
        merge_price_history(previous, fresh)


@pytest.mark.parametrize(("factor", "rebased"), [(1.0004, None), (0.2001, 0.2)])
def test_merge_price_history_allows_rounding_and_preserves_halts(factor, rebased):
    dates = pd.bdate_range("2024-01-02", periods=5)
    previous = pd.DataFrame({"Date": dates, "Volume": [0., 1., 1., 1., 0.],
                             "AdjustmentFactor": [np.nan, 1., 1., 1., np.nan]})
    columns = ["Open", "High", "Low", "Close", "VWAP"]
    previous[columns] = 50_000.
    new_ratios = pd.Series([rebased or 1., factor, rebased or 1., np.nan], index=previous.index[1:])
    fresh = previous.iloc[1:].copy()
    fresh[columns] = fresh[columns].mul(new_ratios, axis=0)
    fresh["AdjustmentFactor"] = new_ratios

    merged, ratio = merge_price_history(previous, fresh)

    assert ratio == rebased
    assert merged.Date.tolist() == dates.tolist()
    assert pd.isna(merged.iloc[0].AdjustmentFactor) and pd.isna(merged.iloc[-1].AdjustmentFactor)
    assert merged.iloc[0].Close == 50_000. * (rebased or 1.)


def test_merge_price_history_uses_common_ratio_when_median_is_outside_rounding_bounds():
    dates = pd.bdate_range("2024-01-02", periods=4)
    raw_close = [1000., 1002., 1002., 4000.]
    previous = pd.DataFrame({"Date": dates, "Volume": 1., "AdjustmentFactor": 1.,
                             "RawClose": raw_close})
    columns = ["Open", "High", "Low", "Close", "VWAP"]
    for column in columns:
        previous[column] = raw_close
    fresh = previous.iloc[1:].copy()
    for column in columns:
        fresh[column] = [200., 200., 800.]
    fresh["AdjustmentFactor"] = fresh.Close / fresh.RawClose

    merged, ratio = merge_price_history(previous, fresh)

    assert ratio == pytest.approx(0.2 / 1.00175)
    assert merged.Close.iloc[0] == pytest.approx(1000. * ratio)
    pd.testing.assert_frame_equal(merged.iloc[1:].reset_index(drop=True), fresh.reset_index(drop=True))


def test_merge_price_history_allows_untraded_overlap_when_fresh_replaces_all_rows():
    dates = pd.bdate_range("2024-01-02", periods=2)
    fresh = pd.DataFrame({"Date": dates, "Volume": 0., "Close": 0., "AdjustmentFactor": np.nan})

    merged, ratio = merge_price_history(fresh.iloc[:1], fresh)

    assert ratio is None
    pd.testing.assert_frame_equal(merged, fresh)
