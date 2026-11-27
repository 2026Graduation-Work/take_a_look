import hashlib
from pathlib import Path

import lightgbm as lgb
import numpy as np
import pandas as pd
import pytest
import yaml
from experiments.config import load_experiment_config
from experiments.dataset.pipeline import preprocess_dataset, training_metadata
from experiments.features.local_panel import prepare_local_panel
from experiments.run_inference import init_worker, parse_args, process_ticker, resolve_model_path
from shared.data import trading_calendar
from shared.data.market_notices import SecurityKey
from shared.data.market_resolutions import Resolution
from shared.data.resolution_snapshot import PRICE_POLICY, read_resolution_snapshot, segment_id
from shared.features.columns import BASE_FEATURES
from shared.io import atomic_json, atomic_parquet, sha256
from shared.processing import QLIB_PREPROCESSING, build_feature_frame, processing_contract
from shared.settings import TRAINING_PRICE_BASIS
from shared.tests.official_fixtures import fake_isin, fixture_snapshot
from test_local_pipeline_contract import local_dataset as local_dataset


@pytest.fixture
def research_model(tmp_path, request):
    columns = [*BASE_FEATURES, *getattr(request, "param", ())]
    features = pd.DataFrame({name: 1.0 for name in columns}, index=range(120))
    features["beta_5"] = np.linspace(-0.1, 0.1, len(features))
    labels = np.digitize(features.beta_5, [-0.03, 0.03])
    model = lgb.train(
        {"objective": "multiclass", "num_class": 3, "verbosity": -1, "num_threads": 1},
        lgb.Dataset(features, label=labels),
        num_boost_round=3,
    )
    model_path = tmp_path / "model.txt"
    model.save_model(model_path)
    manifest_path = model_path.with_suffix(".txt.manifest.json")
    manifest = {
        "kind": "model",
        "feature_columns": model.feature_name(),
        "sha256": sha256(model_path),
        "processing_contract": processing_contract(QLIB_PREPROCESSING),
    }
    atomic_json(manifest_path, manifest)
    return model_path, model, manifest_path, manifest


def test_resolve_model_path_from_registry(tmp_path):
    model_path = tmp_path / "model.txt"
    model_path.write_bytes(b"model")
    sha256 = hashlib.sha256(b"model").hexdigest()
    registry_path = tmp_path / "registry.yaml"
    registry_path.write_text(
        yaml.safe_dump(
            {"models": {"aggressive": {"model_file": "model.txt", "sha256": sha256}}}
        ),
        encoding="utf-8",
    )

    assert resolve_model_path("aggressive", registry_path=registry_path) == str(model_path)


