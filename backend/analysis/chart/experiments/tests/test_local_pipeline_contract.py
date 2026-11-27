import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import yaml
from backtest_harness import bars, signals
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


@pytest.mark.parametrize("legacy_fields", [
    {"price_basis": "krx_raw_base_price_events_v1"},
    {"price_basis": "krx_raw_ohlc_uniform_close_ratio_v1"},
    {"price_policy": "immutable_krx_raw_with_events_as_of_dataset_end"},
    {"price_policy": "krx_raw_ohlc_uniform_close_ratio_snapshot_not_point_in_time_archive"},
])
def test_previous_price_policy_requires_collection_before_using_processed_data(local_dataset, legacy_fields):
    from experiments.dataset.pipeline import validate_processed_inputs

    _, settings, dataset_path, _ = local_dataset
    manifest_path = Path(settings["root"]) / "dataset_manifest.json"
    manifest = json.loads(manifest_path.read_text())
    atomic_json(manifest_path, {**manifest, **legacy_fields})

    for allow_partial in (False, True):
        with pytest.raises(ValueError, match="rerun collection"):
            preprocess_dataset(dataset_path, allow_partial=allow_partial)
    with pytest.raises(ValueError, match="rerun collection"):
        validate_processed_inputs(settings)


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
            "initial_cash": 10_000.0,
            "fee": 0.01,
            "slippage_bps": 0,
            "max_participation": None,
            "max_holding_days": 5,
            "up_mult": 1.0,
            "down_mult": 1.0,
            "hard_sl_mult": 1.0,
        },
    }


def test_execution_equal_budgets_and_signal_time_barriers():
    days = pd.bdate_range("2024-01-02", periods=3)
    entries = pd.DataFrame({"000001": [False, True, False], "000002": [False, True, False]},
                           index=days)

    def bar(day, code):
        if day == days[0]:
            return dict(Open=100.0, High=100.0, Low=100.0, Close=100.0, Sigma=0.1)
        if day == days[1]:
            wide = code == "000001"
            return dict(Open=100.0, High=120.0 if wide else 101.0, Low=80.0 if wide else 99.0,
                        Close=100.0, Sigma=0.9)
        return dict(Open=100.0, High=105.0, Low=99.0, Close=105.0, Sigma=0.9)

    prices = pd.DataFrame([{"Date": day, "Code": code, "Trading_Halt": 0, **bar(day, code)}
                           for day in days for code in entries.columns])
    result = simulate(execution_config(), entries, prices)
    orders = result.events
    buys = orders.loc[orders.side.eq("buy")]
    assert buys.quantity.tolist() == [9, 9]  # Slot 10,000 / (2 × 5) at 101 with fee.
    # Signal-day Sigma 0.1 puts the stop at 90; same-day Sigma 0.9 would put it at 10.
    sold = result.trades.set_index("code")
    assert sold.loc["000001", "exit_price"] == 90.0
    assert sold.loc["000001", "exit_reason"] == "intraday_stop"
    assert sold.loc["000002", "exit_reason"] == "period_end"
    expected = 10_000 - 2 * 9 * 101 + 9 * 90 * 0.99 + 9 * 105 * 0.99
    assert result.value().iloc[-1] == pytest.approx(expected)
    again = simulate(execution_config(), entries[entries.columns[::-1]], prices)
    assert again.value().iloc[-1] == pytest.approx(expected)


def test_execution_never_fills_missing_held_price():
    days = pd.bdate_range("2024-01-02", periods=3)
    entries = pd.DataFrame({"000001": [False, True, False]}, index=days)
    prices = pd.DataFrame({"Date": days[:2], "Code": "000001", "Open": 100.0, "High": 101.0,
                           "Low": 99.0, "Close": 100.0, "Sigma": 0.1, "Trading_Halt": 0})
    with pytest.raises(ValueError, match="lost valuation"):
        simulate(execution_config(), entries, prices)


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


