"""Small synthetic data verifies the local contract, never research results."""

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import yaml
from experiments.backtest.local_execution import simulate
from experiments.config import CHART_ROOT, atomic_json, atomic_parquet, load_experiment_config
from experiments.dataset.pipeline import preprocess_dataset, sha256, validate_flow, validate_prices
from experiments.features.flow import build_flow_features
from experiments.features.local_panel import prepare_local_panel
from experiments.features.registry import BASE_FEATURES, FLOW_FEATURES, resolve_feature_columns
from experiments.train_src.labels import (
    apply_dynamic_sigma_barrier_labeling,
    apply_fixed_barrier_labeling,
)
from experiments.train_src.loaders import load_parquet_data
from shared.features.builder import build_feature_frame, normalize_trading_halts


@pytest.fixture
def local_dataset(tmp_path):
    days = pd.bdate_range("2023-01-02", periods=340)
    close = 100 + 8 * np.sin(np.arange(len(days)) / 6) + np.arange(len(days)) * 0.02
    frame = pd.DataFrame(
        {
            "Date": days,
            "Code": "005930",
            "Name": "Synthetic",
            "IsDelisted": False,
            "Open": close,
            "High": close * 1.02,
            "Low": close * 0.98,
            "Close": close,
            "Volume": 1000 + np.arange(len(days)),
            "RawVolume": 1000 + np.arange(len(days)),
            "RawClose": close,
            "AdjustmentFactor": 1.0,
            "VWAP": close,
            "PriceProvider": "synthetic",
        }
    )
    for column in ("Open", "High", "Low"):
        frame[f"Raw{column}"] = frame[column]
    frame["Change"] = frame.Close.pct_change(fill_method=None).fillna(0) * 100
    frame["Amount"] = frame.Close * frame.RawVolume
    for investor in ("Individual", "Institution", "Foreign"):
        for kind in ("Volume", "Amount"):
            frame[f"{investor}_Buy{kind}"] = 20.0
            frame[f"{investor}_Sell{kind}"] = 10.0
    root = tmp_path / "dataset"
    settings = {
        "contract_version": 3,
        "dataset_id": "synthetic",
        "root": str(root),
        "collection": {
            "start_date": "2023-01-02",
            "end_date": str(days[-1].date()),
            "markets": ["KOSPI"],
            "include_delisted": True,
            "investor_flows": True,
        },
        "preprocessing": {
            "sigma_window": 20,
            "sigma_min_periods": 10,
            "barrier_feature_up_mult": 1.5,
            "barrier_feature_down_mult": 1.2,
        },
    }
    dataset_config = tmp_path / "dataset.yaml"
    dataset_config.write_text(yaml.safe_dump(settings))
    path = root / "raw" / "005930.parquet"
    atomic_parquet(path, frame)
    atomic_json(
        root / "dataset_manifest.json",
        {"contract_version": 3, "prices_complete": True, "raw_files": {path.name: sha256(path)}},
    )
    atomic_json(
        root / "calendar.json",
        {"validation_version": 3, "trading_days": [str(day.date()) for day in days]},
    )
    pd.DataFrame({"Code": ["005930"], "ListingDate": [days[0]], "DelistingDate": [pd.NaT]}).to_csv(
        root / "ticker_metadata.csv", index=False
    )
    atomic_parquet(root / "benchmarks" / "KOSPI.parquet", frame[["Date", "Close"]])
    preprocess_dataset(dataset_config)
    config = yaml.safe_load((CHART_ROOT / "experiments/configs/local_h5.yaml").read_text())
    config["dataset"] = str(dataset_config)
    config["experiment_name"] = "synthetic_contract_smoke"
    config["data"].update(
        start_date="2023-01-02",
        end_date="2024-03-29",
        tickers=["005930"],
        splits=[
            {
                "fold_id": 0,
                "train_start": "2023-01-02",
                "train_end": "2023-12-29",
                "test_start": "2024-01-08",
                "test_end": "2024-03-29",
            }
        ],
    )
    config["model"]["params"].update(n_estimators=5, min_child_samples=5, n_jobs=1)
    config["strategy"]["prob_threshold"] = 0.0
    config["evaluation"]["benchmark_file"] = str(root / "benchmarks" / "KOSPI.parquet")
    config_path = tmp_path / "experiment.yaml"
    config_path.write_text(yaml.safe_dump(config))
    return frame, settings, dataset_config, config_path


def test_local_features_are_causal_and_161_explicit(local_dataset):
    raw, settings, _, _ = local_dataset
    assert len(BASE_FEATURES) == 161 and len(set(BASE_FEATURES)) == 161
    full = build_feature_frame(raw, raw.Date, settings["preprocessing"])
    short = build_feature_frame(raw.iloc[:150], raw.Date, settings["preprocessing"])
    pd.testing.assert_frame_equal(full.iloc[:150], short)
    assert "Y_Label" not in full
    assert len(full) == len(raw)
    assert resolve_feature_columns({"groups": ["base"], "exclude": ["kmid"]}) == [
        c for c in BASE_FEATURES if c != "kmid"
    ]
    assert "Individual_BuyAmount" not in BASE_FEATURES


def test_partial_collection_uses_only_verified_files(local_dataset):
    from experiments.dataset.pipeline import validate_processed_inputs

    _, settings, dataset_path, config_path = local_dataset
    root = Path(settings["root"])
    manifest_path = root / "dataset_manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["prices_complete"] = False
    bad_path = root / "raw/000000.parquet"
    bad_path.write_bytes(b"invalid parquet")
    manifest["raw_files"][bad_path.name] = sha256(bad_path)
    atomic_json(manifest_path, manifest)
    with pytest.raises(ValueError, match="Price collection incomplete"):
        preprocess_dataset(dataset_path)

    preprocess_dataset(dataset_path, allow_partial=True)
    processed = validate_processed_inputs(settings)
    assert processed["allow_partial"] is True
    assert set(processed["files"]) == set(processed["raw_files"]) == {"005930.parquet"}
    report = json.loads((root / "preprocessing_report.json").read_text())
    assert any(row["file"] == bad_path.name and row["status"] == "failed" for row in report)
    panel = prepare_local_panel(load_experiment_config(config_path))
    assert set(panel["file_hashes"]) == {"005930.parquet"}

    manifest["raw_files"]["005930.parquet"] = "changed"
    atomic_json(manifest_path, manifest)
    with pytest.raises(ValueError, match="Dataset changed"):
        validate_processed_inputs(settings)


