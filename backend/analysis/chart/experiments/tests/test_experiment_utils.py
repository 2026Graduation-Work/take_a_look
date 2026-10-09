# ruff: noqa: I001

import pandas as pd
import pytest

from experiments.experiment_utils import (
    build_fold_alignment,
    filter_to_test_fold_rows,
    resolve_tickers,
)


SPLITS = [{"fold_id": 0, "name": "fold-0", "test_start": "2024-01-01", "test_end": "2024-01-31"}]


def test_frozen_universe_is_loaded_and_missing_prices_fail(tmp_path) -> None:
    universe = tmp_path / "universe.csv"
    universe.write_text("Code\n5930\n123456\n")
    (tmp_path / "005930.parquet").touch()
    config = {"data": {"universe_file": str(universe), "price_dir": str(tmp_path)}}
    with pytest.raises(ValueError, match="Missing processed files"):
        resolve_tickers(config, __file__)
    (tmp_path / "123456.parquet").touch()
    assert resolve_tickers(config, __file__) == ["005930", "123456"]


def test_fold_alignment_rejects_missing_actual_label_key() -> None:
    predictions = pd.DataFrame(
        {"Date": pd.to_datetime(["2024-01-02", "2024-01-03"]), "Code": ["000001", "000002"]}
    )
    actuals = predictions.iloc[[0]].assign(Y_Label=1)

    _, status = build_fold_alignment(predictions, SPLITS, eval_df=actuals)
    assert not status["is_exact_row_match"]


def test_fold_alignment_rejects_duplicate_actual_keys() -> None:
    predictions = pd.DataFrame(
        {"Date": pd.to_datetime(["2024-01-02", "2024-01-03"]), "Code": ["000001", "000002"]}
    )
    actuals = pd.concat([predictions, predictions.iloc[[0]]], ignore_index=True).assign(Y_Label=1)

    _, status = build_fold_alignment(predictions, SPLITS, eval_df=actuals)
    assert not status["is_exact_row_match"]


def test_fold_alignment_uses_test_fold_union_and_excludes_embargo_rows() -> None:
    splits = [
        {"fold_id": 0, "name": "fold-0", "test_start": "2024-01-02", "test_end": "2024-01-03"},
        {"fold_id": 1, "name": "fold-1", "test_start": "2024-01-08", "test_end": "2024-01-09"},
    ]
    predictions = pd.DataFrame(
        {
            "Date": pd.to_datetime(["2024-01-02", "2024-01-03", "2024-01-08", "2024-01-09"]),
            "Code": ["000001"] * 4,
        }
    )
    actuals_with_embargo = pd.concat(
        [
            predictions.assign(Y_Label=1),
            pd.DataFrame(
                {"Date": pd.to_datetime(["2024-01-04", "2024-01-05"]), "Code": ["000001", "000001"], "Y_Label": [1, 1]}
            ),
        ],
        ignore_index=True,
    )

    actuals = filter_to_test_fold_rows(actuals_with_embargo, splits)
    _, status = build_fold_alignment(predictions, splits, eval_df=actuals)

    assert actuals["Date"].tolist() == predictions["Date"].tolist()
    assert status["is_exact_row_match"]
