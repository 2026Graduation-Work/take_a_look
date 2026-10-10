# ruff: noqa: I001

from pathlib import Path

import pandas as pd

from experiments.evaluation.metrics import _pr_auc_score_binary
from experiments.experiment_utils import data_fingerprint, generate_dataset_hash, resolve_splits


def _window_config(strategy: str) -> dict:
    return {
        "data": {
            "split_strategy": strategy,
            "embargo_days": 7,
            strategy: {
                "start_year": 2016,
                "end_year": 2023,
                "test_window_years": 2,
                **({"train_window_years": 3} if strategy == "sliding" else {"initial_train_years": 3}),
            },
        }
    }


def test_pr_auc_is_invariant_to_tied_score_row_order() -> None:
    y_true = pd.Series([1, 0, 1, 0, 1])
    y_prob = pd.Series([0.8, 0.8, 0.5, 0.5, 0.2])
    reordered = [1, 0, 3, 2, 4]

    original = _pr_auc_score_binary(y_true, y_prob)
    shuffled = _pr_auc_score_binary(y_true.iloc[reordered], y_prob.iloc[reordered])

    assert original == shuffled


def test_sliding_two_year_test_windows_are_non_overlapping() -> None:
    folds = resolve_splits(_window_config("sliding"))

    assert [(fold["test_start"], fold["test_end"]) for fold in folds] == [
        ("2019-01-07", "2020-12-31"),
        ("2021-01-07", "2022-12-31"),
    ]
    assert folds[1]["train_start"] == "2018-01-01"
    assert folds[1]["train_end"] == "2020-12-31"


def test_expanding_two_year_test_windows_are_non_overlapping() -> None:
    folds = resolve_splits(_window_config("expanding"))

    assert [(fold["test_start"], fold["test_end"]) for fold in folds] == [
        ("2019-01-07", "2020-12-31"),
        ("2021-01-07", "2022-12-31"),
    ]
    assert folds[1]["train_start"] == "2016-01-01"
    assert folds[1]["train_end"] == "2020-12-31"


def test_data_fingerprint_changes_cache_hash_when_parquet_manifest_changes(tmp_path: Path) -> None:
    parquet_path = tmp_path / "prices.parquet"
    parquet_path.write_bytes(b"first-version")
    config = {"data": {"price_dir": str(tmp_path), "version": "v1"}}
    splits = [{"fold_id": 0, "train_start": "2020-01-01", "train_end": "2020-12-31", "test_start": "2021-01-08", "test_end": "2021-12-31"}]

    before_fingerprint = data_fingerprint(config)
    before_hash = generate_dataset_hash(config, splits)
    parquet_path.write_bytes(b"second-version-with-a-different-size")

    assert data_fingerprint(config) != before_fingerprint
    assert generate_dataset_hash(config, splits) != before_hash


def test_generated_folds_do_not_extend_past_configured_data_end() -> None:
    config = _window_config("sliding")
    config["data"]["end_date"] = "2020-12-31"

    folds = resolve_splits(config)

    assert [(fold["test_start"], fold["test_end"]) for fold in folds] == [
        ("2019-01-07", "2020-12-31")
    ]
