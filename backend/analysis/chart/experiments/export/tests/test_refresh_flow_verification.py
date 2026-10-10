"""A flow pack must match its actual training inputs, including missing values."""
import json
from pathlib import Path

import pandas as pd
import pytest
from experiments.export.refresh_pack import verify_inputs
from shared.features.builder import build_feature_frame
from shared.features.columns import BASE_FEATURES, FLOW_FEATURES
from shared.io import atomic_json, sha256_file
from shared.settings import PREPROCESSING, PRICE_BASIS, processing_contract


@pytest.mark.parametrize("tampered", [False, True])
def test_flow_training_values_and_missingness_are_verified(tmp_path, monkeypatch, tampered):
    from experiments.export import refresh_pack
    fixture = Path(__file__).parents[3] / "shared/tests/fixtures/v3-golden.json"
    case = next(c for c in json.loads(fixture.read_text())["cases"] if c["name"] == "flow_missing")
    raw = pd.DataFrame(case["raw"])
    raw.Date = pd.to_datetime(raw.Date)
    raw["Code"] = "005930"
    panel = build_feature_frame(raw, set(raw.Date.dt.date))
    store = tmp_path / "training"
    for directory in (tmp_path / "raw", tmp_path / "processed", store):
        directory.mkdir()
    raw.to_parquet(tmp_path / "raw/005930.parquet", index=False)
    panel.drop(columns=list(FLOW_FEATURES)).to_parquet(tmp_path / "processed/005930.parquet", index=False)
    trained = panel.copy()
    if tampered:
        missing = trained.flow_foreign_20.isna()
        trained.loc[missing, "flow_foreign_20"] = 0.
    trained.to_parquet(store / "005930.parquet", index=False)
    raw_hashes = {"005930.parquet": sha256_file(tmp_path / "raw/005930.parquet")}
    atomic_json(tmp_path / "dataset_manifest.json", {"contract_version": 3, "prices_complete": True,
                "price_basis": PRICE_BASIS, "raw_files": raw_hashes})
    atomic_json(tmp_path / "processed_manifest.json", {"settings": PREPROCESSING, "raw_files": raw_hashes,
                "processing_contract": processing_contract(),
                "files": {"005930.parquet": sha256_file(tmp_path / "processed/005930.parquet")}})
    atomic_json(tmp_path / "calendar.json", {"trading_days": raw.Date.astype(str).tolist()})
    pd.DataFrame({"Code": ["005930"], "ListingDate": [raw.Date.min()], "DelistingDate": [pd.NaT]}).to_csv(
        tmp_path / "ticker_metadata.csv", index=False)
    # The golden fixture uses a synthetic calendar; real exports audit exchange sessions.
    monkeypatch.setattr(refresh_pack, "verify_calendar_schedule", lambda calendar: None)
    names = list(BASE_FEATURES) + list(FLOW_FEATURES)
    if tampered:
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
    atomic_json(dataset / "calendar.json", {"trading_days": ["2026-10-06"]})
    config = tmp_path / "serving/config.local.yaml"
    config.parent.mkdir()
    config.write_text("active_pack:\n  pack_id: previous\n")
    original = config.read_bytes()
    source = {"h5": {"feature_columns": list(BASE_FEATURES) + list(FLOW_FEATURES),
                      "training_feature_store": str(tmp_path)},
              "h20": {"training_feature_store": str(tmp_path)}}
    monkeypatch.setattr(refresh_pack, "CHART_ROOT", tmp_path)
    monkeypatch.setattr(refresh_pack, "verify_runs", lambda *args, **kwargs: ({}, {}, source, dataset))
    monkeypatch.setattr(refresh_pack, "verify_inputs", lambda *args: {})
    monkeypatch.setattr(refresh_pack, "build_pack", lambda **kwargs: (tmp_path, tmp_path / "pack.tar.gz", {}))
    monkeypatch.setattr(refresh_pack, "load_pack", lambda *args: ({}, {}))
    monkeypatch.setattr(refresh_pack.pd, "read_parquet", lambda *args: pd.DataFrame())
    missing = pd.DataFrame({name: [0.] for name in FLOW_FEATURES})
    missing.loc[0, "flow_foreign_20"] = float("nan")
    monkeypatch.setattr(refresh_pack, "build_feature_frame", lambda *args: missing)
    with pytest.raises(ValueError, match="complete operational preview input"):
        refresh_pack.main(["--h5-result", "h5", "--h20-result", "h20", "--pack-id", "new",
                           "--with-flows", "--activate"])
    assert config.read_bytes() == original