@pytest.mark.parametrize("horizon,with_flow", [(5, False), (5, True), (20, False)])
def test_cli_train_ml_and_backtest_share_predictions(local_dataset, horizon, with_flow):
    import os
    import subprocess

    from experiments.experiment_utils import (
        generate_predictions_hash,
        load_predictions,
        predictions_cache_path,
        resolve_splits,
        result_dir,
    )
    from experiments.run_backtest import run_local_backtest

    raw, settings, dataset_path, config_path = local_dataset
    cfg = yaml.safe_load(config_path.read_text())
    if horizon == 20:
        h20 = yaml.safe_load((CHART_ROOT / "experiments/configs/local_h20.yaml").read_text())
        cfg.update(labels=h20["labels"], backtest=h20["backtest"])
    if with_flow:
        raw.loc[300, "Individual_BuyAmount"] = np.nan
        root = Path(settings["root"])
        path = root / "raw/005930.parquet"
        atomic_parquet(path, raw)
        manifest = json.loads((root / "dataset_manifest.json").read_text())
        manifest["raw_files"][path.name] = sha256(path)
        atomic_json(root / "dataset_manifest.json", manifest)
        preprocess_dataset(dataset_path)
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
    manifest_path = Path(path + ".manifest.json")
    manifest = json.loads(manifest_path.read_text())
    assert manifest["predictions_hash"] == generate_predictions_hash(config, splits)
    assert manifest["config"]["labels"] == config["labels"]
    recorded_labels = {**config["labels"], "down_class": 0.0, "neutral_class": 1.0, "up_class": 2.0}
    atomic_json(
        manifest_path, {**manifest, "config": {**manifest["config"], "labels": recorded_labels}}
    )
    pd.testing.assert_frame_equal(load_predictions(config, splits, __file__, path), predictions)
    atomic_json(manifest_path, manifest)
    output = Path(result_dir(config, str(CHART_ROOT / "experiments/train.py")))
    assert (output / "backtest_metrics.json").exists()
    assert (output / "execution_report.json").exists()
    assert (output / "run_manifest.json").exists()
    history = pd.read_parquet(output / "oos_history.parquet")
    pd.testing.assert_frame_equal(history[["Date", "Code", "fold_id", "prob_up"]],
                                  predictions[["Date", "Code", "fold_id", "prob_up"]])
    assert len(history) == len(predictions)
    assert "label_observed" in history

    cfg["labels"].update(up_mult=1.5, down_mult=1.2)
    cfg["backtest"].update(up_mult=1.5, down_mult=1.2)
    config_path.write_text(yaml.safe_dump(cfg))
    changed = load_experiment_config(config_path)
    with pytest.raises(ValueError, match="Trained prediction labels.*requested") as exc:
        run_local_backtest(changed, path)
    assert str(config["labels"]) in str(exc.value)
    assert str(changed["labels"]) in str(exc.value)

    atomic_json(
        manifest_path, {**manifest, "config": {**manifest["config"], "labels": changed["labels"]}}
    )
    with pytest.raises(ValueError, match="Trained prediction labels.*requested"):
        load_predictions(config, splits, __file__, path)

    for mismatched_labels in (
        {**config["labels"], "horizon": True},
        {**config["labels"], "up_mult": float("inf")},
        {**config["labels"], "down_class": 2},
    ):
        atomic_json(manifest_path, {**manifest, "config": {"labels": mismatched_labels}})
        with pytest.raises(ValueError, match="Trained prediction labels.*requested"):
            load_predictions(config, splits, __file__, path)

    for invalid_labels in (
        None,
        {"type": "dynamic_sigma", "horizon": horizon},
    ):
        atomic_json(manifest_path, {**manifest, "config": {"labels": invalid_labels}})
        with pytest.raises(ValueError, match=r"Invalid prediction manifest config\.labels"):
            load_predictions(config, splits, __file__, path)
    manifest_path.write_text('{"config":')
    with pytest.raises(ValueError, match="Invalid prediction manifest JSON"):
        load_predictions(config, splits, __file__, path)
    atomic_json(manifest_path, manifest)