def test_missing_session_is_not_a_halt(local_dataset):
    raw, _, _, _ = local_dataset
    with pytest.raises(ValueError, match="Unverified missing"):
        normalize_trading_halts(raw.drop(index=100), raw.Date)
    stopped = raw.copy()
    stopped.loc[100, ["Volume", "RawVolume", "Amount"]] = 0
    stopped.loc[100, "VWAP"] = np.nan
    normalized = normalize_trading_halts(stopped, raw.Date)
    assert normalized.loc[100, "Trading_Halt"] == 1
    assert normalized.loc[100, "Close"] == stopped.loc[100, "Close"]


def test_flow_windows_distinguish_zero_missing_and_zero_denominator(local_dataset):
    raw, _, _, _ = local_dataset
    raw.loc[25, "Individual_BuyAmount"] = np.nan
    raw.loc[5, ["Individual_BuyAmount", "Individual_SellAmount"]] = 0
    raw.loc[6, "Amount"] = 0
    flow = build_flow_features(raw, raw.Date)
    assert flow.loc[5, "flow_individual_1"] == 0
    assert np.isnan(flow.loc[6, "flow_individual_1"])
    assert flow.loc[25:29, "flow_individual_5"].isna().all()
    assert np.isnan(flow.loc[43, "flow_individual_20"])
    assert pd.notna(flow.loc[45, "flow_individual_20"])


def test_label_short_tail_and_dual_touch():
    prices = pd.DataFrame(
        {
            "Close": [100.0, 90.0, 100.0],
            "High": [100.0, 120.0, 100.0],
            "Sigma": [0.1, 0.1, 0.1],
            "Trading_Halt": [0, 0, 0],
        }
    )
    assert apply_dynamic_sigma_barrier_labeling(prices, 1, 1.0, 1.0).iloc[0] == -1
    assert apply_fixed_barrier_labeling(prices, 20, 5.0, 5.0).isna().all()
    assert apply_dynamic_sigma_barrier_labeling(prices, 20, 1.0, 1.0).isna().all()
    assert np.isnan(apply_dynamic_sigma_barrier_labeling(prices.iloc[:1], 1, 1.0, 1.0).iloc[0])


def test_config_cwd_strict_keys_and_feature_store(local_dataset, monkeypatch):
    _, settings, _, config_path = local_dataset
    first = load_experiment_config(config_path)
    monkeypatch.chdir("/tmp")
    assert load_experiment_config(config_path) == first
    manifest = prepare_local_panel(first)
    frame = pd.read_parquet(Path(manifest["output_feature_store_dir"]) / "005930.parquet")
    assert len(frame) == 340 and "Y_Label" not in frame
    assert first["feature_columns"] == list(BASE_FEATURES)
    assert prepare_local_panel(first)["input_identity"] == manifest["input_identity"]
    invalid = yaml.safe_load(config_path.read_text())
    invalid["strategy"]["position_weighting"] = "risk_parity"
    config_path.write_text(yaml.safe_dump(invalid))
    with pytest.raises(ValueError, match="equal_weight"):
        load_experiment_config(config_path)
    invalid["strategy"]["position_weighting"] = "equal_weight"
    invalid["features"]["typo"] = True
    config_path.write_text(yaml.safe_dump(invalid))
    with pytest.raises(ValueError, match="Unknown features"):
        load_experiment_config(config_path)


def test_update_recomputes_identical_processed(local_dataset):
    _, settings, config_path, _ = local_dataset
    file = Path(settings["root"]) / "processed/005930.parquet"
    before = pd.read_parquet(file)
    preprocess_dataset(config_path, rebuild=True)
    pd.testing.assert_frame_equal(before, pd.read_parquet(file))


def test_price_coverage_includes_leading_gap(local_dataset):
    raw, _, _, _ = local_dataset
    with pytest.raises(ValueError, match="coverage mismatch"):
        validate_prices(raw.iloc[1:], pd.DatetimeIndex(raw.Date))
    corrupted = raw.copy()
    corrupted.loc[10, "VWAP"] = 200
    with pytest.raises(ValueError, match="VWAP"):
        validate_prices(corrupted, pd.DatetimeIndex(raw.Date))


def test_flow_cache_rejects_wrong_day():
    day = pd.Timestamp("2024-01-02")
    frame = pd.DataFrame({"Date": [day], "Code": ["005930"], "buy": [0.0], "sell": [np.nan]})
    validate_flow(frame, day, ["buy", "sell"])
    with pytest.raises(ValueError, match="date/code"):
        validate_flow(frame, day + pd.Timedelta(days=1), ["buy", "sell"])


def execution_config():
    return {
        "strategy": {"top_n": 2},
        "backtest": {
            "initial_cash": 1000.0,
            "fee": 0.01,
            "max_holding_days": 5,
            "up_mult": 1.0,
            "down_mult": 1.0,
            "hard_sl_mult": 1.0,
        },
    }


