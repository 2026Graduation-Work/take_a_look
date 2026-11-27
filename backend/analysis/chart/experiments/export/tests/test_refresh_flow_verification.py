import json
from pathlib import Path

import pandas as pd
import pytest
from experiments.dataset.pipeline import _require_current_training_prices, training_metadata
from experiments.export.refresh_pack import verify_inputs
from shared.data.calendar import scheduled_sessions
from shared.features.builder import build_feature_frame
from shared.features.columns import BASE_FEATURES, FLOW_FEATURES
from shared.io import atomic_json, sha256_file
from shared.settings import PREPROCESSING, TRAINING_PRICE_BASIS, processing_contract
from shared.tests.official_fixtures import NEW_POLICY, listing_segment, price_provenance


@pytest.mark.parametrize("case_name", ["current_contract", "tampered_flow", "stale_contract"])
def test_flow_training_values_and_missingness_are_verified(tmp_path, monkeypatch, case_name):
    from experiments.export import refresh_pack
    fixture = Path(__file__).parents[3] / "shared/tests/fixtures/v3-golden.json"
    case = next(c for c in json.loads(fixture.read_text())["cases"] if c["name"] == "flow_missing")
    raw = pd.DataFrame(case["raw"])
    start = pd.Timestamp(raw.Date.iloc[0])
    raw.Date = scheduled_sessions(start, start + pd.Timedelta(days=180))[:len(raw)]
    raw["Code"] = "005930"
    raw["SegmentId"] = listing_segment("005930", str(raw.Date.iloc[0].date()))
    panel = build_feature_frame(raw, set(raw.Date.dt.date))
    store = tmp_path / "training"
    for directory in (tmp_path / "raw", tmp_path / "processed", store):
        directory.mkdir()
    raw.to_parquet(tmp_path / "raw/005930.parquet", index=False)
    panel.drop(columns=list(FLOW_FEATURES)).to_parquet(tmp_path / "processed/005930.parquet", index=False)
    trained = panel.copy()
    if case_name == "tampered_flow":
        missing = trained.flow_foreign_20.isna()
        trained.loc[missing, "flow_foreign_20"] = 0.
    trained.to_parquet(store / "005930.parquet", index=False)
    raw_hashes = {"005930.parquet": sha256_file(tmp_path / "raw/005930.parquet")}
    provenance = price_provenance(tmp_path, ["005930"], pd.DatetimeIndex(raw.Date))
    collection = {"markets": ["KOSPI"], "include_delisted": True}
    manifest = {**provenance, "contract_version": 3, "prices_complete": True, "config": {"collection": collection},
                "price_basis": TRAINING_PRICE_BASIS, "raw_files": raw_hashes}
    atomic_json(tmp_path / "dataset_manifest.json", manifest)
    contract = processing_contract()
    if case_name == "stale_contract":
        contract["sha256"] = "0" * 64
    atomic_json(tmp_path / "processed_manifest.json", {**provenance, "settings": PREPROCESSING, "raw_files": raw_hashes,
                "dataset_manifest_sha256": sha256_file(tmp_path / "dataset_manifest.json"),
                "processing_contract": contract, "spac_excluded_rows": {},
                "files": {"005930.parquet": sha256_file(tmp_path / "processed/005930.parquet")}})
    calendar = {"trading_days": raw.Date.astype(str).tolist()}
    atomic_json(tmp_path / "calendar.json", calendar)
    training_metadata(_require_current_training_prices(manifest, tmp_path), collection, calendar).to_csv(
        tmp_path / "ticker_metadata.csv", index=False)

    # The golden fixture uses a synthetic calendar; real exports audit exchange sessions.
    monkeypatch.setattr(refresh_pack, "verify_calendar_schedule", lambda calendar: None)
    names = list(BASE_FEATURES) + list(FLOW_FEATURES)
    if case_name == "stale_contract":
        with pytest.raises(ValueError, match="processing contract mismatch"):
            verify_inputs(tmp_path, names, store)
    elif case_name == "tampered_flow":
        with pytest.raises(ValueError, match="flow feature mismatch"):
            verify_inputs(tmp_path, names, store)
    else:
        proof = verify_inputs(tmp_path, names, store)
        assert proof["flow_feature_columns"] == list(FLOW_FEATURES)
        assert proof["flow_incomplete_rows"] == int(panel[list(FLOW_FEATURES)].isna().any(axis=1).sum()) > 0


def test_flow_activation_refuses_incomplete_preview_before_config_write(tmp_path, monkeypatch):
    from experiments.export import refresh_pack
    dataset = tmp_path / "dataset"
    dataset.mkdir()
    atomic_json(dataset / "dataset_manifest.json", NEW_POLICY)
    atomic_json(dataset / "calendar.json", {"trading_days": ["2026-10-06"]})
    config = tmp_path / "serving/config.local.yaml"
    config.parent.mkdir()
    config.write_text("active_pack:\n  pack_id: previous\n")
    original = config.read_bytes()
    source = {"h5": {"feature_columns": list(BASE_FEATURES) + list(FLOW_FEATURES),
                      "training_feature_store": str(tmp_path), "official_actions": NEW_POLICY["official_actions"]},
              "h20": {"training_feature_store": str(tmp_path), "official_actions": NEW_POLICY["official_actions"]}}
    monkeypatch.setattr(refresh_pack, "CHART_ROOT", tmp_path)
    monkeypatch.setattr(refresh_pack, "verify_runs", lambda *args, **kwargs: ({}, {}, source, dataset))
    monkeypatch.setattr(refresh_pack, "verify_inputs", lambda *args: {"processed_manifest_sha256": "synthetic"})
    monkeypatch.setattr(refresh_pack, "build_pack", lambda **kwargs: (tmp_path, tmp_path / "pack.tar.gz", {}))
    monkeypatch.setattr(refresh_pack, "load_pack", lambda *args: ({}, {}, "a" * 64))
    monkeypatch.setattr(refresh_pack.pd, "read_parquet", lambda *args: pd.DataFrame())
    missing = pd.DataFrame({name: [0.] for name in FLOW_FEATURES})
    missing.loc[0, "flow_foreign_20"] = float("nan")
    monkeypatch.setattr(refresh_pack, "build_feature_frame", lambda *args: missing)
    with pytest.raises(ValueError, match="complete operational preview input"):
        refresh_pack.main(["--h5-result", "h5", "--h20-result", "h20", "--pack-id", "new",
                           "--with-flows", "--activate"])
    assert config.read_bytes() == original
