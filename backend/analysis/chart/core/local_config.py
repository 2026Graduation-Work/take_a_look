"""Validated local research configuration; all relative paths are chart-relative."""

from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path

import pandas as pd
import yaml

CHART_ROOT = Path(__file__).resolve().parents[1]
CONTRACT_VERSION = 3


def chart_path(value):
    path = Path(value)
    return path.resolve() if path.is_absolute() else (CHART_ROOT / path).resolve()


def read_yaml(value):
    path = Path(value)
    if not path.is_file():
        path = chart_path(value)
    with path.open(encoding="utf-8") as handle:
        result = yaml.safe_load(handle)
    if not isinstance(result, dict):
        raise ValueError(f"Configuration must be an object: {path}")
    return result


def keys(value, allowed, section):
    if not isinstance(value, dict):
        raise ValueError(f"{section} must be an object")
    if unknown := set(value) - set(allowed.split()):
        raise ValueError(f"Unknown {section} keys: {sorted(unknown)}")


def positive_int(value, name):
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError(f"{name} must be a positive integer")


def load_dataset_config(path):
    config = read_yaml(path)
    keys(config, "contract_version dataset_id root collection preprocessing", "dataset")
    if config.get("contract_version") != CONTRACT_VERSION:
        raise ValueError("Use contract_version: 3; see configs/dataset.yaml")
    for name in ("dataset_id", "root", "collection", "preprocessing"):
        if name not in config:
            raise ValueError(f"Missing dataset.{name}")
    root = chart_path(config["root"])
    # Rebuild must never touch the historical serving/source dataset.
    if (
        root == CHART_ROOT / "data"
        or CHART_ROOT / "data" in root.parents
        and root.name in {"raw", "processed"}
    ):
        raise ValueError("Use a distinct dataset root, e.g. data/datasets/local_v1")
    config["root"] = str(root)
    collection = config["collection"]
    keys(
        collection,
        "start_date end_date markets include_delisted investor_flows tickers",
        "collection",
    )
    if pd.Timestamp(collection["start_date"]) < pd.Timestamp("2016-01-01"):
        raise ValueError("collection.start_date must be 2016-01-01 or later")
    if collection.get("end_date") and pd.Timestamp(collection["start_date"]) > pd.Timestamp(
        collection["end_date"]
    ):
        raise ValueError("collection.start_date > end_date")
    if not collection.get("markets") or set(collection["markets"]) - {"KOSPI", "KOSDAQ"}:
        raise ValueError("collection.markets must contain KOSPI/KOSDAQ")
    for flag in ("include_delisted", "investor_flows"):
        if not isinstance(collection.get(flag), bool):
            raise ValueError(f"collection.{flag} must be a boolean")
    pre = config["preprocessing"]
    keys(
        pre,
        "sigma_window sigma_min_periods barrier_feature_up_mult barrier_feature_down_mult",
        "preprocessing",
    )
    for name in ("sigma_window", "sigma_min_periods"):
        positive_int(pre[name], name)
    if pre["sigma_min_periods"] > pre["sigma_window"]:
        raise ValueError("sigma_min_periods exceeds sigma_window")
    for name in ("barrier_feature_up_mult", "barrier_feature_down_mult"):
        if pre[name] <= 0:
            raise ValueError(f"{name} must be positive")
    return config


