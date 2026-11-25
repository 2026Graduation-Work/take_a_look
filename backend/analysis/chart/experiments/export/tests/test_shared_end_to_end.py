import json
import sys
from types import SimpleNamespace

import lightgbm as lgb
import numpy as np
import pandas as pd
import pytest
from experiments.evaluation.metrics import calculate_classification_metrics
from experiments.export.pack import build_pack
from experiments.train_src.labels import apply_dynamic_sigma_barrier_labeling
from serving.internal import calendar, pipeline, prices
from serving.internal.inference import infer_batch
from serving.internal.pack import load_pack
from shared.data import providers
from shared.data.calendar import scheduled_sessions
from shared.data.prices import fetch_price_window
from shared.features.builder import build_feature_frame
from shared.features.columns import BASE_FEATURES, FLOW_FEATURES
from shared.io import atomic_json, sha256
from shared.settings import BUILDER_ID, TRAINING_PRICE_BASIS, processing_contract
from shared.tests.official_fixtures import listing_segment, price_provenance


@pytest.mark.parametrize("with_flows", [False, True])
def test_legacy_krx_price_features_export_and_serving(tmp_path, monkeypatch, with_flows):
    from pykrx.website.krx.market import wrap

    days = scheduled_sessions(pd.Timestamp("2019-01-07"), pd.Timestamp("2020-12-31"))[:230]
    close = 100 + np.sin(np.arange(len(days)) / 4) * 8
    raw = pd.DataFrame({"RawOpen": close - .2, "RawHigh": close + .8, "RawLow": close - .8,
                        "RawClose": close, "RawVolume": 1000., "Amount": close * 1000.}, index=days)
    adjusted = pd.DataFrame({"시가": close, "고가": close, "저가": close,
                             "종가": close / 2, "거래량": 1000.}, index=days)
    adjusted["등락률"] = adjusted["종가"].pct_change(fill_method=None).fillna(0) * 100

    def fetch_adjusted(start, end, code, adjusted_price):
        assert (start, end, code, adjusted_price) == (days[0].strftime("%Y%m%d"), days[-1].strftime("%Y%m%d"), "005930", True)
        return adjusted.copy()

    def fetch_fdr(code, start, end):
        assert (code, start, end) == ("005930", str(days[0].date()), str(days[-1].date()))
        return adjusted.assign(**{"등락률": adjusted["등락률"] / 100}).rename(columns={
            "시가": "Open", "고가": "High", "저가": "Low", "종가": "Close", "거래량": "Volume", "등락률": "Change"
        })

    def fetch_raw(start, end, code, *, adjusted):
        assert adjusted is False
        return raw.copy()

    monkeypatch.setitem(sys.modules, "FinanceDataReader", SimpleNamespace(DataReader=fetch_fdr))
    monkeypatch.setattr(wrap, "get_market_ohlcv_by_date", fetch_adjusted)
    monkeypatch.setattr(providers.krx, "get_market_ohlcv_by_date", fetch_raw)
    monkeypatch.setattr(calendar, "get_krx_trading_days", lambda *_: set(days.date))
    monkeypatch.setenv("CHART_SERVING_DATA_DIR", str(tmp_path))
    legacy = fetch_price_window("005930", days, root=tmp_path / "legacy", raw=raw)
    operational = prices.fetch_prices("005930", str(days[0].date()), str(days[-1].date()))
    assert legacy.PriceProvider.eq("fdr").all()
    assert operational.PriceProvider.eq("pykrx").all()
    pd.testing.assert_frame_equal(legacy.drop(columns="PriceProvider"), operational.drop(columns="PriceProvider"))
    inputs = legacy.assign(Code="005930", SegmentId=listing_segment("005930", str(days[0].date())))
    for investor in ("Individual", "Institution", "Foreign"):
        inputs[f"{investor}_BuyAmount"] = inputs.Amount * .2
        inputs[f"{investor}_SellAmount"] = inputs.Amount * .1
    frame = build_feature_frame(inputs, days)
    names = list(BASE_FEATURES) + (list(FLOW_FEATURES) if with_flows else [])
    processed = tmp_path / "processed"
    processed.mkdir()
    frame.to_parquet(processed / "005930.parquet", index=False)
    calendar_path = tmp_path / "calendar.json"
    atomic_json(calendar_path, {"trading_days": days.astype(str).tolist()})
    models, predictions = {}, {}
    for horizon in (5, 20):
        labels = apply_dynamic_sigma_barrier_labeling(frame, horizon, 1.5, 1.2).map({-1: 0, 0: 1, 1: 2})
        eligible = labels.notna() & frame.Sigma.notna() & frame.roc_60.notna()
        train = frame.loc[eligible].iloc[:90]
        model = lgb.train({"objective": "multiclass", "num_class": 3, "num_threads": 1,
                           "seed": 42, "deterministic": True, "verbosity": -1,
                           "min_data_in_leaf": 5},
                          lgb.Dataset(train[names], label=labels.loc[train.index]),
                          num_boost_round=5)
        models[horizon] = tmp_path / f"h{horizon}.txt"
        model.save_model(str(models[horizon]))
        test = frame.loc[eligible].iloc[110:]
        probabilities = model.predict(test[names])
        metrics = calculate_classification_metrics(labels.loc[test.index], pd.Series(probabilities[:, 2], index=test.index))
        assert metrics["sample_count"] == len(test) > 0
        predictions[horizon] = tmp_path / f"p{horizon}.parquet"
        pd.DataFrame({"Date": test.Date, "Code": "005930", "fold_id": 0,
                      "prob_up": probabilities[:, 2]}).to_parquet(predictions[horizon], index=False)
    proof = price_provenance(tmp_path, ["005930"], pd.DatetimeIndex(days))
    dataset_manifest = tmp_path / "dataset_manifest.json"
    raw_files = {"005930.parquet": sha256(processed / "005930.parquet")}
    atomic_json(dataset_manifest, {**proof, "price_basis": TRAINING_PRICE_BASIS,
                                  "prices_complete": True, "raw_files": raw_files})
    processed_manifest = tmp_path / "processed_manifest.json"
    atomic_json(processed_manifest, {**proof, "files": raw_files, "raw_files": raw_files, "spac_excluded_rows": {},
                                    "dataset_manifest_sha256": sha256(dataset_manifest)})
    provenance = {**proof, "processed_manifest_sha256": sha256(processed_manifest), "feature_builder_id": BUILDER_ID, "processing_contract": processing_contract(),
                  "models": {f"h{h}": {"labels": {"up_mult": 1.75 if h == 5 else 3.75, "down_mult": 1.5 if h == 5 else 3.0}} for h in (5, 20)},
                  "known_issues": ["Synthetic fixture only."], "validation_status": "synthetic_mock_end_to_end_only",
                  "training_period": {"start": str(frame.Date.iloc[60].date()), "end": str(frame.Date.iloc[160].date())},
                  "data_period": {"start": str(days[0].date()), "end": str(days[-1].date()), "partial_years": []}}
    root, archive, report = build_pack(pack_id="mock_e2e", output=tmp_path / "packs", models=models,
        predictions=predictions, processed_dir=processed, calendar_file=calendar_path, research_manifest=provenance)
    dataset = json.loads(dataset_manifest.read_text())
    atomic_json(dataset_manifest, {**dataset, "prices_complete": False, "raw_files": {}})
    with pytest.raises(ValueError, match="Export training price provenance"):
        build_pack(pack_id="stale", output=tmp_path / "packs", models=models, predictions=predictions,
                   processed_dir=processed, calendar_file=calendar_path, research_manifest=provenance)
    assert not (tmp_path / "packs/stale").exists()
    pack, paths = load_pack(root)
    assert archive.is_file() and all(report[f"h{h}"]["sample_rows"] > 0 for h in (5, 20))
    for horizon in (5, 20):
        assert lgb.Booster(model_file=str(paths[horizon][0])).feature_name() == names
        scores = infer_batch(paths[horizon][0], frame.tail(1))[0][0]
        assert sum(scores.values()) == pytest.approx(1)
    pack["processing_contract"]["preprocessing"]["sigma_window"] = 21
    atomic_json(root / "manifest.json", pack)
    with pytest.raises(ValueError, match="checksum mismatch"):
        load_pack(root)
    config = tmp_path / "config.yaml"
    config.write_text("active_pack:\n  pack_id: mock_e2e\n")
    monkeypatch.setattr(pipeline, "config_path", lambda: config)
    monkeypatch.setattr(pipeline, "SupabaseStore", lambda: pytest.fail("Mismatched pack contacted storage"))
    with pytest.raises(ValueError, match="checksum mismatch"):
        pipeline.run(SimpleNamespace(as_of="2019-12-30", dry_run=True, publish=False))