def test_execution_equal_budgets_signal_sigma_same_day_and_open_mark():
    days = pd.bdate_range("2024-01-02", periods=2)
    entries = pd.DataFrame({"000001": [True, False], "000002": [True, False]}, index=days)
    entries.attrs["signal_sigma"] = pd.DataFrame(0.1, index=days, columns=entries.columns)
    prices = pd.DataFrame(
        [
            {
                "Date": day,
                "Code": code,
                "Open": 100.0,
                "High": 120.0 if code == "000001" else 101.0,
                "Low": 80.0 if code == "000001" else 99.0,
                "Close": 105.0 if day == days[-1] else 100.0,
                "Sigma": 0.9,
                "Trading_Halt": 0,
            }
            for day in days
            for code in entries.columns
        ]
    )
    result = simulate(execution_config(), entries, entries.astype(float) / 2, prices)
    orders = result.events
    buys = orders.loc[orders.side.eq("buy")]
    assert buys.quantity.nunique() == 1
    sold = orders.loc[orders.side.eq("sell")]
    assert sold.iloc[0].price == 90.0 and sold.iloc[0].reason == "intraday_stop"
    assert len(result.open_positions) == 1
    q = 4
    expected = 1000 - 2 * q * 101 + q * 90 * 0.99 + q * 105
    assert result.value().iloc[-1] == pytest.approx(expected)
    reversed_entries = entries[entries.columns[::-1]].copy()
    reversed_entries.attrs["signal_sigma"] = entries.attrs["signal_sigma"]
    again = simulate(
        execution_config(), reversed_entries, reversed_entries.astype(float) / 2, prices
    )
    assert again.value().iloc[-1] == pytest.approx(expected)


def test_execution_never_fills_missing_held_price():
    days = pd.bdate_range("2024-01-02", periods=2)
    entries = pd.DataFrame({"000001": [True, False]}, index=days)
    entries.attrs["signal_sigma"] = pd.DataFrame(0.1, index=days, columns=entries.columns)
    prices = pd.DataFrame(
        {
            "Date": [days[0]],
            "Code": ["000001"],
            "Open": [100.0],
            "High": [101.0],
            "Low": [99.0],
            "Close": [100.0],
            "Sigma": [0.1],
            "Trading_Halt": [0],
        }
    )
    with pytest.raises(ValueError, match="lost valuation"):
        simulate(execution_config(), entries, entries.astype(float), prices)


def test_loader_fails_for_missing_requested_ticker(local_dataset):
    _, _, _, config_path = local_dataset
    config = load_experiment_config(config_path)
    prepare_local_panel(config)
    with pytest.raises(FileNotFoundError, match="Missing requested"):
        load_parquet_data(config["data"]["price_dir"], tickers=["005930", "000660"])


def test_flow_ab_matching_preserves_price_paths(local_dataset):
    raw, settings, dataset_path, config_path = local_dataset
    raw.loc[90, "Individual_BuyAmount"] = np.nan
    raw_path = Path(settings["root"]) / "raw/005930.parquet"
    atomic_parquet(raw_path, raw)
    atomic_json(
        Path(settings["root"]) / "dataset_manifest.json",
        {"prices_complete": True, "raw_files": {raw_path.name: sha256(raw_path)}},
    )
    preprocess_dataset(dataset_path, rebuild=True)
    cfg = yaml.safe_load(config_path.read_text())
    cfg["features"]["groups"] = ["base", "flow"]
    config_path.write_text(yaml.safe_dump(cfg))
    treatment = load_experiment_config(config_path)
    manifest = prepare_local_panel(treatment)
    treatment_path = Path(manifest["output_feature_store_dir"])
    cfg["features"] = {
        "groups": ["base"],
        "matched_sample_file": str(treatment_path / "sample_keys.parquet"),
    }
    config_path.write_text(yaml.safe_dump(cfg))
    control = load_experiment_config(config_path)
    prepare_local_panel(control)
    for c in (control, treatment):
        assert len(pd.read_parquet(Path(c["data"]["price_dir"]) / "005930.parquet")) == len(raw)
    left = pd.read_parquet(Path(control["data"]["price_dir"]) / "sample_keys.parquet")
    right = pd.read_parquet(treatment_path / "sample_keys.parquet")
    pd.testing.assert_frame_equal(left, right)
    assert set(FLOW_FEATURES).issubset(treatment["feature_columns"])


@pytest.mark.parametrize("with_flow", [False, True])
def test_cli_train_ml_and_backtest_share_predictions(local_dataset, with_flow):
    """Exercise the real CLIs with five trees and a synthetic price dataset."""
    import os
    import subprocess

    from experiments.experiment_utils import (
        generate_predictions_hash,
        predictions_cache_path,
        resolve_splits,
        result_dir,
    )

    raw, settings, dataset_path, config_path = local_dataset
    if with_flow:
        raw.loc[300, "Individual_BuyAmount"] = np.nan
        root = Path(settings["root"])
        path = root / "raw/005930.parquet"
        atomic_parquet(path, raw)
        manifest = json.loads((root / "dataset_manifest.json").read_text())
        manifest["raw_files"][path.name] = sha256(path)
        atomic_json(root / "dataset_manifest.json", manifest)
        preprocess_dataset(dataset_path)
        cfg = yaml.safe_load(config_path.read_text())
        cfg["features"]["groups"] = ["base", "flow"]
        config_path.write_text(yaml.safe_dump(cfg))
    config = load_experiment_config(config_path)
    prepare_local_panel(config)
    environment = {**os.environ, "KRX_ID": "", "KRX_PW": ""}
    for name in ("train.py", "run_ml_evaluation.py", "run_backtest.py"):
        command = [
            str(Path(__import__("sys").executable)),
            "-m",
            "experiments." + Path(name).stem,
            "--config",
            str(config_path),
        ]
        result = subprocess.run(
            command,
            cwd=CHART_ROOT,
            env=environment,
            text=True,
            capture_output=True,
            timeout=120,
        )
        assert result.returncode == 0, result.stdout + result.stderr
    splits = resolve_splits(config)
    path = predictions_cache_path(config, splits, str(CHART_ROOT / "experiments/train.py"))
    predictions = pd.read_parquet(path)
    assert {"prob_up", "prob_down", "prob_neutral", "fold_id"} <= set(predictions)
    assert np.allclose(predictions[["prob_down", "prob_neutral", "prob_up"]].sum(axis=1), 1)
    manifest = json.loads(Path(path + ".manifest.json").read_text())
    assert manifest["predictions_hash"] == generate_predictions_hash(config, splits)
    output = Path(result_dir(config, str(CHART_ROOT / "experiments/train.py")))
    assert (output / "backtest_metrics.json").exists()
    assert (output / "execution_report.json").exists()
    assert (output / "run_manifest.json").exists()
    history = pd.read_parquet(output / "oos_history.parquet")
    pd.testing.assert_frame_equal(history[["Date", "Code", "fold_id", "prob_up"]],
                                  predictions[["Date", "Code", "fold_id", "prob_up"]])
    assert len(history) == len(predictions)
    assert "label_observed" in history



