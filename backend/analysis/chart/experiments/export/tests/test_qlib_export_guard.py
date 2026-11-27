from pathlib import Path

import lightgbm as lgb
import numpy as np
import pandas as pd
import pytest
from experiments.export.pack import build_pack
from serving.internal import pack as serving_pack
from serving.internal.pack import load_pack
from serving.internal.storage import _pack_releases
from shared.features.columns import BASE_FEATURES
from shared.io import atomic_json, sha256_file
from shared.processing import QLIB_PREPROCESSING
from shared.processing import processing_contract as research_contract
from shared.settings import BUILDER_ID, processing_contract


@pytest.fixture
def pack_inputs(tmp_path):
    contract = processing_contract()
    days = pd.bdate_range("2019-01-02", periods=25)
    calendar = tmp_path / "calendar.json"
    atomic_json(calendar, {"trading_days": days.astype(str).tolist()})
    processed = tmp_path / "processed"
    processed.mkdir()
    pd.DataFrame({"Date": days, "Close": 100. + np.arange(len(days)),
                  "Trading_Halt": 0, "Sigma": .02}).to_parquet(processed / "005930.parquet")

    features = pd.DataFrame(np.tile(np.arange(15.)[:, None], (1, len(BASE_FEATURES))), columns=BASE_FEATURES)
    model = lgb.train({"objective": "multiclass", "num_class": 3, "num_threads": 1,
                       "min_data_in_leaf": 2, "verbosity": -1},
                      lgb.Dataset(features, label=np.arange(15) % 3), num_boost_round=1)
    models, predictions = {}, {}
    for horizon in (5, 20):
        models[horizon] = tmp_path / f"h{horizon}.txt"
        model.save_model(str(models[horizon]))
        predictions[horizon] = tmp_path / f"p{horizon}.parquet"
        pd.DataFrame({"Date": days[:1], "Code": "005930", "fold_id": 0,
                      "prob_up": .4}).to_parquet(predictions[horizon])

    period = {"start": "2019-01-02", "end": "2019-01-31"}
    provenance = {"feature_builder_id": BUILDER_ID, "processing_contract": contract,
                  "models": {f"h{h}": {"labels": {"up_mult": 1.5, "down_mult": 1.2}} for h in models},
                  "known_issues": [], "validation_status": "synthetic_test",
                  "training_period": period, "data_period": period}
    return {"pack_id": "fixture", "output": tmp_path / "packs", "models": models, "predictions": predictions,
            "processed_dir": processed, "calendar_file": calendar, "research_manifest": provenance}


def write_valid_sidecars(pack_inputs):
    contract = pack_inputs["research_manifest"]["processing_contract"]
    for kind in ("models", "predictions"):
        for path in pack_inputs[kind].values():
            atomic_json(f"{path}.manifest.json", {"sha256": sha256_file(path),
                        "feature_columns": list(BASE_FEATURES), "processing_contract": contract})


@pytest.mark.parametrize(("artifact", "changed", "message"), [
    ("models", "qlib", "processing contract"),
    ("models", "sha256", "checksum"),
    ("models", "feature_columns", "feature order"),
    ("predictions", "sha256", "checksum"),
    ("predictions", "contract", "processing contract"),
    ("predictions", "config", "processing contract"),
])
def test_export_rejects_mismatched_sidecar_before_creating_pack(pack_inputs, artifact, changed, message):
    path = pack_inputs[artifact][20]
    contract = pack_inputs["research_manifest"]["processing_contract"]
    write_valid_sidecars(pack_inputs)
    sidecar = {"sha256": sha256_file(path), "feature_columns": list(BASE_FEATURES),
               "processing_contract": contract}
    if changed == "qlib":
        sidecar["processing_contract"] = research_contract(QLIB_PREPROCESSING)
    elif changed == "sha256":
        sidecar["sha256"] = "0" * 64
    elif changed == "feature_columns":
        sidecar["feature_columns"].reverse()
    elif changed == "contract":
        sidecar["processing_contract"] = {**contract, "builder_id": "different"}
    elif changed == "config":
        sidecar["config"] = {"processing_contract": {**contract, "builder_id": "different"}}
    atomic_json(f"{path}.manifest.json", sidecar)

    with pytest.raises(ValueError, match=message):
        build_pack(**pack_inputs)
    assert not pack_inputs["output"].exists()