def test_calendar_disagreement_and_unobserved_holiday_tail(tmp_path, monkeypatch):
    from experiments.dataset.pipeline import build_calendar
    from shared.data import trading_calendar

    dates = pd.bdate_range("2024-01-02", "2024-01-05")
    frame = pd.DataFrame({"Close": 100.0}, index=dates)
    monkeypatch.setattr(trading_calendar, "_fetch_pykrx_index", lambda *_: frame)
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
    monkeypatch.setattr("shared.data.calendar.fetch_authenticated_index", lambda *_: old)
    collection["end_date"] = "2024-01-19"
    with pytest.raises(ValueError, match="boundary coverage"):
        build_calendar(tmp_path, collection)


def _synthetic_krx_raw(frame):
    raw = frame[["Date", "RawOpen", "RawHigh", "RawLow", "RawClose", "RawVolume", "Amount"]].copy()
    fields = ["RawOpen", "RawHigh", "RawLow", "RawClose"]
    raw[fields] = raw[fields].round().astype(int)
    raw["Amount"] = raw.RawClose * raw.RawVolume
    raw["RawChange"] = raw.RawClose.diff().fillna(0).astype(int)
    raw["ListedShares"] = 100_000
    return raw


def test_partial_collection_resume_and_safe_rebuild(local_dataset, tmp_path, monkeypatch):
    from experiments.dataset import pipeline as module

    raw, settings, _, _ = local_dataset
    raw = _synthetic_krx_raw(raw.iloc[:3])
    raw.loc[2, ["RawOpen", "RawHigh", "RawLow", "RawClose"]] = [50, 53, 49, 51]
    raw.loc[2, "Amount"] = raw.RawClose.iloc[2] * raw.RawVolume.iloc[2]
    raw.loc[2, "RawChange"] = 1
    raw.loc[2, "ListedShares"] = 200_000
    raw.loc[1, "RawClose"] = 100
    raw.loc[1, "RawChange"] = raw.RawClose.iloc[1] - raw.RawClose.iloc[0]
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
    monkeypatch.setattr(module, "fetch_raw_window", lambda *_, **kwargs: raw.iloc[1:])
    with pytest.raises(RuntimeError, match="incomplete"):
        module.collect_dataset(path, rebuild=True)
    root = Path(settings["root"])
    assert not (root / "raw/005930.parquet").exists()
    assert not (root / "krx_raw_prices/005930.parquet").exists()
    monkeypatch.setattr(module, "fetch_raw_window", lambda *_, **kwargs: raw)
    module.collect_dataset(path)
    stored = pd.read_parquet(root / "raw/005930.parquet")
    assert stored.Date.min() == raw.Date.min()
    with pytest.raises(FileExistsError, match="new dataset root"):
        module.collect_dataset(path, rebuild=True)
    pd.testing.assert_frame_equal(stored, pd.read_parquet(root / "raw/005930.parquet"))

    original_path = root / "krx_raw_prices/005930.parquet"
    derived_path = root / "raw/005930.parquet"
    original_hash = sha256(original_path)
    manifest_path = root / "dataset_manifest.json"
    manifest = json.loads(manifest_path.read_text())
    assert manifest["krx_raw_files"] == {original_path.name: original_hash}
    events_path = root / manifest["price_events"]["path"]
    event_hash = sha256(events_path)
    event_bytes = events_path.read_bytes()
    assert manifest["price_events"]["sha256"] == event_hash
    assert pd.read_parquet(events_path).PriceFactor.tolist() == [0.5]
    assert stored.AdjustmentFactor.tolist() == [0.5, 0.5, 1.0]
    np.testing.assert_array_equal(stored.Volume, raw.RawVolume * [2, 2, 1])

    def no_repeat(*_, **kwargs):
        pytest.fail("Verified KRX source must not be requested again")

    monkeypatch.setattr(module, "fetch_raw_window", no_repeat)
    revised = stored.copy()
    revised.loc[0, "Close"] += 1
    atomic_parquet(derived_path, revised)
    module.collect_dataset(path, mode="update")
    pd.testing.assert_frame_equal(stored, pd.read_parquet(derived_path))
    assert sha256(original_path) == original_hash
    assert json.loads(manifest_path.read_text())["price_events"] == manifest["price_events"]

    revised.loc[0, "RawHigh"] += 1
    atomic_parquet(derived_path, revised)
    revised_hash = sha256(derived_path)

    def interrupt_manifest(destination, value):
        if destination == manifest_path:
            raise KeyboardInterrupt()
        atomic_json(destination, value)

    with monkeypatch.context() as interrupted:
        interrupted.setattr(module, "atomic_json", interrupt_manifest)
        with pytest.raises(KeyboardInterrupt):
            module.collect_dataset(path, mode="update")
    assert json.loads(manifest_path.read_text())["price_events"] == manifest["price_events"]
    assert events_path.read_bytes() == event_bytes

    with pytest.raises(RuntimeError, match="incomplete"):
        module.collect_dataset(path, mode="update")
    assert sha256(derived_path) == revised_hash
    assert sha256(original_path) == original_hash
    failed_manifest = json.loads(manifest_path.read_text())
    assert failed_manifest["price_events"]["path"] != events_path.name
    failed_events = root / failed_manifest["price_events"]["path"]
    assert failed_manifest["price_events"]["sha256"] == sha256(failed_events)
    assert pd.read_parquet(failed_events).empty
    assert sha256(events_path) == event_hash