def test_calendar_disagreement_and_unobserved_holiday_tail(tmp_path, monkeypatch):
    from experiments.dataset.pipeline import build_calendar
    from shared.data import providers as price_collector
    from shared.data import trading_calendar

    dates = pd.bdate_range("2024-01-02", "2024-01-05")
    frame = pd.DataFrame({"Close": 100.0}, index=dates)
    monkeypatch.setattr(trading_calendar, "_fetch_fdr_index", lambda *_: frame)
    monkeypatch.setattr(trading_calendar, "_fetch_pykrx_index", lambda *_: frame)
    monkeypatch.setattr(price_collector.fdr, "DataReader", lambda *_: frame)
    monkeypatch.setattr("shared.data.calendar.fetch_authenticated_index", lambda *_: frame)
    collection = {"start_date": "2024-01-02", "end_date": "2024-01-07"}
    calendar = build_calendar(tmp_path, collection)
    assert calendar["verified_end"] == "2024-01-05"
    assert calendar["unverified_tail"] == "2024-01-07"
    monkeypatch.setattr(
        trading_calendar, "_fetch_pykrx_index", lambda *_: frame.drop(index=dates[1])
    )
    with pytest.raises(ValueError, match="disagree"):
        build_calendar(tmp_path, collection)
    old = frame.iloc[:1]
    monkeypatch.setattr(trading_calendar, "_fetch_pykrx_index", lambda *_: old)
    monkeypatch.setattr(trading_calendar, "_fetch_fdr_index", lambda *_: old)
    monkeypatch.setattr(price_collector.fdr, "DataReader", lambda *_: old)
    monkeypatch.setattr("shared.data.calendar.fetch_authenticated_index", lambda *_: old)
    collection["end_date"] = "2024-01-19"
    with pytest.raises(ValueError, match="boundary coverage"):
        build_calendar(tmp_path, collection)


def test_partial_collection_resume_and_safe_rebuild(local_dataset, tmp_path, monkeypatch):
    from experiments.dataset import pipeline as module
    from shared.data import providers as price_collector

    raw, settings, _, _ = local_dataset
    raw = raw.iloc[:3].copy()
    settings["root"] = str(tmp_path / "fresh")
    settings["collection"].update(
        end_date=str(raw.Date.iloc[-1].date()), investor_flows=False, tickers=["005930"]
    )
    path = tmp_path / "collect.yaml"
    path.write_text(yaml.safe_dump(settings))

    def calendar(root, collection):
        result = {
            "validation_version": 3,
            "observed_end": collection["end_date"],
            "requested_end": collection["end_date"],
            "trading_days": raw.Date.astype(str).tolist(),
        }
        atomic_json(root / "calendar.json", result)
        return result

    monkeypatch.setattr("shared.data.prices.supplement_raw_ohlc", lambda *args: raw.set_index("Date")[["RawOpen", "RawHigh", "RawLow", "RawClose", "RawVolume", "Amount"]])
    monkeypatch.setattr(module, "build_calendar", calendar)
    monkeypatch.setattr(module, "verify_calendar_schedule", lambda *_: {"synthetic": True})
    monkeypatch.setattr(
        module,
        "load_metadata",
        lambda *_: pd.DataFrame(
            {
                "Code": ["005930"],
                "Name": ["Synthetic"],
                "Market": ["KOSPI"],
                "ListingDate": [raw.Date.iloc[0]],
                "DelistingDate": [pd.NaT],
                "IsDelisted": [False],
            }
        ),
    )
    partial = raw.iloc[1:].set_index("Date")
    monkeypatch.setattr(price_collector, "_fetch_ohlcv_fdr", lambda *_, **kwargs: partial)
    monkeypatch.setattr(price_collector, "_fetch_ohlcv_pykrx", lambda *_, **kwargs: partial)
    with pytest.raises(RuntimeError, match="incomplete"):
        module.collect_dataset(path, rebuild=True)
    root = Path(settings["root"])
    assert not (root / "raw/005930.parquet").exists()
    monkeypatch.setattr(price_collector, "_fetch_ohlcv_fdr", lambda *_, **kwargs: raw.set_index("Date"))
    module.collect_dataset(path)
    stored = pd.read_parquet(root / "raw/005930.parquet")
    assert stored.Date.min() == raw.Date.min()
    with pytest.raises(FileExistsError, match="new dataset root"):
        module.collect_dataset(path, rebuild=True)
    pd.testing.assert_frame_equal(stored, pd.read_parquet(root / "raw/005930.parquet"))

    revised = raw.copy()
    for column in ["Open", "High", "Low", "Close", "VWAP", "AdjustmentFactor"]:
        revised[column] *= 0.5
    monkeypatch.setattr(price_collector, "_fetch_ohlcv_fdr", lambda *_, **kwargs: revised.set_index("Date"))
    with pytest.raises(RuntimeError, match="incomplete"):
        module.collect_dataset(path, mode="update")
    pd.testing.assert_frame_equal(stored, pd.read_parquet(root / "raw/005930.parquet"))
    revision = json.loads(next((root / "price_revisions").glob("*.json")).read_text())
    assert "AdjustmentFactor" in revision["changed_columns"]


