"""Small real pipeline: provider mocks, causal inputs, labels, models, evaluation and serving."""
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
from shared.data.prices import fetch_price_window
from shared.features.builder import build_feature_frame
from shared.features.columns import BASE_FEATURES
from shared.io import atomic_json
from shared.settings import BUILDER_ID, processing_contract


def test_collection_training_export_and_serving(tmp_path, monkeypatch):
    days = pd.bdate_range("2019-01-07", periods=230)
    close = 100 + np.sin(np.arange(len(days)) / 4) * 8
    raw = pd.DataFrame({"RawOpen": close - .2, "RawHigh": close + .8, "RawLow": close - .8,
                        "RawClose": close, "RawVolume": 1000., "Amount": close * 1000.}, index=days)
    adjusted = pd.DataFrame({"Open": close, "High": close, "Low": close,
                            "Close": close / 2, "Volume": 1000., "Change": 0.}, index=days)
    adjusted.Change = adjusted.Close.pct_change(fill_method=None).fillna(0)
    monkeypatch.setattr(providers.fdr, "DataReader", lambda *_: adjusted.copy())
    monkeypatch.setattr(providers.krx, "get_market_ohlcv_by_date", lambda *_, **kwargs: raw.copy())
    monkeypatch.setattr(calendar, "get_krx_trading_days", lambda *_: set(days.date))
    monkeypatch.setenv("CHART_SERVING_DATA_DIR", str(tmp_path))
    research = fetch_price_window("005930", days, root=tmp_path / "research", raw=raw)
    operational = prices.fetch_prices("005930", str(days[0].date()), str(days[-1].date()))
    pd.testing.assert_frame_equal(research, operational)
    frame = build_feature_frame(research.assign(Code="005930"), days)
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
                          lgb.Dataset(train[list(BASE_FEATURES)], label=labels.loc[train.index]),
                          num_boost_round=5)
        models[horizon] = tmp_path / f"h{horizon}.txt"
        model.save_model(str(models[horizon]))
        test = frame.loc[eligible].iloc[110:]
        probabilities = model.predict(test[list(BASE_FEATURES)])
        metrics = calculate_classification_metrics(labels.loc[test.index], pd.Series(probabilities[:, 2], index=test.index))
        assert metrics["sample_count"] == len(test) > 0
        predictions[horizon] = tmp_path / f"p{horizon}.parquet"
        pd.DataFrame({"Date": test.Date, "Code": "005930", "fold_id": 0,
                      "prob_up": probabilities[:, 2]}).to_parquet(predictions[horizon], index=False)
    provenance = {"feature_builder_id": BUILDER_ID, "processing_contract": processing_contract(),
                  "models": {f"h{h}": {"labels": {"up_mult": 1.75 if h == 5 else 3.75, "down_mult": 1.5 if h == 5 else 3.0}} for h in (5, 20)},
                  "known_issues": ["Synthetic fixture only."], "validation_status": "synthetic_mock_end_to_end_only",
                  "training_period": {"start": str(frame.Date.iloc[60].date()), "end": str(frame.Date.iloc[160].date())},
                  "data_period": {"start": str(days[0].date()), "end": str(days[-1].date()), "partial_years": []}}
    root, archive, report = build_pack(pack_id="mock_e2e", output=tmp_path / "packs", models=models,
        predictions=predictions, processed_dir=processed, calendar_file=calendar_path, research_manifest=provenance)
    pack, paths = load_pack(root)
    assert archive.is_file() and all(report[f"h{h}"]["sample_rows"] > 0 for h in (5, 20))
    for horizon in (5, 20):
        scores = infer_batch(paths[horizon][0], frame.tail(1))[0][0]
        assert sum(scores.values()) == pytest.approx(1)
    # A changed setting must fail before collection, Storage or publication.
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