def test_resolve_model_path_rejects_sha_mismatch(tmp_path):
    (tmp_path / "model.txt").write_bytes(b"model")
    registry_path = tmp_path / "registry.yaml"
    registry_path.write_text(
        yaml.safe_dump(
            {"models": {"stable": {"model_file": "model.txt", "sha256": "wrong"}}}
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="SHA-256 불일치"):
        resolve_model_path("stable", registry_path=registry_path)


@pytest.mark.parametrize(
    "arguments",
    [
        ["--threshold", "-0.1"],
        ["--threshold", "1.1"],
        ["--threshold", "nan"],
        ["--workers", "0"],
        ["--workers", "-1"],
        ["--top-n", "0"],
        ["--top-n", "-1"],
    ],
)
def test_parse_args_rejects_invalid_numeric_contract(arguments):
    with pytest.raises(SystemExit):
        parse_args(arguments)


def test_parse_args_accepts_numeric_boundaries():
    assert parse_args(["--threshold", "0", "--workers", "1", "--top-n", "1"]).threshold == 0
    assert parse_args(["--threshold", "1"]).threshold == 1


def test_parse_args_accepts_research_raw_directory(tmp_path):
    assert parse_args(["--raw-dir", str(tmp_path)]).raw_dir == str(tmp_path)


def test_parse_args_requires_explicit_legacy_model_opt_in():
    assert parse_args([]).legacy_model is False
    assert parse_args(["--legacy-model"]).legacy_model is True


@pytest.mark.parametrize(
    ("field", "value", "error"),
    [
        ("kind", "dataset", "Invalid model manifest"),
        ("sha256", "changed", "Invalid model manifest"),
        ("feature_columns", ["ma_5"], "Model feature order differs"),
        ("processing_contract", None, "Model processing contract mismatch"),
    ],
)
def test_worker_rejects_changed_model_sidecar(research_model, field, value, error):
    model_path, _, manifest_path, manifest = research_model
    if field == "processing_contract":
        manifest[field]["sha256"] = "changed"
    else:
        manifest[field] = value
    atomic_json(manifest_path, manifest)
    with pytest.raises(ValueError, match=error):
        init_worker(model_path, legacy_without_manifest=True)


def test_worker_predicts_with_qlib_contract_or_explicit_legacy_defaults(
    local_dataset, research_model, monkeypatch,
):
    raw, dataset, _, _ = local_dataset
    model_path, model, manifest_path, _ = research_model
    path = Path(dataset["root"]) / "raw/005930.parquet"
    target = raw.Date.iloc[150]
    dates_requested = []

    def get_trading_days(start, end):
        dates_requested.append((pd.Timestamp(start), pd.Timestamp(end)))
        return raw.loc[raw.Date.between(start, end), "Date"]

    monkeypatch.setattr(trading_calendar, "get_krx_trading_days", get_trading_days)
    init_worker(model_path)
    qlib_result = process_ticker(path, str(target.date()), 0.5)
    history = raw.loc[raw.Date.le(target)]
    qlib_features = build_feature_frame(history, history.Date, QLIB_PREPROCESSING)
    qlib_score = model.predict(qlib_features[model.feature_name()].tail(1), num_threads=1)[0, 2]
    assert qlib_result["Model_Score"] == pytest.approx(qlib_score)
    assert qlib_result["Date"] == str(target.date())
    assert dates_requested == []

    manifest_path.unlink()
    with pytest.raises(ValueError, match="Missing model manifest"):
        init_worker(model_path)
    init_worker(model_path, legacy_without_manifest=True)
    atomic_parquet(path, raw.drop(columns="SegmentId"))
    legacy_result = process_ticker(path, str(target.date()), 0.5)
    tail = history.tail(85)
    legacy_features = build_feature_frame(tail, tail.Date)
    legacy_score = model.predict(legacy_features[model.feature_name()].tail(1), num_threads=1)[0, 2]
    assert legacy_result["Model_Score"] == pytest.approx(legacy_score)
    assert legacy_result["Model_Score"] != pytest.approx(qlib_result["Model_Score"])
    assert dates_requested == [(tail.Date.iloc[0], target)]


@pytest.mark.parametrize("history", ["first_listing", "relisted", "segment_break"])
def test_qlib_inference_matches_training_panel_after_60_rows(
    local_dataset, research_model, tmp_path, monkeypatch, history,
):
    raw, config, _, experiment_path = local_dataset
    model_path, model, _, _ = research_model
    root = tmp_path / "qlib"
    days = raw.Date
    start = 0 if history == "first_listing" else 100
    sessions = pd.DatetimeIndex(days.iloc[: start + 61])
    code = "005930"
    isin = fake_isin(code)
    first, boundary = sessions[0].date().isoformat(), sessions[start].date().isoformat()
    active = SecurityKey(code, isin, first, None, "KOSPI", "common")
    keys, events = [active], []
    current = raw.iloc[: len(sessions)].copy()
    if history == "relisted":
        prior = SecurityKey(code, isin, first, sessions[70].date().isoformat(), "KOSPI", "common")
        active = SecurityKey(code, isin, boundary, None, "KOSPI", "common")
        keys = [prior, active]
        current = pd.concat([current.iloc[:70], current.iloc[start:]], ignore_index=True)
    elif history == "segment_break":
        events = [(boundary, Resolution.SEGMENT_BREAK, None, None)]
    current.loc[current.Date.ge(sessions[start]), "SegmentId"] = segment_id(active, boundary)
    path = root / "raw/005930.parquet"
    atomic_parquet(path, current)
    calendar = {"validation_version": 3, "trading_days": sessions.strftime("%Y-%m-%d").tolist()}
    atomic_json(root / "calendar.json", calendar)
    snapshot = read_resolution_snapshot(fixture_snapshot(root, [code], sessions, keys=keys, events=events))
    atomic_json(root / "dataset_manifest.json", {
        "price_basis": TRAINING_PRICE_BASIS,
        "prices_complete": True,
        "raw_files": {path.name: sha256(path)},
        "price_policy": PRICE_POLICY,
        "official_actions": snapshot.provenance,
    })
    config["collection"]["end_date"] = sessions[-1].date().isoformat()
    training_metadata(snapshot, config["collection"], calendar).to_csv(root / "ticker_metadata.csv", index=False)
    dataset_path = tmp_path / "qlib.yaml"
    dataset_path.write_text(yaml.safe_dump({
        **config, "root": str(root), "dataset_id": "qlib", "preprocessing": "qlib_alpha158",
    }))
    experiment = yaml.safe_load(experiment_path.read_text())
    experiment["dataset"] = str(dataset_path)
    end = sessions[-1].date().isoformat()
    experiment["data"].update(
        end_date=end,
        splits=[{"fold_id": 0, "train_start": first, "train_end": "2023-01-13",
                 "test_start": "2023-02-01", "test_end": end}],
    )
    experiment["features"] = {"groups": [], "include": model.feature_name()}
    experiment_path.write_text(yaml.safe_dump(experiment))
    preprocess_dataset(dataset_path)
    resolved = load_experiment_config(experiment_path)
    prepare_local_panel(resolved)
    panel = pd.read_parquet(Path(resolved["data"]["price_dir"]) / path.name)

    def unexpected_provider(*args):
        pytest.fail("Qlib inference must use its stored calendar")

    monkeypatch.setattr(trading_calendar, "get_krx_trading_days", unexpected_provider)
    init_worker(model_path)
    target = str(days.iloc[start + 60].date())
    assert not panel.SampleEligible.iloc[-2]
    assert panel.SampleEligible.iloc[-1]
    assert process_ticker(path, str(days.iloc[start + 59].date()), 0.5) is None
    result = process_ticker(path, target if history == "relisted" else None, 0.5)
    expected = model.predict(panel[model.feature_name()].tail(1), num_threads=1)[0, 2]
    assert result["Date"] == target
    assert result["Model_Score"] == pytest.approx(expected)


def test_qlib_inference_reports_missing_metadata(local_dataset, research_model, capsys):
    _, dataset, _, _ = local_dataset
    model_path, _, _, _ = research_model
    root = Path(dataset["root"])
    (root / "ticker_metadata.csv").unlink()
    init_worker(model_path)
    assert process_ticker(root / "raw/005930.parquet", None, 0.5) is None
    error = capsys.readouterr().err
    assert "005930" in error
    assert "ticker_metadata.csv" in error


@pytest.mark.parametrize("disqualifier", ["halt", "sigma", "flow"])
@pytest.mark.parametrize("research_model", [("flow_individual_5",)], indirect=True)
def test_qlib_inference_skips_ineligible_latest_sample(local_dataset, research_model, capsys, disqualifier):
    raw, dataset, _, _ = local_dataset
    model_path, _, _, _ = research_model
    path = Path(dataset["root"]) / "raw/005930.parquet"
    init_worker(model_path)
    assert process_ticker(path, None, 0.5) is not None

    if disqualifier == "flow":
        raw.loc[raw.index[-1], "Individual_BuyAmount"] = np.nan
    else:
        halted = raw.index[-1:] if disqualifier == "halt" else raw.index[-20:-1]
        raw.loc[halted, ["Volume", "RawVolume", "Amount"]] = 0
    atomic_parquet(path, raw)
    assert process_ticker(path, None, 0.5) is None
    assert not capsys.readouterr().err
