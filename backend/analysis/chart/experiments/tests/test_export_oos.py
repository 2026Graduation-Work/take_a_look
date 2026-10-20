import copy
import json

import numpy as np
import pandas as pd
import pytest
from experiments.export_oos import attach_outcomes, export, outcomes
from experiments.features.psychology.market_psychology import RAW_FEATURES
from shared.io import sha256
from shared.settings import BASE_FEATURES, FLOW_FEATURES


def prices(count=60):
    return pd.DataFrame({"Date": pd.bdate_range("2019-01-07", periods=count),
                         "Code": "00088K", "High": np.arange(count) + 101.,
                         "Close": np.arange(count) + 100., "Sigma": .02, "Trading_Halt": 0})


def labels(horizon):
    return {"type": "dynamic_sigma", "horizon": horizon, "up_mult": 1.75, "down_mult": 1.5}


def test_return_uses_h_non_halted_sessions_not_filtered_prediction_rows():
    frame = prices(9)
    frame.loc[1:2, "Trading_Halt"] = 1
    result = outcomes(frame.iloc[::-1], labels(2))
    assert result.loc[0, "forward_return"] == pytest.approx(.04)
    assert result.loc[0, "return_date"] == frame.loc[4, "Date"]
    assert pd.isna(result.loc[1, "forward_return"])
    assert result.tail(2).forward_return.isna().all()
    frame.loc[1:6, "Trading_Halt"] = 1
    assert pd.isna(outcomes(frame, labels(2)).loc[0, "forward_return"])


def test_outcome_join_rejects_missing_dates_changed_labels_and_duplicates():
    frame = prices()
    expected = outcomes(frame, labels(5))
    predictions = expected[["Date", "Y_Label"]].copy()
    predictions["label_observed"] = predictions.Y_Label.notna()
    assert len(attach_outcomes(predictions, frame, labels(5))) == len(frame)
    predictions.loc[0, "Y_Label"] = 0
    with pytest.raises(ValueError, match="labels differ"):
        attach_outcomes(predictions, frame, labels(5))
    with pytest.raises(ValueError, match="dates are missing"):
        attach_outcomes(predictions.iloc[-1:], frame.iloc[:-1], labels(5))
    with pytest.raises(ValueError, match="duplicate price"):
        outcomes(pd.concat([frame, frame.iloc[:1]]), labels(5))


def completed_suite(tmp_path):
    suite = tmp_path / "suite"
    suite.mkdir()
    feature_root = tmp_path / "features"
    feature_root.mkdir()
    frame = prices()
    path = feature_root / "00088K.parquet"
    frame.to_parquet(path, index=False)
    columns = list(BASE_FEATURES) + list(FLOW_FEATURES)
    feature_manifest = feature_root / "feature_manifest.json"
    feature_manifest.write_text(json.dumps({"feature_columns": columns + list(RAW_FEATURES),
                                           "file_hashes": {path.name: sha256(path)}}))
    pinned = {"run_id": "completed", "run_manifest_sha256": {},
              "sigma_feature_manifest_sha256": sha256(feature_manifest)}
    status = {"run_id": "completed", "status": "complete", "completed": {}}
    for h in (5, 20):
        prediction = outcomes(frame, labels(h))[["Date", "Y_Label"]]
        prediction["Code"] = "00088K"
        prediction["label_observed"] = prediction.Y_Label.notna()
        prediction["fold_id"] = 0
        prediction["Prob"] = prediction["prob_up"] = .5
        prediction["prob_down"], prediction["prob_neutral"] = .2, .3
        config = {key: {} for key in ("model", "strategy", "backtest", "dataset")}
        config.update(labels=labels(h), data={"price_dir": "unused-A", "splits": [
            {"fold_id": 0, "train_end": "2018-12-31", "train_start": "2016-01-01",
             "test_start": "2019-01-07", "test_end": "2019-12-31"}]},
            features={"groups": ["base", "flow"]})
        for variant in ("A", "B"):
            name = f"h{h}_{variant}"
            folder = suite / name
            folder.mkdir()
            current = copy.deepcopy(config)
            if variant == "B":
                current["data"]["price_dir"] = str(feature_root)
                current["features"]["groups"].append("psychology")
            manifest = folder / "run_manifest.json"
            manifest.write_text(json.dumps({"config": current, "processing_contract": {},
                "feature_columns": columns + (list(RAW_FEATURES) if variant == "B" else [])}))
            pinned["run_manifest_sha256"][name] = sha256(manifest)
            oos = folder / "oos_history.parquet"
            prediction.to_parquet(oos, index=False)
            status["completed"][f"{name}:ml"] = {str(oos): sha256(oos)}
    (suite / "status.json").write_text(json.dumps(status))
    (suite / "prepared.json").write_text(json.dumps({"run_id": "completed"}))
    pinned["completion_status_sha256"] = sha256(suite / "status.json")
    evidence = tmp_path / "evidence.json"
    evidence.write_text(json.dumps(pinned))
    return suite, evidence, feature_root


def test_export_validates_pinned_inputs_and_retains_unknown_tail(tmp_path):
    suite, evidence, _ = completed_suite(tmp_path)
    output = tmp_path / "export"
    report = export(suite, output, evidence)
    assert report["runs"]["h5_A"]["rows"] == 60
    assert report["runs"]["h20_A"]["return_rows"] == 40
    frame = pd.read_parquet(output / "h5_A.parquet")
    assert frame.Code.eq("00088K").all()
    assert frame.loc[0, "forward_return"] == pytest.approx(.05)
    assert frame.tail(5).Y_Label.isna().all()
    assert not frame.tail(5).return_observed.any()
    assert sha256(output / "h5_A.parquet") == report["runs"]["h5_A"]["sha256"]
    with pytest.raises(FileExistsError):
        export(suite, output, evidence)


@pytest.mark.parametrize("changed", ["predictions", "prices", "status", "run_manifest"])
def test_export_rejects_modified_sources_without_publishing(tmp_path, changed):
    suite, evidence, feature_root = completed_suite(tmp_path)
    path = {"predictions": suite / "h5_A/oos_history.parquet", "prices": feature_root / "00088K.parquet",
            "status": suite / "status.json", "run_manifest": suite / "h5_A/run_manifest.json"}[changed]
    path.write_bytes(path.read_bytes() + b"changed")
    output = tmp_path / "export"
    with pytest.raises(ValueError, match="changed"):
        export(suite, output, evidence)
    assert not output.exists()
