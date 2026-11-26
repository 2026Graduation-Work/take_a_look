# ruff: noqa: I001

import pandas as pd
import pytest

from experiments.config import load_experiment_config
from experiments.train import _evaluate_validation, _training_windows


class _FixedProbModel:
    def predict(self, features: pd.DataFrame):
        # The halted row receives the highest score on every day.  If validation
        # substitutes Trading_Halt=0, it would incorrectly be selected instead.
        return features["feature"].to_numpy()


def _validation_frame() -> pd.DataFrame:
    dates = pd.date_range("2024-01-01", periods=5, freq="B")
    rows = []
    for date in dates:
        rows.extend(
            [
                {"Date": date, "Code": "HALTED", "Close": 100.0, "Trading_Halt": 1, "Y_Label": 2, "feature": 0.99},
                {"Date": date, "Code": "TRADEABLE", "Close": 100.0, "Trading_Halt": 0, "Y_Label": 1, "feature": 0.80},
            ]
        )
    return pd.DataFrame(rows).set_index("Code", drop=False)


def test_validation_excludes_halted_high_probability_signals() -> None:
    metrics = _evaluate_validation(
        {"strategy": {"prob_threshold": 0.65, "top_n": 1}},
        {"fold_id": 0, "name": "fold", "train_start": "2023-01-01", "train_end": "2023-12-31"},
        0,
        _FixedProbModel(),
        _validation_frame(),
        ["feature"],
    )

    assert metrics["selected_signal_count"] == 5
    assert metrics["selected_success_count"] == 0


def test_rank_only_backtest_config_keeps_training_validation_threshold() -> None:
    config = load_experiment_config("experiments/configs/base.yaml")
    frame = pd.DataFrame({
        "Date": pd.Timestamp("2024-01-02"),
        "Code": ["AT_THRESHOLD", "BELOW_THRESHOLD"],
        "Close": 100.0,
        "Trading_Halt": 0,
        "Y_Label": [2, 1],
        "feature": [0.65, 0.64],
    })

    metrics = _evaluate_validation(
        config,
        {"train_start": "2023-01-01", "train_end": "2023-12-31"},
        0,
        _FixedProbModel(),
        frame,
        ["feature"],
    )

    assert config["strategy"]["prob_threshold"] == 0.0
    assert metrics["selected_signal_count"] == 1
    assert metrics["selected_success_count"] == 1


def test_validation_rejects_missing_trade_metadata() -> None:
    frame = _validation_frame().drop(columns=["Trading_Halt"])
    with pytest.raises(ValueError, match="메타데이터"):
        _evaluate_validation(
            {"strategy": {}},
            {"fold_id": 0, "name": "fold", "train_start": "2023-01-01", "train_end": "2023-12-31"},
            0,
            _FixedProbModel(),
            frame,
            ["feature"],
        )


def test_final_holdout_uses_full_training_period_without_label_leakage() -> None:
    split = {
        "train_start": "2022-01-01",
        "train_end": "2024-12-31",
        "test_start": "2025-01-08",
        "test_end": "2025-12-31",
    }

    assert _training_windows(split, embargo_days=7, skip_validation=True) == (
        "2024-12-31",
        "2024-12-31",
        "2024-12-31",
        "2024-12-31",
        None,
    )


def test_standard_run_keeps_internal_validation_window() -> None:
    split = {
        "train_start": "2022-01-01",
        "train_end": "2024-12-31",
        "test_start": "2025-01-08",
        "test_end": "2025-12-31",
    }

    assert _training_windows(split, embargo_days=7, skip_validation=False) == (
        "2024-06-30",
        "2024-07-06",
        "2024-07-07",
        "2024-12-31",
        "2025-01-07",
    )