def test_mature_h20_and_observation_boundary():
    prices = pd.DataFrame(
        {"Close": [100.0] * 35, "High": [100.0] * 35, "Sigma": [0.1] * 35, "Trading_Halt": [0] * 35}
    )
    labels = apply_dynamic_sigma_barrier_labeling(prices, 20, 1.0, 1.0)
    assert labels.iloc[:15].eq(0).all()
    assert labels.iloc[15:].isna().all()
    assert apply_dynamic_sigma_barrier_labeling(prices.iloc[:20], 20, 1.0, 1.0).isna().all()


def test_cache_invalidation_tracks_only_stage_inputs(local_dataset):
    from experiments.experiment_utils import (
        generate_dataset_hash,
        generate_predictions_hash,
        resolve_splits,
    )

    _, _, _, config_path = local_dataset
    config = load_experiment_config(config_path)
    prepare_local_panel(config)
    splits = resolve_splits(config)
    data_hash = generate_dataset_hash(config, splits)
    predictions_hash = generate_predictions_hash(config, splits)
    changed = dict(config)
    changed["strategy"] = {**config["strategy"], "top_n": 2}
    assert generate_predictions_hash(changed, splits) == predictions_hash
    changed["model"] = {
        **config["model"],
        "params": {**config["model"]["params"], "n_estimators": 6},
    }
    assert generate_dataset_hash(changed, splits) == data_hash
    assert generate_predictions_hash(changed, splits) != predictions_hash
    changed["labels"] = {**config["labels"], "horizon": 20}
    assert generate_dataset_hash(changed, splits) != data_hash


def test_class_weights_and_binary_cache_manifest(tmp_path):
    from experiments.train_src.lgbm_wrapper import LGBMWrapper

    x = pd.DataFrame({"kmid": [0.0, 1.0, 2.0, 3.0, 4.0, 5.0]})
    y = pd.Series([0, 0, 0, 0, 1, 2])
    config = {
        "contract_version": 3,
        "feature_columns": ["kmid"],
        "cache_dir": str(tmp_path),
        "model": {"params": {"class_weight": None, "n_jobs": 1}},
    }
    plain = LGBMWrapper(config)
    dataset = plain._build_dataset(x, y, str(tmp_path / "plain.bin"))
    assert dataset.get_weight() is None
    balanced = LGBMWrapper(
        {**config, "model": {"params": {"class_weight": "balanced", "n_jobs": 1}}}
    )
    dataset = balanced._build_dataset(x, y, str(tmp_path / "balanced.bin"))
    weights = dataset.get_weight()
    assert weights[-1] > weights[0]
    assert Path(str(tmp_path / "balanced.bin") + ".manifest.json").exists()
    (tmp_path / "balanced.bin").write_bytes(b"corrupt")
    with pytest.raises(ValueError, match="Invalid dataset cache"):
        balanced.load_cached_dataset(str(tmp_path / "balanced.bin"))


@pytest.mark.parametrize("flow_status", ["interrupted", "partial", "request_failed"])
def test_interrupted_flow_leaves_usable_price_checkpoint(local_dataset, tmp_path, monkeypatch, flow_status):
    from experiments.dataset import pipeline as module
    from shared.data import providers as price_collector

    raw, settings, _, _ = local_dataset
    raw = raw.iloc[:260 if flow_status == "partial" else 3].copy()
    settings["root"] = str(tmp_path / "flow_interrupted")
    settings["collection"].update(end_date=str(raw.Date.iloc[-1].date()), investor_flows=True)
    path = tmp_path / "interrupted.yaml"
    path.write_text(yaml.safe_dump(settings))

    def calendar(root, collection):
        result = {
            "validation_version": 3,
            "observed_end": collection["end_date"],
            "requested_end": collection["end_date"],
            "trading_days": raw.Date.astype(str).tolist(),
        }
        atomic_json(root / "calendar.json", result)
        return result

    monkeypatch.setattr("shared.data.prices.supplement_raw_ohlc", lambda *args: raw.set_index("Date")[["RawOpen", "RawHigh", "RawLow", "RawClose", "RawVolume", "Amount"]])
    monkeypatch.setattr(module, "build_calendar", calendar)
    monkeypatch.setattr(module, "verify_calendar_schedule", lambda *_: {"synthetic": True})
    monkeypatch.setattr(
        module,
        "load_metadata",
        lambda *_: pd.DataFrame(
            {
                "Code": ["005930"],
                "Name": ["Synthetic"],
                "Market": ["KOSPI"],
                "ListingDate": [raw.Date.iloc[0]],
                "DelistingDate": [pd.NaT],
                "IsDelisted": [False],
            }
        ),
    )
    monkeypatch.setattr(price_collector, "_fetch_ohlcv_fdr", lambda *_, **kwargs: raw.set_index("Date"))

    def fetch(day, **kwargs):
        if flow_status == "interrupted":
            raise KeyboardInterrupt("simulated interruption")
        if flow_status == "request_failed":
            raise RuntimeError("simulated request failure")
        row = raw.loc[raw.Date.eq(day), ["Date", "Code", *price_collector._FLOW_COLUMNS]].copy()
        row[[col for col in price_collector._FLOW_COLUMNS if col.startswith("Institution_")]] = np.nan
        return row

    raw_writes = []
    original_write = module.atomic_parquet

    def tracked_write(destination, frame):
        if destination.parent.name == "raw":
            raw_writes.append(destination.name)
        return original_write(destination, frame)

    monkeypatch.setattr(module, "atomic_parquet", tracked_write)
    monkeypatch.setattr(price_collector, "_fetch_investor_day", fetch)
    if flow_status == "interrupted":
        with pytest.raises(KeyboardInterrupt):
            module.collect_dataset(path, rebuild=True)
    else:
        module.collect_dataset(path, rebuild=True)
    root = Path(settings["root"])
    manifest = json.loads((root / "dataset_manifest.json").read_text())
    assert manifest["prices_complete"] and not manifest["flows_complete"]
    if flow_status != "interrupted":
        assert manifest["flow_queries_complete"] == (flow_status == "partial")
        report = json.loads((root / "collection_report.json").read_text())
        assert report["status"] == "complete"
    if flow_status == "partial":
        assert raw_writes == ["005930.parquet", "005930.parquet"]
        merged = pd.read_parquet(root / "raw/005930.parquet")
        assert merged.Institution_BuyAmount.isna().all()
        np.testing.assert_array_equal(merged.Individual_BuyAmount, raw.Individual_BuyAmount)
    module.preprocess_dataset(path)
    assert len(pd.read_parquet(root / "processed/005930.parquet")) == len(raw)


