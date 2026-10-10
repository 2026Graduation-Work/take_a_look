"""Run the fixed stable/aggressive Alpha158 feature A/B experiments.

The comparison deliberately reuses the chart block's canonical parquet loader and
dynamic-sigma labeler.  A profile owns its horizon, barriers, date split and two
feature-store directories; only A/B inside that profile must have identical rows.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import yaml
from lightgbm import LGBMClassifier

from ..evaluation.metrics import calculate_classification_metrics
from ..train_src.loaders import load_parquet_data
from .metrics import expected_calibration_error, select_volatile_dates

PROFILE_ORDER = ("stable", "aggressive")
VARIANTS = (("A", "baseline"), ("B", "treatment"))
PROBABILITY_COLUMN = "Prob"
METRIC_COLUMNS = (
    "accuracy",
    "balanced_accuracy",
    "macro_f1",
    "brier_score",
    "roc_auc",
    "pr_auc",
    "calibration_ece",
)


class ComparisonConfigError(ValueError):
    """Raised when the experiment contract or an A/B invariant is violated."""


def _resolve_path(value: str | Path, base_dir: Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else (base_dir / path).resolve()


def _features_from_model(model_path: Path) -> list[str]:
    if not model_path.exists():
        raise ComparisonConfigError(f"baseline feature model does not exist: {model_path}")
    with model_path.open(encoding="utf-8") as model_file:
        for line in model_file:
            if line.startswith("feature_names="):
                return line.removeprefix("feature_names=").strip().split()
    raise ComparisonConfigError(f"feature_names entry not found in model: {model_path}")


def resolve_feature_sets(config: dict[str, Any], config_dir: Path) -> tuple[list[str], list[str]]:
    feature_config = config.get("features", {})
    baseline = list(feature_config.get("baseline", []))
    model_file = feature_config.get("baseline_model_file")
    group = feature_config.get("baseline_group")
    if sum([bool(baseline), bool(model_file), bool(group)]) != 1:
        raise ComparisonConfigError(
            "configure exactly one of features.baseline or features.baseline_model_file"
        )
    if group:
        if group != "base":
            raise ComparisonConfigError("baseline_group must be base")
        from shared.features.columns import BASE_FEATURES
        baseline = list(BASE_FEATURES)
    if model_file:
        baseline = _features_from_model(_resolve_path(model_file, config_dir))

    treatment = list(feature_config.get("treatment", []))
    if not treatment:
        raise ComparisonConfigError("features.treatment must contain at least one external feature")
    overlap = sorted(set(baseline) & set(treatment))
    if overlap:
        raise ComparisonConfigError(f"baseline and treatment features overlap: {overlap}")
    if len(baseline) != len(set(baseline)) or len(treatment) != len(set(treatment)):
        raise ComparisonConfigError("feature lists must not contain duplicates")
    return baseline, treatment


def _profile_config(config: dict[str, Any], profile: str) -> dict[str, Any]:
    profiles = config.get("profiles", {})
    if profile not in profiles or not isinstance(profiles[profile], dict):
        raise ComparisonConfigError(f"profiles.{profile} is required")
    profile_config = profiles[profile]
    required = ("data", "labels")
    missing = [key for key in required if key not in profile_config]
    if missing:
        raise ComparisonConfigError(f"profiles.{profile} missing keys: {missing}")

    data = profile_config["data"]
    data_required = (
        "baseline_price_dir",
        "treatment_price_dir",
        "train_start",
        "train_end",
        "test_start",
        "test_end",
    )
    missing = [key for key in data_required if key not in data]
    if missing:
        raise ComparisonConfigError(f"profiles.{profile}.data missing keys: {missing}")
    train_start, train_end = pd.Timestamp(data["train_start"]), pd.Timestamp(data["train_end"])
    test_start, test_end = pd.Timestamp(data["test_start"]), pd.Timestamp(data["test_end"])
    if not train_start <= train_end < test_start <= test_end:
        raise ComparisonConfigError(
            f"profiles.{profile} dates must satisfy "
            "train_start <= train_end < test_start <= test_end"
        )

    labels = profile_config["labels"]
    for key in ("type", "horizon", "up_mult", "down_mult"):
        if key not in labels:
            raise ComparisonConfigError(f"profiles.{profile}.labels.{key} is required")
    if labels["type"] != "dynamic_sigma":
        raise ComparisonConfigError(f"profiles.{profile}.labels.type must be dynamic_sigma")
    return profile_config


def _fingerprint(frame: pd.DataFrame, columns: list[str]) -> str:
    hashes = pd.util.hash_pandas_object(frame[columns], index=False).to_numpy()
    return hashlib.sha256(hashes.tobytes()).hexdigest()


def _load_split(
    price_dir: Path,
    *,
    start: str,
    end: str,
    label_observation_end: str | None,
    tickers: str | list[str] | None,
    label_params: dict[str, Any],
    features: list[str],
) -> pd.DataFrame:
    if not price_dir.is_dir():
        raise ComparisonConfigError(f"feature-store directory does not exist: {price_dir}")
    try:
        frame = load_parquet_data(
            str(price_dir),
            start,
            end,
            columns_only=["Date", "Code", "Sigma", *features],
            tickers=tickers,
            label_params=label_params,
            label_observation_end=label_observation_end,
            training=False,
        )
    except (ValueError, KeyError) as exc:
        raise ComparisonConfigError(f"failed to load feature store {price_dir}: {exc}") from exc
    required = ["Date", "Code", "Sigma", "Y_Label", *features]
    missing = [column for column in required if column not in frame.columns]
    if missing:
        raise ComparisonConfigError(f"feature store {price_dir} missing columns: {missing}")
    frame = frame[required].copy()
    frame["Date"] = pd.to_datetime(frame["Date"], errors="coerce").dt.tz_localize(None)
    frame["Code"] = frame["Code"].astype("string").str.strip().str.zfill(6)
    frame = frame.sort_values(["Date", "Code"], kind="stable", ignore_index=True)
    if frame[["Date", "Code"]].duplicated().any():
        raise ComparisonConfigError(f"duplicate Date/Code rows in feature store: {price_dir}")
    numeric = ["Sigma", "Y_Label", *features]
    frame[numeric] = frame[numeric].apply(pd.to_numeric, errors="coerce")
    if frame[required].isna().to_numpy().any() or not np.isfinite(
        frame[numeric].to_numpy(dtype=float)
    ).all():
        raise ComparisonConfigError(f"missing/non-finite values in feature store: {price_dir}")
    labels = set(frame["Y_Label"].astype(int).unique())
    if labels - {0, 1, 2}:
        raise ComparisonConfigError(f"Y_Label must use chart classes 0/1/2; found {sorted(labels)}")
    frame["Y_Label"] = frame["Y_Label"].astype(int)
    return frame


def _assert_ab_alignment(
    baseline: pd.DataFrame,
    treatment: pd.DataFrame,
    *,
    profile: str,
    split: str,
    baseline_features: list[str],
) -> None:
    columns = ["Date", "Code", "Y_Label", "Sigma", *baseline_features]
    left = baseline[columns].reset_index(drop=True)
    right = treatment[columns].reset_index(drop=True)
    if not left.equals(right):
        left_hash = _fingerprint(left, columns)
        right_hash = _fingerprint(right, columns)
        raise ComparisonConfigError(
            f"{profile} {split} A/B keys, labels, Sigma, or baseline features differ "
            f"(baseline={left_hash}, treatment={right_hash})"
        )


def prepare_profile_data(
    config: dict[str, Any], profile: str, *, config_dir: Path
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame, list[str], list[str], dict]:
    """Load canonical labels independently for one profile and verify its A/B pair."""
    profile_config = _profile_config(config, profile)
    data = profile_config["data"]
    baseline_features, treatment_features = resolve_feature_sets(config, config_dir)
    tickers = data.get("tickers", []) or None
    label_params = dict(profile_config["labels"])

    paths = {
        "baseline": _resolve_path(data["baseline_price_dir"], config_dir),
        "treatment": _resolve_path(data["treatment_price_dir"], config_dir),
    }
    loaded: dict[tuple[str, str], pd.DataFrame] = {}
    for variant, path in paths.items():
        features = (
            baseline_features
            if variant == "baseline"
            else baseline_features + treatment_features
        )
        for split in ("train", "test"):
            # Train labels may only observe prices inside the training boundary.
            # Test labels intentionally use the canonical loader's right buffer,
            # including post-test prices, because those are outcomes rather than inputs.
            label_observation_end = str(data["train_end"]) if split == "train" else None
            loaded[(variant, split)] = _load_split(
                path,
                start=str(data[f"{split}_start"]),
                end=str(data[f"{split}_end"]),
                label_observation_end=label_observation_end,
                tickers=tickers,
                label_params=label_params,
                features=features,
            )
    for split in ("train", "test"):
        _assert_ab_alignment(
            loaded[("baseline", split)],
            loaded[("treatment", split)],
            profile=profile,
            split=split,
            baseline_features=baseline_features,
        )
    for variant in ("baseline", "treatment"):
        if loaded[(variant, "train")]["Y_Label"].nunique() < 3:
            raise ComparisonConfigError(
                f"{profile} {variant} training target must contain classes 0/1/2"
            )

    metadata = {
        "baseline_price_dir": str(paths["baseline"]),
        "treatment_price_dir": str(paths["treatment"]),
        "train_rows": len(loaded[("baseline", "train")]),
        "test_rows": len(loaded[("baseline", "test")]),
        "train_key_label_hash": _fingerprint(
            loaded[("baseline", "train")], ["Date", "Code", "Y_Label"]
        ),
        "test_key_label_hash": _fingerprint(
            loaded[("baseline", "test")], ["Date", "Code", "Y_Label"]
        ),
        "label_observation_policy": {
            "train": "capped_at_train_end",
            "test": "post_test_right_buffer_allowed_for_outcome_observation",
        },
    }
    return (
        loaded[("baseline", "train")],
        loaded[("baseline", "test")],
        loaded[("treatment", "train")],
        loaded[("treatment", "test")],
        baseline_features,
        treatment_features,
        metadata,
    )


def _make_model(config: dict[str, Any], seed: int) -> LGBMClassifier:
    defaults: dict[str, Any] = {
        "objective": "multiclass",
        "num_class": 3,
        "n_estimators": 500,
        "learning_rate": 0.03,
        "max_depth": 5,
        "num_leaves": 20,
        "min_child_samples": 200,
        "class_weight": "balanced",
        "verbosity": -1,
    }
    user_params = dict(config.get("model", {}).get("params", {}))
    if user_params.get("objective", "multiclass") != "multiclass":
        raise ComparisonConfigError("model.params.objective must be multiclass")
    if int(user_params.get("num_class", 3)) != 3:
        raise ComparisonConfigError("model.params.num_class must be 3")
    defaults.update(user_params)
    defaults.update(
        {
            "objective": "multiclass",
            "num_class": 3,
            "random_state": seed,
            "bagging_seed": seed,
            "feature_fraction_seed": seed,
            "data_random_seed": seed,
            "deterministic": True,
            "force_col_wise": True,
            "n_jobs": 1,
        }
    )
    return LGBMClassifier(**defaults)


def _prob_up(model: LGBMClassifier, features: pd.DataFrame) -> np.ndarray:
    classes = list(model.classes_)
    if classes != [0, 1, 2]:
        raise ComparisonConfigError(f"trained model classes must be [0, 1, 2]; found {classes}")
    return model.predict_proba(features)[:, classes.index(2)]


def _evaluate(frame: pd.DataFrame, *, bins: int, threshold: float) -> dict[str, Any]:
    shared = calculate_classification_metrics(
        frame["Y_Label"], frame[PROBABILITY_COLUMN], threshold
    )
    actual_up = (frame["Y_Label"] == 2).astype(int)
    return {
        "sample_rows": int(len(frame)),
        "sample_dates": int(frame["Date"].nunique()),
        "up_class_ratio": shared["up_class_ratio"],
        "accuracy": shared["accuracy"],
        "balanced_accuracy": shared["balanced_accuracy"],
        "macro_f1": shared["macro_f1"],
        "brier_score": shared["brier_score"],
        "roc_auc": shared["roc_auc"],
        "pr_auc": shared["pr_auc"],
        "calibration_ece": expected_calibration_error(
            actual_up, frame[PROBABILITY_COLUMN], bins=bins
        ),
    }


def _json_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _json_value(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_value(item) for item in value]
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating, float)):
        return None if not np.isfinite(value) else float(value)
    return value


def _delta_table(metrics: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for profile in PROFILE_ORDER:
        for sample in ("all", "volatile_top_20pct"):
            pair = metrics.loc[(metrics["profile"] == profile) & (metrics["sample"] == sample)]
            baseline = pair.loc[pair["variant"] == "A"].iloc[0]
            treatment = pair.loc[pair["variant"] == "B"].iloc[0]
            row: dict[str, Any] = {"profile": profile, "sample": sample}
            for metric in METRIC_COLUMNS:
                row[f"delta_B_minus_A_{metric}"] = treatment[metric] - baseline[metric]
            rows.append(row)
    return pd.DataFrame(rows)


def _build_backtest_config(
    config: dict[str, Any], profile: str, variant: str, profile_config: dict[str, Any]
) -> dict[str, Any]:
    """공용 run_backtest.py가 직접 읽을 수 있는 profile/variant config를 만듭니다."""
    data = profile_config["data"]
    labels = dict(profile_config["labels"])
    horizon = int(labels["horizon"])
    experiment_prefix = str(config.get("experiment_name", "psychology_ab"))
    strategy = {
        "score_column": "prob_up",
        "selection": "top_k",
        "top_n": 5,
        "prob_threshold": 0.65,
        "position_weighting": "equal_weight",
        **config.get("strategy", {}),
    }
    backtest = {
        "initial_cash": 10_000_000,
        "signal_lag_days": 1,
        "entry_price": "open",
        "exit_price": "open",
        "fee": 0.00105,
        "up_mult": 1.8,
        "down_mult": 1.2,
        "hard_sl_mult": 1.5,
        **config.get("backtest", {}),
        "max_holding_days": horizon,
    }
    return {
        "experiment_name": f"{experiment_prefix}_{profile}_{variant.lower()}",
        "description": f"A/B comparison canonical backtest: {profile} variant {variant}",
        "data": {
            "tickers": data.get("tickers", []),
            "price_dir": str(data["baseline_price_dir"]),
            "version": data.get("version", f"comparison_{profile}"),
            "start_date": str(data["train_start"]),
            "end_date": str(data["test_end"]),
            "split_strategy": "single",
            "embargo_days": int(data.get("embargo_days", 7)),
            "splits": [
                {
                    "fold_id": 0,
                    "name": f"{profile} A/B test",
                    "train_start": str(data["train_start"]),
                    "train_end": str(data["train_end"]),
                    "test_start": str(data["test_start"]),
                    "test_end": str(data["test_end"]),
                }
            ],
        },
        "features": {"comparison_profile": profile, "comparison_variant": variant},
        "labels": labels,
        "model": config.get("model", {}),
        "strategy": strategy,
        "backtest": backtest,
        "evaluation": {
            "random_baseline_seeds": int(
                config.get("evaluation", {}).get("random_baseline_seeds", 5)
            )
        },
    }


def run_comparison(
    config: dict[str, Any], *, config_dir: Path, output_override: Path | None = None
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    seed = int(config.get("seed", 42))
    np.random.seed(seed)
    evaluation = config.get("evaluation", {})
    fraction = float(evaluation.get("volatile_fraction", 0.2))
    if not np.isclose(fraction, 0.2):
        raise ComparisonConfigError("evaluation.volatile_fraction is fixed at 0.2")
    output = output_override or _resolve_path(
        config.get("output_dir", "../results/psychology_ab"), config_dir
    )
    output.mkdir(parents=True, exist_ok=True)
    prediction_dir = output / "predictions"
    prediction_dir.mkdir(exist_ok=True)
    backtest_config_dir = output / "backtest_configs"
    backtest_config_dir.mkdir(exist_ok=True)

    metric_rows: list[dict[str, Any]] = []
    runs: list[dict[str, Any]] = []
    profile_metadata: dict[str, Any] = {}
    for profile in PROFILE_ORDER:
        (
            base_train,
            base_test,
            treat_train,
            treat_test,
            baseline_features,
            treatment_features,
            metadata,
        ) = prepare_profile_data(config, profile, config_dir=config_dir)
        profile_config = _profile_config(config, profile)
        volatile_dates, volatility_threshold = select_volatile_dates(
            base_test, date_column="Date", volatility_column="Sigma", fraction=fraction
        )
        metadata.update(
            {
                "labels": profile_config["labels"],
                "volatile_threshold": volatility_threshold,
                "volatile_dates": [date.strftime("%Y-%m-%d") for date in volatile_dates],
            }
        )
        profile_metadata[profile] = metadata
        pairs = {
            "A": (base_train, base_test, baseline_features, "baseline"),
            "B": (
                treat_train,
                treat_test,
                baseline_features + treatment_features,
                "treatment",
            ),
        }
        for variant, (train, test, features, feature_set) in pairs.items():
            model = _make_model(config, seed)
            model.fit(train[features], train["Y_Label"])
            predictions = test[["Date", "Code", "Y_Label", "Sigma"]].copy()
            predictions[PROBABILITY_COLUMN] = _prob_up(model, test[features])
            prediction_path = (
                prediction_dir / f"{profile}_{variant.lower()}_predictions.parquet"
            )
            predictions.to_parquet(prediction_path, index=False)
            backtest_config = _build_backtest_config(
                config, profile, variant, profile_config
            )
            backtest_config["data"]["price_dir"] = str(
                _resolve_path(profile_config["data"]["baseline_price_dir"], config_dir)
            )
            backtest_config_path = backtest_config_dir / f"{profile}_{variant.lower()}.yaml"
            with backtest_config_path.open("w", encoding="utf-8") as file:
                yaml.safe_dump(backtest_config, file, allow_unicode=True, sort_keys=False)
            backtest_command = (
                f"python -m experiments.run_backtest --config {backtest_config_path} "
                f"--predictions-path {prediction_path}"
            )
            runs.append(
                {
                    "profile": profile,
                    "variant": variant,
                    "feature_set": feature_set,
                    "feature_count": len(features),
                    "features": features,
                    "train_key_label_hash": metadata["train_key_label_hash"],
                    "test_key_label_hash": metadata["test_key_label_hash"],
                    "prediction_file": str(prediction_path),
                    "backtest_config_file": str(backtest_config_path),
                    "backtest_command": backtest_command,
                }
            )
            samples = {
                "all": predictions,
                "volatile_top_20pct": predictions.loc[
                    predictions["Date"].isin(volatile_dates)
                ],
            }
            for sample_name, sample in samples.items():
                metric_rows.append(
                    {
                        "profile": profile,
                        "variant": variant,
                        "feature_set": feature_set,
                        "sample": sample_name,
                        "feature_count": len(features),
                        **_evaluate(
                            sample,
                            bins=int(evaluation.get("calibration_bins", 10)),
                            threshold=float(evaluation.get("classification_threshold", 0.5)),
                        ),
                    }
                )

    metrics = pd.DataFrame(metric_rows)
    four_runs = metrics.loc[metrics["sample"] == "all"].reset_index(drop=True)
    volatile = metrics.loc[metrics["sample"] == "volatile_top_20pct"].reset_index(drop=True)
    deltas = _delta_table(metrics)
    four_runs.to_csv(output / "four_run_metrics.csv", index=False, float_format="%.10g")
    volatile.to_csv(output / "volatile_subsample_metrics.csv", index=False, float_format="%.10g")
    deltas.to_csv(output / "comparison_deltas.csv", index=False, float_format="%.10g")

    manifest = {
        "seed": seed,
        "model_params": _make_model(config, seed).get_params(),
        "evaluation": {
            **evaluation,
            "volatile_fraction": fraction,
            "market_volatility_definition": "daily cross-sectional mean of trailing Sigma",
            "trading_metrics": (
                "not produced here; execute each runs[].backtest_command with canonical run_backtest"
            ),
        },
        "invariants": {
            "common_rows_scope": "within_profile_A_B_only",
            "cross_profile_row_equality_required": False,
            "only_A_B_difference": "features.treatment and profile treatment_price_dir",
            "baseline_features": baseline_features,
            "treatment_features": treatment_features,
        },
        "profiles": profile_metadata,
        "runs": runs,
    }
    with (output / "experiment_manifest.json").open("w", encoding="utf-8") as file:
        json.dump(_json_value(manifest), file, ensure_ascii=False, indent=2, sort_keys=True)
        file.write("\n")
    with (output / "comparison_results.json").open("w", encoding="utf-8") as file:
        json.dump(
            _json_value(
                {
                    "four_run_metrics": four_runs.to_dict("records"),
                    "volatile_subsample_metrics": volatile.to_dict("records"),
                    "comparison_deltas": deltas.to_dict("records"),
                }
            ),
            file,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        file.write("\n")
    return four_runs, volatile, deltas, manifest


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run fixed chart multiclass A/B experiments")
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--out", type=Path, help="override output_dir")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    config_path = args.config.resolve()
    try:
        with config_path.open(encoding="utf-8") as config_file:
            config = yaml.safe_load(config_file)
        if not isinstance(config, dict):
            raise ComparisonConfigError("config root must be a mapping")
        four_runs, volatile, deltas, manifest = run_comparison(
            config,
            config_dir=config_path.parent,
            output_override=args.out.resolve() if args.out else None,
        )
    except (ComparisonConfigError, FileNotFoundError) as exc:
        parser.exit(2, f"comparison experiment error: {exc}\n")
    print(f"4런 ML 지표 행 수: {len(four_runs)}")
    print(f"급변구간 ML 지표 행 수: {len(volatile)}")
    print(f"A/B 비교 행 수: {len(deltas)}")
    print("공용 backtest 실행 명령:")
    for run in manifest["runs"]:
        print(f"  {run['backtest_command']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
