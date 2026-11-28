import json
import shutil
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import yaml
from experiments.config import CHART_ROOT, load_dataset_config, load_experiment_config
from experiments.dataset.pipeline import preprocess_dataset, validate_processed_inputs
from experiments.experiment_utils import (
    find_processed_dir,
    generate_predictions_hash,
    resolve_splits,
)
from experiments.features.local_panel import FEATURE_VERSION, prepare_local_panel
from shared.io import atomic_json, canonical_hash, identity, sha256
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



def test_saved_processing_and_feature_provenance_survive_compatible_source_edits(local_dataset):
    _, settings, dataset_path, experiment_path = local_dataset
    root = Path(settings["root"])
    processed_path = root / "processed_manifest.json"
    processed = json.loads(processed_path.read_text())
    contract = processed["processing_contract"]
    contract["implementation_sha256"]["features/builder.py"] = "1" * 64
    contract["sha256"] = canonical_hash({k: v for k, v in contract.items() if k != "sha256"})
    processed["implementation_sha256"] = "1" * 64
    atomic_json(processed_path, processed)
    pinned = {path: sha256(path) for path in [processed_path, root / "processed/005930.parquet"]}

    preprocess_dataset(dataset_path)
    assert {path: sha256(path) for path in pinned} == pinned
    config = load_experiment_config(experiment_path)
    store = prepare_local_panel(config)
    canonical = Path(store["output_feature_store_dir"])
    legacy = canonical.with_name("saved-v3")
    canonical.rename(legacy)
    for key in ("inputs", "sample_keys_sha256"):
        store.pop(key)
    store["input_identity"] = identity({"processed": processed, "sources": {},
                                        "selected": store["feature_columns"], "version": FEATURE_VERSION})
    store["output_feature_store_dir"] = str(legacy)
    store["config"]["data"]["price_dir"] = str(legacy)
    store["config"]["features"]["materialized_dir"] = str(legacy)
    atomic_json(legacy / "feature_manifest.json", store)
    saved_manifest = (legacy / "feature_manifest.json").read_bytes()

    config = load_experiment_config(experiment_path)
    assert Path(find_processed_dir(config, __file__)) == legacy
    assert prepare_local_panel(config) == store
    assert (legacy / "feature_manifest.json").read_bytes() == saved_manifest
    changed = {**config, "processing_contract": {**contract,
        "implementation_sha256": {**contract["implementation_sha256"], "features/builder.py": "2" * 64}}}
    current = changed["processing_contract"]
    current["sha256"] = canonical_hash({k: v for k, v in current.items() if k != "sha256"})
    splits = resolve_splits(config)
    assert generate_predictions_hash(config, splits) == generate_predictions_hash(changed, splits)


def test_corrupt_feature_generation_is_rebuilt_in_a_separate_store(local_dataset):
    _, _, _, experiment_path = local_dataset
    config = load_experiment_config(experiment_path)
    original = prepare_local_panel(config)
    old_store = Path(original["output_feature_store_dir"])
    old_panel = old_store / "005930.parquet"
    old_panel.write_bytes(b"damaged cache")
    healed = prepare_local_panel(config)
    new_store = Path(healed["output_feature_store_dir"])

    assert new_store != old_store
    assert old_panel.read_bytes() == b"damaged cache"
    assert healed["file_hashes"] == original["file_hashes"]
    assert Path(find_processed_dir(load_experiment_config(experiment_path), __file__)) == new_store


def test_corrupt_training_binary_is_rebuilt_without_overwriting_the_saved_path(tmp_path):
    from experiments.train_src.lgbm_wrapper import LGBMWrapper

    config = {"contract_version": 3, "feature_columns": ["example"], "cache_dir": str(tmp_path)}
    model = LGBMWrapper(config)
    base = tmp_path / "training.bin"
    x, y = pd.DataFrame({"example": range(30)}), pd.Series([0, 1, 2] * 10)
    model._build_dataset(x, y, str(base))
    base.write_bytes(b"damaged cache")

    model._build_dataset(x, y, str(base))
    recovered, reusable = model.cache_entry(base, "dataset")
    assert reusable and recovered != base
    assert base.read_bytes() == b"damaged cache"
    dataset = model.load_cached_dataset(str(recovered)).construct()
    assert dataset.get_label().tolist() == y.tolist()



def test_train_regenerates_stale_models_and_predictions(local_dataset, tmp_path, monkeypatch):
    from experiments import config as config_module
    from experiments import experiment_utils, train
    from experiments.train_src.lgbm_wrapper import LGBMWrapper

    _, _, _, experiment_path = local_dataset
    load = config_module.load_experiment_config
    cfg = yaml.safe_load(experiment_path.read_text())
    cfg["training"] = {"skip_validation": True}
    experiment_path.write_text(yaml.safe_dump(cfg))
    cache_root = tmp_path / "prediction-cache"
    cache_root.mkdir()
    model_root = tmp_path / "model-cache"

    def cached_config(path):
        return {**load(path), "cache_dir": str(model_root)}

    monkeypatch.setattr(config_module, "load_experiment_config", cached_config)
    monkeypatch.setattr(experiment_utils, "cache_dir", lambda *_args, **_kwargs: str(cache_root))
    monkeypatch.setattr(train, "cache_dir", lambda *_args: str(cache_root))
    monkeypatch.setattr(train, "result_dir", lambda *_args: str(tmp_path))
    train.main(experiment_path)

    config = cached_config(experiment_path)
    splits = resolve_splits(config)
    key = generate_predictions_hash(config, splits)
    model = model_root / "models" / f"{key}_fold0_model.txt"
    predictions = Path(experiment_utils.predictions_cache_path(config, splits, __file__))
    expected = pd.read_parquet(predictions)
    model.write_bytes(b"damaged model")
    predictions.write_bytes(b"damaged predictions")

    train.main(experiment_path)

    regenerated, reusable = LGBMWrapper(config).cache_entry(model, "model")
    assert reusable and regenerated != model
    assert model.read_bytes() == b"damaged model"
    repaired = Path(experiment_utils.predictions_cache_path(config, splits, __file__))
    assert repaired != predictions
    assert predictions.read_bytes() == b"damaged predictions"
    pd.testing.assert_frame_equal(expected, experiment_utils.load_predictions(config, splits, __file__))



def test_comparison_loads_a_pinned_feature_store_without_the_live_sample_file(local_dataset, tmp_path):
    from experiments.comparison.runner import ComparisonConfigError, _load_split
    from experiments.experiment_utils import label_params_from_config

    raw, _, _, experiment_path = local_dataset
    sample = tmp_path / "sample.parquet"
    raw[["Date", "Code"]].to_parquet(sample, index=False)
    cfg = yaml.safe_load(experiment_path.read_text())
    cfg["features"]["matched_sample_file"] = str(sample)
    experiment_path.write_text(yaml.safe_dump(cfg))
    config = load_experiment_config(experiment_path)
    store = Path(prepare_local_panel(config)["output_feature_store_dir"])
    sample.rename(sample.with_name("archived-sample.parquet"))

    options = {"start": "2023-05-01", "end": "2023-07-31", "label_observation_end": "2023-08-31",
               "tickers": ["005930"], "label_params": label_params_from_config(config), "features": ["kmid"]}
    loaded = _load_split(store, **options)
    assert not loaded.empty
    assert loaded.Code.unique().tolist() == ["005930"]
    (store / "005930.parquet").write_bytes(b"tampered")
    with pytest.raises(ComparisonConfigError, match="Modified/missing feature input"):
        _load_split(store, **options)