def test_short_selected_features_do_not_force_sixty_day_warmup(local_dataset):
    _, _, _, path = local_dataset
    values = yaml.safe_load(path.read_text())
    values["features"] = {"groups": [], "include": ["kmid", "roc_5"]}
    path.write_text(yaml.safe_dump(values))
    config = load_experiment_config(path)
    prepare_local_panel(config)
    loaded = load_parquet_data(
        config["data"]["price_dir"], feature_columns=config["feature_columns"], sample_only=True
    )
    assert loaded.Date.min() < pd.Timestamp("2023-03-01")
    assert config["feature_columns"] == ["kmid", "roc_5"]


def test_stale_calendar_cache_retries_direct_index(tmp_path, monkeypatch):
    from experiments.dataset.pipeline import build_calendar
    from shared.data import providers as price_collector
    from shared.data import trading_calendar

    dates = pd.bdate_range("2024-01-02", "2024-01-12")
    full = pd.DataFrame({"Close": 100.0}, index=dates)
    stale = full.iloc[:-2]
    monkeypatch.setattr(trading_calendar, "_fetch_fdr_index", lambda *_: stale)
    monkeypatch.setattr(trading_calendar, "_fetch_pykrx_index", lambda *_: full)
    calls = []

    def fdr(symbol, *_):
        calls.append(symbol)
        return stale if symbol == "KQ11" else full

    monkeypatch.setattr(price_collector.fdr, "DataReader", fdr)
    monkeypatch.setattr("shared.data.calendar.fetch_authenticated_index", lambda *_: full)
    monkeypatch.setattr(price_collector.krx, "get_index_ohlcv_by_date", lambda *_: full)
    result = build_calendar(tmp_path, {"start_date": "2024-01-02", "end_date": "2024-01-12"})
    assert result["verified_end"] == "2024-01-12"
    assert calls == ["KQ11"]
    assert len(result["fallbacks"]) == 2
    assert result["providers"][0] == "KRX authenticated MDCSTAT00301"
    assert result["providers"][2] == "pykrx KOSDAQ 2001"
    assert len(pd.read_parquet(tmp_path / "benchmarks/KOSDAQ.parquet")) == len(dates)


def test_direct_calendar_uses_authenticated_session_and_bounded_chunks(monkeypatch):
    from experiments.dataset.pipeline import fetch_authenticated_index
    from shared.data import providers as price_collector

    calls = []

    class Response:
        def raise_for_status(self):
            pass

        def json(self):
            return {"output": [{"TRD_DD": calls[-1]["strtDd"], "CLSPRC_IDX": "2,500.50"}]}

    class Session:
        def post(self, url, *, data, timeout):
            assert url.startswith("https://data.krx.co.kr/")
            assert timeout == (10, 30)
            calls.append(data)
            return Response()

    monkeypatch.setattr(price_collector, "get_krx_session", Session)
    result = fetch_authenticated_index(pd.Timestamp("2020-01-01"), pd.Timestamp("2024-01-03"))
    assert [(c["strtDd"], c["endDd"]) for c in calls] == [
        ("20200101", "20211231"), ("20220101", "20231231"), ("20240101", "20240103")
    ]
    assert result.Close.tolist() == [2500.5] * 3


def test_calendar_rejects_missing_day_shared_by_price_providers(tmp_path, monkeypatch):
    from experiments.dataset.pipeline import build_calendar
    from shared.data import providers as price_collector
    from shared.data import trading_calendar

    dates = pd.bdate_range("2024-01-02", "2024-01-05").delete(1)
    incomplete = pd.DataFrame({"Close": 100.0}, index=dates)
    monkeypatch.setattr(trading_calendar, "_fetch_fdr_index", lambda *_: incomplete)
    monkeypatch.setattr(trading_calendar, "_fetch_pykrx_index", lambda *_: incomplete)
    monkeypatch.setattr(price_collector.fdr, "DataReader", lambda *_: incomplete)
    with pytest.raises(ValueError, match="missing_sessions=.*2024-01-03"):
        build_calendar(tmp_path, {"start_date": "2024-01-02", "end_date": "2024-01-05"})
    assert not (tmp_path / "calendar.json").exists()
    assert not (tmp_path / "benchmarks/KOSPI.parquet").exists()


def test_independent_schedule_announced_closures_and_end_boundary():
    from experiments.dataset.pipeline import scheduled_sessions, verify_calendar_schedule

    expected = scheduled_sessions(pd.Timestamp("2026-06-01"), pd.Timestamp("2026-07-20"))
    assert pd.Timestamp("2026-06-03") not in expected
    assert pd.Timestamp("2026-07-17") not in expected
    assert pd.Timestamp("2026-07-16") in expected
    payload = {"requested_start": "2026-06-01", "checked_end": "2026-07-20",
               "trading_days": expected[:-1].strftime("%Y-%m-%d").tolist()}
    with pytest.raises(ValueError, match="missing_sessions=.*2026-07-20"):
        verify_calendar_schedule(payload)


def test_revision_detection_preserves_snapshot_and_records_non_close_changes(local_dataset):
    from experiments.dataset.pipeline import reject_price_revision

    previous, settings, _, _ = local_dataset
    root = Path(settings["root"])
    original_hash = sha256(root / "raw/005930.parquet")
    # A corrected intraday high must be detected even if Close is unchanged.
    current = previous.copy()
    current.loc[0, "High"] *= 1.01
    with pytest.raises(ValueError, match="Historical prices revised"):
        reject_price_revision(root, "005930", previous, current)
    assert sha256(root / "raw/005930.parquet") == original_hash
    record = json.loads(next((root / "price_revisions").glob("*.json")).read_text())
    assert record["changed_columns"] == ["High"]
    assert record["rows"] == 1
    # An identical response, including any matching NaNs, is safe.
    reject_price_revision(root, "005930", previous, previous.copy())


