from argparse import Namespace

import pandas as pd
import pytest
from serving import run_daily
from serving.internal import pipeline


@pytest.mark.parametrize("argv", [
    ["--historical-test", "--dry-run"],
    ["--historical-test", "--as-of", "2026-09-21", "--publish"],
    ["--as-of", "2026-09-21", "--code", "005930", "--dry-run"],
])
def test_historical_test_requires_explicit_mode(argv):
    with pytest.raises(SystemExit):
        run_daily.main(argv)


def test_historical_test_fetches_selected_stock_instead_of_replaying(monkeypatch):
    as_of = "2026-09-21"
    monkeypatch.setattr(pipeline, "refresh_krx_trading_days", lambda *_: {pd.Timestamp(as_of).date()})
    def selected_universe(date, code=None):
        assert date == as_of and code == "005930"
        return pd.DataFrame({"Code": [code], "Name": ["삼성전자"]})

    monkeypatch.setattr(pipeline, "fetch_universe", selected_universe)
    monkeypatch.setattr(pipeline, "_retry_fetch", lambda *_: pd.DataFrame(
        {"Date": pd.to_datetime([as_of]), "Close": [100], "Volume": [1000]}))
    monkeypatch.setattr(pipeline, "build_feature_frame", lambda *_: pd.DataFrame(
        {"Date": pd.to_datetime([as_of]), "Sigma": [0.02]}))
    monkeypatch.setattr(pipeline, "collect_flows", lambda *_: (pd.DataFrame(), {}))
    monkeypatch.setattr(pipeline, "frame_hash", lambda *_: "digest")

    class Store:
        def save_universe(self, date, rows):
            raise AssertionError("Historical test must not replace archived universe")

        def load_prices(self, *_):
            raise AssertionError("Historical test must use newly fetched prices")

        def upsert_prices(self, *_):
            pass

        def upload_features(self, *_):
            pass

    universe, frames, unavailable, _, _ = pipeline.collect(as_of, Store(), code="005930", historical_test=True)
    assert universe.Code.tolist() == ["005930"]
    assert list(frames) == ["005930"]
    assert not unavailable


def test_single_stock_universe_skips_full_listing(monkeypatch):
    from pykrx import stock

    monkeypatch.setattr(stock, "get_market_ticker_list", lambda *_args, **_kwargs: pytest.fail("full listing requested"))
    monkeypatch.setattr(stock, "get_market_ticker_name", lambda code: "삼성전자" if code == "005930" else "")
    assert pipeline.fetch_universe("2026-09-21", code="005930").to_dict("records") == [
        {"Code": "005930", "Name": "삼성전자"}]


def test_daily_universe_uses_requested_krx_date(monkeypatch):
    from pykrx import stock

    def listing(date, market):
        assert date == "20260921" and market == "KOSPI"
        return [f"{number:06d}" for number in range(499)] + ["00104K"]

    monkeypatch.setattr(stock, "get_market_ticker_list", listing)
    monkeypatch.setattr(stock, "get_market_ticker_name", lambda code: f"stock-{code}")
    universe = pipeline.fetch_universe("2026-09-21")
    assert len(universe) == 500
    assert "00104K" in set(universe.Code)
    assert "247540" not in set(universe.Code)


def test_historical_test_rejects_remote_supabase(monkeypatch, tmp_path):
    monkeypatch.setenv("CHART_SERVING_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("SUPABASE_URL", "https://production.supabase.co")
    with pytest.raises(ValueError, match="loopback"):
        pipeline.run(Namespace(as_of="2026-09-21", historical_test=True, code="005930", dry_run=True, publish=False))
