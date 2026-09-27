import copy
import json
from pathlib import Path

import pandas as pd
import pytest
from serving.contracts import validate_snapshot
from serving.persistence import SupabaseStore
from serving.publish import _pack_releases
from serving.snapshot import unavailable_snapshot


def v2_snapshot():
    value = json.loads((Path(__file__).parents[1] / "contracts/examples/normal.json").read_text())
    value["contract"] = "chart_signal_detail_v2"
    value["pack_id"] = "pack-1"
    del value["cases"]
    value["distribution"] = {
        "status": "available", "reason": None,
        "policy_id": "multi_stock_up_sigma_001_005_v1",
        "current": {"up": value["inference"]["scores"]["up"],
                    "sigma": value["inference"]["sigma"]},
        "tolerances": {"up_absolute": 0.01, "sigma_relative": 0.05},
        "sample_count": 1, "stock_count": 1,
        "period_start": "2024-01-01", "period_end": "2024-01-01",
        "observed_through": "2024-02-01", "by_fold": {"fold-1": 1},
        "histogram": {"bins": [{"left": -2, "right": 0, "count": 1}],
                      "central_68": {"low": -1, "high": -1}},
    }
    return value


def test_v2_one_case_and_partition_guard():
    value = v2_snapshot()
    assert validate_snapshot(value) is value
    bad = copy.deepcopy(value)
    bad["distribution"]["sample_count"] = 2
    with pytest.raises(ValueError, match="Histogram counts"):
        validate_snapshot(bad)


def test_feature_metadata_waits_for_upload(monkeypatch):
    store = SupabaseStore("https://example.supabase.co", "secret")
    calls = []

    def fail_upload(method, path, body=None, **kwargs):
        calls.append(path)
        raise RuntimeError("storage failed")

    monkeypatch.setattr(store, "_request", fail_upload)
    frame = pd.DataFrame({"Date": pd.to_datetime(["2024-01-01"]), "Sigma": [0.1]})
    with pytest.raises(RuntimeError, match="storage failed"):
        store.upload_features("005930", "2024-01-01", "builder-1", "a" * 64, frame)
    assert len(calls) == 1 and calls[0].startswith("/storage/")


def test_price_upsert_uses_stock_day_key(monkeypatch):
    store = SupabaseStore("https://example.supabase.co", "secret")
    seen = []
    monkeypatch.setattr(store, "_request", lambda *args, **kwargs: seen.append((args, kwargs)))
    frame = pd.DataFrame([{source: pd.Timestamp("2024-01-01") if source == "Date" else 1
                           for source in ("Date", "Open", "High", "Low", "Close", "Volume",
                                          "VWAP", "Change", "RawClose", "RawVolume", "Amount",
                                          "AdjustmentFactor")}])
    store.upsert_prices("005930", frame)
    assert "on_conflict=stock_code,trade_date" in seen[0][0][1]
    assert seen[0][0][2][0]["stock_code"] == "005930"


def test_pack_release_pair_and_unavailable_snapshot():
    manifest = {"pack_id": "pack-1", "feature_builder_id": "builder-1",
                "horizons": {key: {"horizon": horizon,
                                   "profile": "aggressive" if horizon == 5 else "stable",
                                   "model_sha256": "a" * 64,
                                   "samples_sha256": "b" * 64,
                                   "feature_names": ["Close"]}
                             for key, horizon in (("h5", 5), ("h20", 20))}}
    releases = _pack_releases(manifest)
    assert [item["release_id"] for item in releases] == ["pack-1:h5", "pack-1:h20"]
    value = unavailable_snapshot(code="005930", stock_name="삼성전자", as_of="2024-01-01",
                                 horizon=5, pack_id="pack-1", batch_id="batch", reason="no_prices")
    assert value["distribution"]["status"] == "unavailable"
