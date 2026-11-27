import json
import shutil
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import yaml
from experiments.config import CHART_ROOT, load_dataset_config, load_experiment_config
from experiments.dataset.pipeline import preprocess_dataset, validate_processed_inputs
from experiments.experiment_utils import find_processed_dir
from experiments.features.local_panel import prepare_local_panel
from shared.io import atomic_json
from shared.settings import processing_contract as legacy_processing_contract
from test_local_pipeline_contract import local_dataset as local_dataset


def test_qlib_dataset_profile_isolates_experiment_outputs(tmp_path):
    configs = CHART_ROOT / "experiments/configs/datasets"
    legacy = load_dataset_config(configs / "dataset_kospi.yaml")
    qlib = load_dataset_config(configs / "dataset_kospi_qlib.yaml")

    assert qlib["collection"] == legacy["collection"]
    assert qlib["root"] != legacy["root"]
    assert qlib["dataset_id"] != legacy["dataset_id"]
    assert qlib["preprocessing"] == {
        **legacy["preprocessing"],
        "feature_engine": "qlib_alpha158_v097",
    }

    qlib["preprocessing"]["feature_engine"] = None
    config = tmp_path / "dataset.yaml"
    config.write_text(yaml.safe_dump(qlib))
    with pytest.raises(ValueError, match="Unsupported preprocessing.feature_engine"):
        load_dataset_config(config)


def test_qlib_features_materialize_and_stale_contract_is_rejected(local_dataset, tmp_path):
    raw, dataset, dataset_path, experiment_path = local_dataset
    root = tmp_path / "qlib"
    shutil.copytree(
        dataset["root"],
        root,
        ignore=shutil.ignore_patterns("processed", "processed_manifest.json", "preprocessing_report.json"),
    )
    qlib_dataset_path = tmp_path / "qlib_dataset.yaml"
    qlib_dataset_path.write_text(yaml.safe_dump({
        **dataset, "dataset_id": "qlib_test", "root": str(root), "preprocessing": "qlib_alpha158",
    }))
    experiment = yaml.safe_load(experiment_path.read_text())
    experiment["dataset"] = str(qlib_dataset_path)
    experiment_path.write_text(yaml.safe_dump(experiment))

    preprocess_dataset(qlib_dataset_path)
    config = load_experiment_config(experiment_path)
    processed = validate_processed_inputs(config["dataset"])
    assert processed["processing_contract"] == config["processing_contract"]
    assert config["processing_contract"] != legacy_processing_contract(dataset["preprocessing"])
    assert validate_processed_inputs(load_dataset_config(dataset_path))["processing_contract"] == (
        legacy_processing_contract(dataset["preprocessing"])
    )
    prepare_local_panel(config)
    anchor = str(CHART_ROOT / "experiments/train.py")
    store = Path(find_processed_dir(config, anchor))
    panel = pd.read_parquet(store / "005930.parquet")
    row = 70
    close = raw.Close.to_numpy(dtype=np.float32)
    slope = np.polyfit(np.arange(5), close[row - 4 : row + 1], 1)[0]
    assert panel.loc[row, "beta_5"] == pytest.approx(slope / close[row])

    manifest_path = store / "feature_manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["config"]["processing_contract"] = legacy_processing_contract(dataset["preprocessing"])
    atomic_json(manifest_path, manifest)
    with pytest.raises(ValueError, match="Shared processing changed"):
        find_processed_dir(config, anchor)
