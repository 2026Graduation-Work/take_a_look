import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import yaml
from experiments.comparison import runner as comparison_runner
from experiments.comparison.runner import (
    ComparisonConfigError,
    prepare_profile_data,
    resolve_feature_sets,
    run_comparison,
)

CHART_DIR = Path(__file__).resolve().parents[3]


def _write_store(path: Path, *, treatment: bool, drop_last: bool = False) -> None:
    path.mkdir(parents=True)
    dates = pd.date_range("2023-01-02", periods=180, freq="B")
    for number, code in enumerate(("000001", "000002", "000003")):
        phase = np.arange(len(dates)) + number * 7
        close = 100 + np.sin(phase / 3) * 5 + np.sin(phase / 13) * 2
        frame = pd.DataFrame(
            {
                "Date": dates,
                "Code": code,
                "Open": close,
                "High": close + 0.1,
                "Low": close - 2,
                "Close": close,
                "Volume": 1000,
                "Trading_Halt": 0,
                "Sigma": 0.015 + number * 0.001,
                "technical_momentum": np.sin(phase / 3),
                "technical_volume": np.cos(phase / 5),
            }
        )
        if treatment:
            frame["synthetic_psychology_index"] = np.sin(phase / 7)
            frame["news_sentiment"] = np.cos(phase / 11)
        if drop_last and code == "000003":
            frame = frame.drop(index=140)
        frame.to_parquet(path / f"{code}.parquet", index=False)


def _config(base: Path, treatment: Path, output: Path) -> dict:
    profiles = {}
    for profile, horizon, up, down in (
        ("stable", 20, 3.75, 3.00),
        ("aggressive", 5, 1.75, 1.50),
    ):
        profiles[profile] = {
            "data": {
                "baseline_price_dir": str(base),
                "treatment_price_dir": str(treatment),
                "tickers": [],
                "train_start": "2023-01-02",
                "train_end": "2023-05-31",
                "test_start": "2023-06-12",
                "test_end": "2023-08-04",
            },
            "labels": {
                "type": "dynamic_sigma",
                "horizon": horizon,
                "up_mult": up,
                "down_mult": down,
            },
        }
    return {
        "seed": 42,
        "features": {
            "baseline": ["technical_momentum", "technical_volume"],
            "treatment": ["synthetic_psychology_index", "news_sentiment"],
        },
        "profiles": profiles,
        "model": {"params": {"n_estimators": 20, "num_leaves": 7, "min_child_samples": 5}},
        "evaluation": {
            "classification_threshold": 0.5,
            "calibration_bins": 5,
            "volatile_fraction": 0.2,
        },
        "output_dir": str(output),
    }


def test_example_config_resolves_tracked_baseline_model() -> None:
    config_path = CHART_DIR / "experiments" / "comparison" / "config.example.yaml"
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    baseline, treatment = resolve_feature_sets(config, config_path.parent)
    assert len(baseline) == 161
    assert treatment == ["synthetic_psychology_index", "news_sentiment"]
    assert config["model"]["params"]["n_estimators"] == 1000
    assert config["model"]["params"]["learning_rate"] == 0.01
    assert config["model"]["params"]["min_child_samples"] == 2000


def test_runs_multiclass_four_models_with_profile_scoped_alignment(tmp_path: Path) -> None:
    base, treatment = tmp_path / "base", tmp_path / "treatment"
    _write_store(base, treatment=False)
    _write_store(treatment, treatment=True)
    output = tmp_path / "results"
    four_runs, volatile, deltas, manifest = run_comparison(
        _config(base, treatment, output), config_dir=tmp_path
    )
    assert list(zip(four_runs["profile"], four_runs["variant"], strict=True)) == [
        ("stable", "A"), ("stable", "B"), ("aggressive", "A"), ("aggressive", "B")
    ]
    assert len(volatile) == 4
    assert len(deltas) == 4
    assert set(four_runs.loc[four_runs["variant"] == "A", "feature_count"]) == {2}
    assert set(four_runs.loc[four_runs["variant"] == "B", "feature_count"]) == {4}
    assert manifest["model_params"]["objective"] == "multiclass"
    assert manifest["model_params"]["num_class"] == 3
    assert manifest["invariants"]["common_rows_scope"] == "within_profile_A_B_only"
    assert manifest["invariants"]["cross_profile_row_equality_required"] is False
    prediction = pd.read_parquet(output / "predictions" / "stable_a_predictions.parquet")
    assert prediction["Prob"].between(0, 1).all()
    assert set(prediction["Y_Label"].unique()) <= {0, 1, 2}
    assert {"four_run_metrics.csv", "volatile_subsample_metrics.csv", "comparison_deltas.csv"} <= {
        item.name for item in output.iterdir()
    }
    results = json.loads((output / "comparison_results.json").read_text())
    assert len(results["four_run_metrics"]) == 4
    for run in manifest["runs"]:
        assert Path(run["prediction_file"]).exists()
        assert "backtest_command" not in run


def test_repeated_runs_are_deterministic(tmp_path: Path) -> None:
    base, treatment = tmp_path / "base", tmp_path / "treatment"
    _write_store(base, treatment=False)
    _write_store(treatment, treatment=True)
    first = run_comparison(_config(base, treatment, tmp_path / "first"), config_dir=tmp_path)[:3]
    second = run_comparison(_config(base, treatment, tmp_path / "second"), config_dir=tmp_path)[:3]
    for left, right in zip(first, second, strict=True):
        pd.testing.assert_frame_equal(left, right)


def test_rejects_different_rows_within_profile_ab(tmp_path: Path) -> None:
    base, treatment = tmp_path / "base", tmp_path / "treatment"
    _write_store(base, treatment=False)
    _write_store(treatment, treatment=True, drop_last=True)
    config = _config(base, treatment, tmp_path / "out")
    with pytest.raises(ComparisonConfigError, match="A/B keys, labels"):
        prepare_profile_data(config, "aggressive", config_dir=tmp_path)


def test_rejects_binary_model_override(tmp_path: Path) -> None:
    config = _config(tmp_path / "base", tmp_path / "treatment", tmp_path / "out")
    config["model"]["params"]["objective"] = "binary"
    base, treatment = resolve_feature_sets(config, tmp_path)
    assert base and treatment
    from experiments.comparison.runner import _make_model

    with pytest.raises(ComparisonConfigError, match="must be multiclass"):
        _make_model(config, 42)


def test_train_labels_cannot_observe_prices_after_train_end(tmp_path: Path) -> None:
    original, changed_future = tmp_path / "original", tmp_path / "changed_future"
    _write_store(original, treatment=False)
    _write_store(changed_future, treatment=False)
    train_end = "2023-05-31"
    for path in changed_future.glob("*.parquet"):
        frame = pd.read_parquet(path)
        future = frame["Date"] > pd.Timestamp(train_end)
        frame.loc[future, ["Open", "High", "Low", "Close"]] = [1000, 1001, 999, 1000]
        frame.to_parquet(path, index=False)

    kwargs = {
        "start": "2023-01-02",
        "end": train_end,
        "label_observation_end": train_end,
        "tickers": None,
        "label_params": {
            "type": "dynamic_sigma",
            "horizon": 20,
            "up_mult": 3.75,
            "down_mult": 3.00,
        },
        "features": ["technical_momentum", "technical_volume"],
    }
    left = comparison_runner._load_split(original, **kwargs)
    right = comparison_runner._load_split(changed_future, **kwargs)
    pd.testing.assert_frame_equal(left, right)
    assert left["Date"].max() < pd.Timestamp(train_end)