@pytest.mark.parametrize("with_sidecars", [False, True])
def test_export_preserves_legacy_pack_builds(pack_inputs, with_sidecars):
    if with_sidecars:
        contract = pack_inputs["research_manifest"]["processing_contract"]
        for horizon in (5, 20):
            model = pack_inputs["models"][horizon]
            prediction = pack_inputs["predictions"][horizon]
            atomic_json(f"{model}.manifest.json", {"sha256": sha256_file(model),
                        "feature_columns": list(BASE_FEATURES), "processing_contract": contract})
            sidecar = {"sha256": sha256_file(prediction), "config": {"processing_contract": contract}}
            if horizon == 5:
                sidecar["processing_contract"] = contract
            atomic_json(f"{prediction}.manifest.json", sidecar)

    root, archive, _ = build_pack(**pack_inputs, allow_legacy_artifacts=not with_sidecars)
    manifest, _, _ = load_pack(root)
    assert archive.is_file()
    assert manifest["processing_contract"] == pack_inputs["research_manifest"]["processing_contract"]


@pytest.mark.parametrize("artifact", ["models", "predictions"])
def test_export_requires_sidecars_unless_legacy_opt_in(pack_inputs, artifact):
    write_valid_sidecars(pack_inputs)
    Path(f"{pack_inputs[artifact][20]}.manifest.json").unlink()

    with pytest.raises(ValueError, match="Missing .* manifest"):
        build_pack(**pack_inputs)
    assert not pack_inputs["output"].exists()


def test_pack_load_rejects_changed_model_byte(pack_inputs):
    root, _, _ = build_pack(**pack_inputs, allow_legacy_artifacts=True)
    _, paths, _ = load_pack(root)
    model = paths[5][0]
    data = model.read_bytes()
    model.write_bytes(bytes([data[0] ^ 1]) + data[1:])

    with pytest.raises(ValueError, match="Missing or changed H5 model file"):
        load_pack(root)


@pytest.mark.parametrize("key", ["builder_id", "price_basis"])
def test_pack_load_rejects_incompatible_builder_contract(pack_inputs, key):
    root, _, _ = build_pack(**pack_inputs, allow_legacy_artifacts=True)
    manifest, _, _ = load_pack(root)
    manifest["processing_contract"][key] = "different"
    atomic_json(root / "manifest.json", manifest)

    with pytest.raises(ValueError, match="builder settings mismatch"):
        load_pack(root)


def test_pack_load_checks_bundled_and_configured_golden_checksums(pack_inputs):
    import tarfile

    root, archive, _ = build_pack(**pack_inputs, allow_legacy_artifacts=True)
    manifest, _, _ = load_pack(root)
    golden = root / "golden/fixture.json"
    with tarfile.open(archive) as tar:
        assert "fixture/golden/fixture.json" in tar.getnames()
    assert manifest["golden_sha256"] == sha256_file(golden)

    with pytest.raises(ValueError, match="configured and manifest golden checksums differ"):
        load_pack(root, golden_sha256="0" * 64)
    frozen = golden.read_bytes()
    golden.write_bytes(frozen + b"\n")
    with pytest.raises(ValueError, match="golden checksum mismatch"):
        load_pack(root)
    golden.unlink()
    with pytest.raises(ValueError, match="missing golden file"):
        load_pack(root)


def test_legacy_pack_keeps_registered_release_checksums(pack_inputs, monkeypatch, tmp_path):
    root, _, _ = build_pack(**pack_inputs, allow_legacy_artifacts=True)
    manifest, _, embedded_digest = load_pack(root)
    assert manifest.pop("golden_sha256") == embedded_digest
    atomic_json(root / "manifest.json", manifest)

    serving_dir = tmp_path / "serving"
    serving_dir.mkdir()
    (root / "golden").replace(serving_dir / "golden")
    config = serving_dir / "config.yaml"
    config.write_text(f"active_pack:\n  pack_id: {manifest['pack_id']}\n  golden_sha256: {embedded_digest}\n")
    monkeypatch.setattr(serving_pack, "SERVING_DIR", serving_dir)
    monkeypatch.setattr(serving_pack, "DEFAULT_CONFIG", config)

    verified, _, golden_sha256 = load_pack(root)
    assert golden_sha256 == embedded_digest
    assert verified == manifest
    assert _pack_releases(verified) == _pack_releases(manifest)