def test_active_listing_dates_are_per_security_including_preferred_and_global(monkeypatch):
    from experiments.dataset.pipeline import fetch_active_listing_intervals
    from shared.data import providers as price_collector

    rows = [
        {"ISU_SRT_CD": "001040", "ISU_ABBRV": "Common", "MKT_TP_NM": "KOSPI",
         "LIST_DD": "1973/06/29", "SECUGRP_NM": "주권"},
        {"ISU_SRT_CD": "00104K", "ISU_ABBRV": "Preferred", "MKT_TP_NM": "KOSPI",
         "LIST_DD": "2019/08/09", "SECUGRP_NM": "주권"},
        {"ISU_SRT_CD": "009520", "ISU_ABBRV": "Global", "MKT_TP_NM": "KOSDAQ GLOBAL",
         "LIST_DD": "1997/11/10", "SECUGRP_NM": "주권"},
        {"ISU_SRT_CD": "123456", "ISU_ABBRV": "Fund", "MKT_TP_NM": "KOSPI",
         "LIST_DD": "2020/01/02", "SECUGRP_NM": "투자회사"},
    ]

    class Response:
        def raise_for_status(self):
            pass

        def json(self):
            return {"OutBlock_1": rows}

    class Session:
        def post(self, url, *, data, timeout):
            assert data["bld"] == "dbms/MDC/STAT/standard/MDCSTAT01901"
            assert timeout == (10, 30)
            return Response()

    monkeypatch.setattr(price_collector, "get_krx_session", Session)
    kospi = fetch_active_listing_intervals("KOSPI").set_index("Code")
    assert len(kospi) == 2
    assert kospi.loc["00104K", "ListingDate"] == pd.Timestamp("2019-08-09")
    assert kospi.loc["001040", "ListingDate"] == pd.Timestamp("1973-06-29")
    kosdaq = fetch_active_listing_intervals("KOSDAQ")
    assert kosdaq.Code.tolist() == ["009520"]
    assert kosdaq.Market.tolist() == ["KOSDAQ"]


def test_incomplete_fdr_listing_response_falls_back_to_security_metadata(monkeypatch):
    from experiments.dataset import pipeline as module
    from shared.data import providers as price_collector

    incomplete = pd.DataFrame({"Code": ["00104K"], "Name": ["Preferred"], "ListingDate": [None]})
    complete = incomplete.assign(ListingDate=pd.Timestamp("2019-08-09"))
    monkeypatch.setattr(price_collector.fdr, "StockListing", lambda *_: incomplete)
    monkeypatch.setattr(module, "fetch_active_listing_intervals", lambda *_: complete)
    result = module.load_metadata({"start_date": "2016-01-01", "markets": ["KOSPI"],
                                   "include_delisted": False}, "2026-10-06")
    assert result.ListingDate.iloc[0] == pd.Timestamp("2019-08-09")
    assert result.Source.iloc[0] == "KRX individual securities MDCSTAT01901"


def test_bulk_collection_falls_back_only_for_missing_stock(local_dataset, tmp_path, monkeypatch):
    from contextlib import nullcontext

    from experiments.dataset import pipeline as module
    from shared.data import providers as price_collector

    raw, settings, _, _ = local_dataset
    raw = raw.iloc[:3].copy()
    codes = [f"{n:06d}" for n in range(10)]
    days = pd.DatetimeIndex(raw.Date)
    settings["root"] = str(tmp_path / "bulk_dataset")
    settings["collection"].update(start_date=str(days[0].date()), end_date=str(days[-1].date()),
                                   investor_flows=False, tickers=codes)
    config = tmp_path / "bulk.yaml"
    config.write_text(yaml.safe_dump(settings))

    def calendar(root, _):
        result = {"validation_version": 3, "requested_end": str(days[-1].date()),
                  "observed_end": str(days[-1].date()), "trading_days": days.astype(str).tolist()}
        atomic_json(root / "calendar.json", result)
        return result

    monkeypatch.setattr(module, "build_calendar", calendar)
    monkeypatch.setattr(module, "verify_calendar_schedule", lambda _: {})
    monkeypatch.setattr(module, "load_metadata", lambda *_: pd.DataFrame({
        "Code": codes, "Name": "Synthetic", "Market": "KOSPI", "ListingDate": days[0],
        "DelistingDate": pd.NaT, "IsDelisted": False,
    }))
    monkeypatch.setattr(price_collector, "_krx_request_timeout", nullcontext)
    daily_calls, fallback_calls = [], []

    def daily(day, **kwargs):
        daily_calls.append(day)
        row = raw.loc[raw.Date.eq(pd.Timestamp(day))].iloc[0]
        present = codes if pd.Timestamp(day) != days[-1] else codes[:-1]
        return pd.DataFrame({"시가": row.RawOpen, "고가": row.RawHigh, "저가": row.RawLow, "종가": row.RawClose, "거래량": row.RawVolume,
                             "거래대금": row.Amount}, index=present)

    monkeypatch.setattr(price_collector.krx, "get_market_ohlcv_by_ticker", daily)
    adjusted = raw.set_index("Date")[["Open", "High", "Low", "Close", "Volume", "Change"]].copy()
    adjusted["Change"] /= 100
    monkeypatch.setattr(price_collector.fdr, "DataReader", lambda *_: adjusted)

    def individual(start, end, code, *, adjusted):
        assert adjusted is False
        fallback_calls.append(code)
        return raw.set_index("Date")[["RawOpen", "RawHigh", "RawLow", "RawClose", "RawVolume", "Amount"]].rename(columns={
            "RawOpen": "시가", "RawHigh": "고가", "RawLow": "저가", "RawClose": "종가", "RawVolume": "거래량", "Amount": "거래대금",
        })

    monkeypatch.setattr(price_collector.krx, "get_market_ohlcv_by_date", individual)
    module.collect_dataset(config)
    assert daily_calls == days.strftime("%Y%m%d").tolist()
    assert fallback_calls == [codes[-1]]
    root = Path(settings["root"])
    assert len(list((root / "raw").glob("*.parquet"))) == 10
    before = {p.name: sha256(p) for p in (root / "raw").glob("*.parquet")}
    daily_calls.clear()
    fallback_calls.clear()
    module.collect_dataset(config)
    assert daily_calls == fallback_calls == []
    assert before == {p.name: sha256(p) for p in (root / "raw").glob("*.parquet")}