def test_failed_event_adjustment_preserves_verified_raw_without_refetching(local_dataset, tmp_path, monkeypatch):
    from experiments.dataset import pipeline as module

    _, settings, _, _ = local_dataset
    fixture = CHART_ROOT / "shared/tests/fixtures/004920_2020.csv"
    raw = pd.read_csv(fixture, comment="#", parse_dates=["Date"])
    root = tmp_path / "unconfirmed_event"
    end = str(raw.Date.iloc[-1].date())
    settings["root"] = str(root)
    settings["collection"].update(
        start_date=str(raw.Date.iloc[0].date()), end_date=end, investor_flows=False, tickers=["123456"]
    )
    path = tmp_path / "unconfirmed_event.yaml"
    path.write_text(yaml.safe_dump(settings))
    atomic_json(root / "calendar.json", {
        "validation_version": 3, "observed_end": end, "requested_end": end,
        "trading_days": raw.Date.astype(str).tolist(),
    })
    pd.DataFrame({
        "Code": ["123456"], "Name": ["Synthetic"], "Market": ["KOSPI"],
        "ListingDate": [raw.Date.iloc[0]], "DelistingDate": [pd.NaT], "IsDelisted": [False],
    }).to_csv(root / "ticker_metadata.csv", index=False)
    monkeypatch.setattr(module, "verify_calendar_schedule", lambda *_: {"synthetic": True})
    monkeypatch.setattr(module, "fetch_raw_window", lambda *_, **kwargs: raw)

    def assert_failed_collection(raw_hash):
        manifest = json.loads((root / "dataset_manifest.json").read_text())
        assert manifest["krx_raw_files"] == {"123456.parquet": raw_hash}
        assert not manifest["prices_complete"]
        assert manifest["raw_files"] == {}
        assert not (root / "raw/123456.parquet").exists()
        report = json.loads((root / "collection_report.json").read_text())
        assert report["prices"][0]["status"] == "failed"
        assert "123456 2020-03-20" in report["prices"][0]["reason"]

    with pytest.raises(RuntimeError, match="incomplete"):
        module.collect_dataset(path)
    original_path = root / "krx_raw_prices/123456.parquet"
    raw_hash = sha256(original_path)
    pd.testing.assert_frame_equal(pd.read_parquet(original_path), raw)
    assert_failed_collection(raw_hash)

    def no_repeat(*_, **kwargs):
        pytest.fail("Verified KRX source must not be requested again after an adjustment failure")

    monkeypatch.setattr(module, "fetch_raw_window", no_repeat)
    with pytest.raises(RuntimeError, match="incomplete"):
        module.collect_dataset(path)
    assert sha256(original_path) == raw_hash
    assert_failed_collection(raw_hash)


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
    monkeypatch.setattr(module, "fetch_raw_window", lambda *_, **kwargs: _synthetic_krx_raw(raw))

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