def load_experiment_config(path):
    from experiments.features.registry import resolve_feature_columns

    config = read_yaml(path)
    keys(
        config,
        "contract_version dataset experiment_name description tags data features labels model training strategy backtest evaluation",
        "experiment",
    )
    if config.get("contract_version") != CONTRACT_VERSION or "dataset" not in config:
        raise ValueError(
            "Legacy config: add contract_version: 3 and dataset; migrate features to groups/include/exclude (experiments/configs/local_h5.yaml)"
        )
    dataset = load_dataset_config(config["dataset"])
    config["dataset"] = dataset
    data = config.setdefault("data", {})
    keys(
        data,
        "tickers universe universe_file point_in_time start_date end_date split_strategy embargo_days splits sliding expanding custom_blocks",
        "data",
    )
    for field in ("start_date", "end_date"):
        if field not in data:
            raise ValueError(f"Missing data.{field}")
    if pd.Timestamp(data["start_date"]) > pd.Timestamp(data["end_date"]):
        raise ValueError("data.start_date > end_date")
    if pd.Timestamp(data["start_date"]) < pd.Timestamp(dataset["collection"]["start_date"]):
        raise ValueError("Experiment starts before dataset")
    if dataset["collection"].get("end_date") and pd.Timestamp(data["end_date"]) > pd.Timestamp(
        dataset["collection"]["end_date"]
    ):
        raise ValueError("Experiment ends after dataset")
    if data.get("split_strategy", "single") not in {
        "single",
        "sliding",
        "expanding",
        "custom_blocks",
    }:
        raise ValueError("Unsupported split strategy")
    active_strategy = data.get("split_strategy", "single")
    inactive = {
        "single": "splits",
        "sliding": "sliding",
        "expanding": "expanding",
        "custom_blocks": "custom_blocks",
    }
    for strategy_name, section_name in inactive.items():
        if section_name in data and strategy_name != active_strategy:
            raise ValueError(
                f"data.{section_name} does not apply to split_strategy={active_strategy}"
            )
    if (
        isinstance(data.get("embargo_days", 7), bool)
        or not isinstance(data.get("embargo_days", 7), int)
        or data.get("embargo_days", 7) < 0
    ):
        raise ValueError("embargo_days must be a nonnegative integer")
    for split in data.get("splits", []) + data.get("custom_blocks", []):
        keys(split, "fold_id name train_start train_end test_start test_end", "split")
        if not (
            pd.Timestamp(data["start_date"])
            <= pd.Timestamp(split["train_start"])
            <= pd.Timestamp(split["train_end"])
            < pd.Timestamp(split["test_start"])
            <= pd.Timestamp(split["test_end"])
            <= pd.Timestamp(data["end_date"])
        ):
            raise ValueError("Conflicting split dates")
    for section, allowed in (
        ("sliding", "train_window_years test_window_years start_year end_year"),
        ("expanding", "initial_train_years test_window_years start_year end_year"),
    ):
        if section in data:
            keys(data[section], allowed, section)
            for name, value in data[section].items():
                positive_int(value, name)
    data["point_in_time"] = data.get("point_in_time", False)
    if data["point_in_time"] and not data.get("universe_file"):
        raise ValueError("point_in_time requires a verified universe_file")
    manifest_path = Path(dataset["root"]) / "dataset_manifest.json"
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text())
        if manifest.get("end_date"):
            data["end_date"] = str(min(pd.Timestamp(data["end_date"]), pd.Timestamp(manifest["end_date"])).date())
            if pd.Timestamp(data["start_date"]) > pd.Timestamp(data["end_date"]):
                raise ValueError("Experiment has no observations before dataset's frozen end")
    features = config.setdefault("features", {})
    keys(features, "groups include exclude sources psychology matched_sample_file", "features")
    config["feature_columns"] = resolve_feature_columns(features)
    from experiments.features.psychology import PsychologyFeatureConfig

    PsychologyFeatureConfig(**features.get("psychology", {}))
    from experiments.features.panel_builder import _parse_source_spec

    for source in features.get("sources", []):
        keys(source, "name path apply_period columns missing", "features.source")
        keys(
            source.get("missing", {}),
            "policy add_indicator max_staleness_trading_days",
            "features.source.missing",
        )
        spec = _parse_source_spec(source)
        if spec.missing_policy in {"drop", "zero"} or spec.add_indicator:
            raise ValueError(
                "Local feature sources preserve missing values and price paths; use error/forward_fill without indicators"
            )
    labels = config["labels"]
    keys(
        labels,
        "type horizon up_mult down_mult tp sl volatility_mode up_class neutral_class down_class",
        "labels",
    )
    if (
        labels.get("type") not in {"fixed", "dynamic_sigma"}
        or labels.get("volatility_mode", "current_sigma") != "current_sigma"
    ):
        raise ValueError("Supported labels: fixed/dynamic_sigma with current_sigma")
    positive_int(labels["horizon"], "labels.horizon")
    if (labels.get("down_class", 0), labels.get("neutral_class", 1), labels.get("up_class", 2)) != (
        0,
        1,
        2,
    ):
        raise ValueError("Label classes must be down=0, neutral=1, up=2")
    for name in ("tp", "sl") if labels["type"] == "fixed" else ("up_mult", "down_mult"):
        if name not in labels or labels[name] <= 0:
            raise ValueError(f"labels.{name} must be positive")
    model = config["model"]
    keys(model, "type objective params", "model")
    if model.get("type") != "LGBM" or model.get("objective", "multiclass") != "multiclass":
        raise ValueError("Only LGBM multiclass supported")
    params = model.setdefault("params", {})
    keys(
        params,
        "n_estimators learning_rate max_depth num_leaves min_child_samples colsample_bytree subsample subsample_freq class_weight random_state n_jobs reg_alpha reg_lambda max_bin min_split_gain",
        "model.params",
    )
    params.setdefault("random_state", 42)
    keys(config.setdefault("training", {}), "skip_validation", "training")
    if not isinstance(config["training"].get("skip_validation", False), bool):
        raise ValueError("skip_validation must be boolean")
    for name in ("n_estimators", "num_leaves", "min_child_samples", "max_bin"):
        if name in params:
            positive_int(params[name], name)
    if isinstance(params["random_state"], bool) or not isinstance(params["random_state"], int):
        raise ValueError("random_state must be a fixed integer")
    strategy = config["strategy"]
    keys(strategy, "score_column selection top_n prob_threshold position_weighting", "strategy")
    if strategy.get("selection") != "top_k" or strategy.get("position_weighting") != "equal_weight":
        raise ValueError("Only top_k/equal_weight supported")
    if strategy.get("score_column") not in {"prob_up", "prob_neutral", "prob_down"}:
        raise ValueError("score_column must name a probability column")
    positive_int(strategy["top_n"], "top_n")
    if not 0 <= strategy["prob_threshold"] <= 1:
        raise ValueError("prob_threshold must be in [0,1]")
    bt = config["backtest"]
    keys(
        bt,
        "initial_cash signal_lag_days entry_price exit_price fee max_holding_days up_mult down_mult hard_sl_mult capital_mode",
        "backtest",
    )
    bt.setdefault("capital_mode", "continuous")
    if bt["capital_mode"] not in {"continuous", "independent_year"}:
        raise ValueError("backtest.capital_mode must be continuous or independent_year")
    if bt.get("entry_price") != "open" or bt.get("exit_price") != "rule":
        raise ValueError("Only entry_price: open / exit_price: rule supported")
    for name in ("signal_lag_days", "max_holding_days"):
        positive_int(bt[name], name)
    if (
        not math.isfinite(bt["initial_cash"])
        or not math.isfinite(bt["fee"])
        or bt["initial_cash"] <= 0
        or not 0 <= bt["fee"] < 1
    ):
        raise ValueError("Invalid initial_cash/fee")
    for name in ("up_mult", "down_mult", "hard_sl_mult"):
        if bt.get(name) is not None and bt[name] <= 0:
            raise ValueError(f"backtest.{name} must be positive or null")
    evaluation = config.setdefault("evaluation", {})
    keys(evaluation, "probability_bins benchmark_file benchmark_strategies", "evaluation")
    if evaluation.get("benchmark_strategies", []) not in ([], ["market_index"]):
        raise ValueError("Local evaluation supports only the fixed market_index benchmark")
    bins = evaluation.get("probability_bins", [0, 0.2, 0.4, 0.6, 0.8, 1])
    if bins[0] != 0 or bins[-1] != 1 or any(a >= b for a, b in zip(bins, bins[1:])):
        raise ValueError("probability_bins must increase from 0 to 1")
    base = Path(dataset["root"]) / "processed"
    config["features"]["base_processed_dir"] = str(base)
    # Feature identity is independent of model, labels and strategy.
    input_files = [Path(dataset["root"]) / "processed_manifest.json"]
    features_root = CHART_ROOT / "experiments" / "features"
    input_files += [
        features_root / name
        for name in (
            "registry.py",
            "flow.py",
            "local_panel.py",
            "panel_builder.py",
            "psychology/market_psychology.py",
        )
    ]
    input_files += [chart_path(source["path"]) for source in features.get("sources", [])]
    for source in features.get("sources", []):
        source["path"] = str(chart_path(source["path"]))
    if features.get("matched_sample_file"):
        features["matched_sample_file"] = str(chart_path(features["matched_sample_file"]))
        input_files.append(Path(features["matched_sample_file"]))
    from core.local_dataset import sha256

    feature_id = identity(
        {
            "dataset": dataset,
            "features": features,
            "columns": config["feature_columns"],
            "inputs": {str(p): sha256(p) if p.exists() else None for p in input_files},
        }
    )
    store = Path(dataset["root"]) / "feature_store" / feature_id
    config["features"]["materialized_dir"] = str(store)
    config["data"]["price_dir"] = str(store)
    config["data"]["version"] = dataset["dataset_id"]
    config["contract_version"] = CONTRACT_VERSION
    return config


def identity(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str).encode()).hexdigest()[:16]


def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8"
    )
    temporary.replace(path)


def atomic_parquet(path, frame):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    frame.to_parquet(temporary, index=False)
    temporary.replace(path)


def append_collection_event(root, event):
    """Append failure/retry history across executions without raw HTTP payloads."""
    path = Path(root) / "collection_events.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    entry = {"timestamp": pd.Timestamp.now(tz="UTC").isoformat(), "pid": os.getpid(), **event}
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry, ensure_ascii=False, default=str) + "\n")