def test_sliding_2016_2026_configs_and_frozen_end(local_dataset, tmp_path):
    from experiments.experiment_utils import resolve_splits

    _, settings, dataset_path, _ = local_dataset
    root = Path(settings["root"])
    manifest = json.loads((root / "dataset_manifest.json").read_text())
    manifest["end_date"] = "2026-10-06"
    atomic_json(root / "dataset_manifest.json", manifest)
    settings["collection"]["end_date"] = None
    settings["collection"]["start_date"] = "2016-01-01"
    dataset_path.write_text(yaml.safe_dump(settings))
    for horizon in [5, 20]:
        for suffix, count in [("", 161), ("_flow", 170)]:
            source = CHART_ROOT / f"experiments/configs/sliding_2016_2026_h{horizon}{suffix}.yaml"
            cfg = yaml.safe_load(source.read_text())
            cfg["dataset"] = str(dataset_path)
            path = tmp_path / f"h{horizon}{suffix}.yaml"
            path.write_text(yaml.safe_dump(cfg))
            resolved = load_experiment_config(path)
            splits = resolve_splits(resolved)
            assert len(splits) == 8
            assert splits[0]["train_start"] == "2016-01-01"
            assert splits[0]["train_end"] == "2018-12-31"
            assert splits[0]["test_start"] == "2019-01-07"
            assert splits[-1]["train_start"] == "2023-01-01"
            assert splits[-1]["train_end"] == "2025-12-31"
            assert splits[-1]["test_end"] == "2026-10-06"
            assert resolved["labels"]["horizon"] == horizon
            assert resolved["backtest"]["capital_mode"] == "independent_year"
            assert len(resolved["feature_columns"]) == count


def test_independent_year_resets_cash_positions_and_signal_lag(tmp_path, monkeypatch):
    from experiments import run_backtest as module

    days = pd.to_datetime(["2019-12-30", "2019-12-31", "2020-01-02", "2020-01-03"])
    prices = pd.DataFrame({"Date": days, "Code": "005930", "Open": [100, 100, 200, 200],
                           "Close": [100, 110, 200, 200], "High": [100, 110, 200, 200],
                           "Low": [100, 100, 200, 200], "Sigma": 0.1, "Trading_Halt": 0})
    predictions = pd.DataFrame({"Date": days, "Code": "005930", "prob_up": 1.0,
                                "fold_id": [0, 0, 1, 1]})
    config = {"contract_version": 3, "data": {"embargo_days": 0},
              "strategy": {"score_column": "prob_up", "top_n": 1, "prob_threshold": 0.5},
              "backtest": {"capital_mode": "independent_year", "initial_cash": 1000,
                           "fee": 0.0, "signal_lag_days": 1, "max_holding_days": 20,
                           "up_mult": None, "down_mult": None, "hard_sl_mult": None}}
    splits = [{"fold_id": i, "train_start": f"{year-3}-01-01", "train_end": f"{year-1}-12-31",
               "test_start": f"{year}-01-01", "test_end": f"{year}-12-31"}
              for i, year in enumerate([2019, 2020])]
    monkeypatch.setattr(module, "resolve_splits", lambda _: splits)
    monkeypatch.setattr(module, "load_predictions", lambda *_: predictions)
    monkeypatch.setattr(module, "load_parquet_data", lambda *args, **kwargs: prices)
    monkeypatch.setattr(module, "find_processed_dir", lambda *_: tmp_path)
    monkeypatch.setattr(module, "resolve_tickers", lambda *_: ["005930"])
    monkeypatch.setattr(module, "load_universe_intervals", lambda _: None)
    monkeypatch.setattr(module, "result_dir", lambda *_: str(tmp_path))
    monkeypatch.setattr(module, "configured_benchmark", lambda cfg, dates, frame: pd.Series(0.0, index=dates))
    module.run_local_backtest(config)
    summary = json.loads((tmp_path / "backtest_metrics.json").read_text())
    assert summary["cash_and_positions_carried"] is False
    assert summary["years"][0]["final_equity"] == pytest.approx(1100)
    assert summary["years"][1]["initial_cash"] == 1000
    assert summary["years"][1]["final_equity"] == pytest.approx(1000)
    orders = pd.read_csv(tmp_path / "years/2020/orders.csv")
    assert orders.quantity.tolist() == [5.0]
    assert pd.to_datetime(orders.date).dt.normalize().tolist() == [days[-1]]
    assert summary["years"][0]["unclosed_positions"] == 1
    assert summary["years"][1]["unclosed_positions"] == 1
    equity = pd.read_csv(tmp_path / "equity_curve.csv")
    assert equity.loc[equity.year.eq(2020), "Equity"].iloc[0] == 1000


def test_previous_builder_processed_data_is_preserved(local_dataset):
    _, settings, dataset_path, _ = local_dataset
    root = Path(settings["root"])
    manifest_path = root / "processed_manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest.pop("processing_contract")
    atomic_json(manifest_path, manifest)
    before = {path: sha256(path) for path in [manifest_path, root / "processed/005930.parquet", root / "raw/005930.parquet"]}
    with pytest.raises(ValueError, match="new dataset root"):
        preprocess_dataset(dataset_path)
    assert {path: sha256(path) for path in before} == before