def test_calendar_uses_krx_indexes_and_rejects_incomplete_kosdaq(tmp_path, monkeypatch):
    from experiments.dataset.pipeline import build_calendar
    from shared.data import providers as price_collector

    dates = pd.bdate_range("2024-01-02", "2024-01-12")
    kospi = pd.DataFrame({"Close": 2500.0}, index=dates)
    kosdaq = pd.DataFrame({"Close": 800.0}, index=dates)
    calls = []

    def fetch(start, end, ticker, *, name_display):
        assert (start, end, name_display) == ("20240102", "20240112", False)
        calls.append(ticker)
        return {"1001": kospi, "2001": kosdaq}[ticker]

    monkeypatch.setattr(price_collector.krx, "get_index_ohlcv_by_date", fetch)
    monkeypatch.setattr("shared.data.calendar.fetch_authenticated_index", lambda *_: kospi)
    collection = {"start_date": "2024-01-02", "end_date": "2024-01-12"}
    result = build_calendar(tmp_path, collection)
    assert result["verified_end"] == "2024-01-12"
    assert calls == ["1001", "2001"]
    assert result["providers"] == ["pykrx KOSPI 1001", "KRX authenticated MDCSTAT00301", "pykrx KOSDAQ 2001"]
    assert result["fallbacks"] == []
    assert pd.read_parquet(tmp_path / "benchmarks/KOSDAQ.parquet").Close.tolist() == [800.0] * len(dates)

    kosdaq = kosdaq.iloc[:-1]
    with pytest.raises(ValueError, match="KOSDAQ index has missing sessions"):
        build_calendar(tmp_path / "incomplete", collection)
    assert not (tmp_path / "incomplete/calendar.json").exists()


@pytest.mark.parametrize("ticker", ["1001", "2001"])
def test_direct_calendar_uses_authenticated_session_and_bounded_chunks(monkeypatch, ticker):
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
    result = fetch_authenticated_index(pd.Timestamp("2020-01-01"), pd.Timestamp("2024-01-03"), ticker)
    assert [(c["strtDd"], c["endDd"]) for c in calls] == [
        ("20200101", "20211231"), ("20220101", "20231231"), ("20240101", "20240103")
    ]
    assert {(c["indIdx"], c["indIdx2"]) for c in calls} == {(ticker[0], ticker[1:])}
    assert result.Close.tolist() == [2500.5] * 3


def test_calendar_rejects_missing_day_shared_by_price_providers(tmp_path, monkeypatch):
    from experiments.dataset.pipeline import build_calendar
    from shared.data import trading_calendar

    dates = pd.bdate_range("2024-01-02", "2024-01-05").delete(1)
    incomplete = pd.DataFrame({"Close": 100.0}, index=dates)
    monkeypatch.setattr(trading_calendar, "_fetch_pykrx_index", lambda *_: incomplete)
    monkeypatch.setattr("shared.data.calendar.fetch_authenticated_index", lambda *_: incomplete)
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


def test_krx_active_listings_keep_equities_with_own_dates_and_kosdaq_global(monkeypatch):
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
        {"ISU_SRT_CD": "234567", "ISU_ABBRV": "DR", "MKT_TP_NM": "KOSPI",
         "LIST_DD": "2020/01/03", "SECUGRP_NM": "주식예탁증권"},
        {"ISU_SRT_CD": "345678", "ISU_ABBRV": "Foreign", "MKT_TP_NM": "KOSDAQ",
         "LIST_DD": "2020/01/06", "SECUGRP_NM": "외국주권"},
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
    assert set(kospi.index) == {"001040", "00104K"}
    assert kospi.loc["00104K", "ListingDate"] == pd.Timestamp("2019-08-09")
    assert kospi.loc["001040", "ListingDate"] == pd.Timestamp("1973-06-29")
    kosdaq = fetch_active_listing_intervals("KOSDAQ")
    assert kosdaq.Code.tolist() == ["009520"]
    assert kosdaq.Market.eq("KOSDAQ").all()


def test_load_metadata_records_krx_listing_source_and_rejects_missing_date(monkeypatch):
    from experiments.dataset import pipeline as module
    from shared.data import metadata as shared_metadata

    frame = pd.DataFrame({"Code": ["00104K"], "Name": ["Preferred"], "ListingDate": [pd.Timestamp("2019-08-09")]})
    monkeypatch.setattr(shared_metadata, "fetch_active_listing_intervals", lambda *_: frame)
    collection = {"start_date": "2016-01-01", "markets": ["KOSPI"], "include_delisted": False}
    result = module.load_metadata(collection, "2026-10-06")
    assert result.ListingDate.iloc[0] == pd.Timestamp("2019-08-09")
    assert result.Source.iloc[0] == "KRX individual securities MDCSTAT01901"
    frame["ListingDate"] = pd.NaT
    with pytest.raises(ValueError, match="Unknown listing interval"):
        module.load_metadata(collection, "2026-10-06")


def test_bulk_collection_falls_back_only_for_missing_stock(local_dataset, tmp_path, monkeypatch):
    from contextlib import nullcontext

    from experiments.dataset import pipeline as module
    from shared.data import bulk_prices, training_prices
    from shared.data import providers as price_collector

    raw, settings, _, _ = local_dataset
    raw = _synthetic_krx_raw(raw.iloc[:3])
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

    def daily(day):
        daily_calls.append(day.strftime("%Y%m%d"))
        row = raw.loc[raw.Date.eq(day)].iloc[0]
        present = codes if day != days[-1] else codes[:-1]
        return pd.DataFrame({**row.to_dict(), "Code": present})

    def individual(code, start, end, *, is_delisted):
        assert (start, end, is_delisted) == (days[0], days[-1], False)
        fallback_calls.append(code)
        return raw

    monkeypatch.setattr(bulk_prices, "request_day", daily)
    monkeypatch.setattr(bulk_prices.time, "sleep", lambda _: None)
    monkeypatch.setattr(training_prices, "request_history", individual)
    module.collect_dataset(config)
    assert daily_calls == days.strftime("%Y%m%d").tolist()
    assert fallback_calls == [codes[-1]]
    root = Path(settings["root"])
    assert len(list((root / "raw").glob("*.parquet"))) == 10
    assert len(list((root / "krx_raw_prices").glob("*.parquet"))) == 10
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
              "backtest": {"capital_mode": "independent_year", "initial_cash": 20_000,
                           "fee": 0.0, "slippage_bps": 0, "max_participation": None,
                           "signal_lag_days": 1, "max_holding_days": 20,
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
    status = json.loads((tmp_path / "backtest_status.json").read_text())
    assert status["status"] == "done"
    assert status["progress"] == {"year": [2, 2], "random": [0, 0]}
    assert status["finished_at"] >= status["started_at"]
    summary = json.loads((tmp_path / "backtest_metrics.json").read_text())
    assert summary["cash_and_positions_carried"] is False
    assert summary["years"][0]["final_equity"] == pytest.approx(20_100)
    assert summary["years"][1]["initial_cash"] == 20_000
    assert summary["years"][1]["final_equity"] == pytest.approx(20_000)
    orders = pd.read_csv(tmp_path / "years/2020/orders.csv")
    assert orders.side.tolist() == ["buy", "sell"]
    assert orders.quantity.tolist() == [5.0, 5.0]
    assert pd.to_datetime(orders.date).dt.normalize().tolist() == [days[-1], days[-1]]
    assert orders.reason.tolist() == ["top_n", "period_end"]
    assert summary["years"][0]["unclosed_positions"] == 0
    assert summary["years"][1]["unclosed_positions"] == 0
    equity = pd.read_csv(tmp_path / "equity_curve.csv")
    assert equity.loc[equity.year.eq(2020), "Equity"].iloc[0] == 20_000


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


@pytest.mark.parametrize("key,value,message", [
    ("slippage_bps", True, "slippage_bps"),
    ("slippage_bps", -1, "slippage_bps"),
    ("signal_lag_days", 2, "signal_lag_days must be 1"),
])
def test_backtest_cost_and_lag_settings_are_validated(local_dataset, key, value, message):
    config_path = local_dataset[3]
    invalid = yaml.safe_load(config_path.read_text())
    invalid["backtest"][key] = value
    config_path.write_text(yaml.safe_dump(invalid))
    with pytest.raises(ValueError, match=message):
        load_experiment_config(config_path)


@pytest.mark.parametrize("value,message", [
    (True, "max_participation"), (0, "max_participation"), ("missing", "max_participation"),
])
def test_participation_cap_setting_is_validated(local_dataset, value, message):
    config_path = local_dataset[3]
    invalid = yaml.safe_load(config_path.read_text())
    if value == "missing":
        del invalid["backtest"]["max_participation"]
    else:
        invalid["backtest"]["max_participation"] = value
    config_path.write_text(yaml.safe_dump(invalid))
    with pytest.raises(ValueError, match=message):
        load_experiment_config(config_path)


@pytest.mark.parametrize("value", [True, -1, "missing"])
def test_random_baseline_runs_must_be_set_explicitly(local_dataset, value):
    config_path = local_dataset[3]
    invalid = yaml.safe_load(config_path.read_text())
    if value == "missing":
        invalid["evaluation"].pop("random_baseline_runs", None)
    else:
        invalid["evaluation"]["random_baseline_runs"] = value
    config_path.write_text(yaml.safe_dump(invalid))
    with pytest.raises(ValueError, match="random_baseline_runs"):
        load_experiment_config(config_path)


@pytest.mark.parametrize("key,value", [("up_mult", 9.9), ("down_mult", 9.9), ("max_holding_days", 1)])
def test_backtest_barriers_must_match_the_label(local_dataset, key, value):
    config_path = local_dataset[3]
    config = load_experiment_config(config_path)
    invalid = yaml.safe_load(config_path.read_text())
    invalid["backtest"][key] = value
    config_path.write_text(yaml.safe_dump(invalid))
    with pytest.raises(ValueError, match="must equal labels"):
        load_experiment_config(config_path)
    prices = bars([(100, 100, 100, 100)] * 6, code="005930")
    entries = signals(prices, [(1, "005930")])
    config["backtest"][key] = value
    with pytest.raises(ValueError, match="must equal labels"):
        simulate(config, entries, prices)


def test_fixed_labels_are_supported_for_training_but_rejected_by_execution(local_dataset):
    _, _, _, config_path = local_dataset
    settings = yaml.safe_load(config_path.read_text())
    settings["labels"] = {"type": "fixed", "horizon": 3, "tp": 5.0, "sl": 5.0}
    settings["backtest"]["max_holding_days"] = 3
    config_path.write_text(yaml.safe_dump(settings))
    config = load_experiment_config(config_path)

    prices = bars([(100, 100, 100, 100), (100, 106, 100, 100)] + [(100, 100, 100, 100)] * 2,
                  code="005930")
    price_dir = config_path.parent / "fixed-prices"
    atomic_parquet(price_dir / "005930.parquet", prices)
    training = load_parquet_data(price_dir, label_params=config["labels"], training=True)
    assert training.Y_Label.tolist() == [2]

    entries = signals(prices, [(1, "005930")])
    with pytest.raises(ValueError, match="dynamic_sigma"):
        simulate(config, entries, prices)
