import json

import numpy as np
import pandas as pd
import pytest
from experiments.features.verify_qlib_alpha158 import validation_cases, verify
from shared.features.builder import build_feature_frame as legacy_frame
from shared.features.columns import BASE_FEATURES, FLOW_FEATURES
from shared.features.qlib_alpha158 import generate_alpha158_features
from shared.processing import QLIB_PREPROCESSING, build_feature_frame, processing_contract
from shared.settings import processing_contract as legacy_contract


def test_all_158_factors_match_official_file_provider_exactly(tmp_path):
    output = tmp_path / "parity.json"
    report = verify(output)
    assert all(case["exact_match"] and case["columns"] == 158 for case in report["parity"])
    assert {case["case"] for case in report["parity"]} == set(validation_cases())
    assert json.loads(output.read_text())["upstream"]["version"] == "0.9.7"


def test_original_values_are_causal_and_cache_isolated():
    from qlib.data.cache import H

    raw = validation_cases()["normal"]
    columns = [c for c in BASE_FEATURES if c not in {"Change", "Barrier_Up", "Barrier_Down"}]
    cache = H["f"]
    before = set(cache.od)
    full = generate_alpha158_features(raw)
    prefix = generate_alpha158_features(raw.head(65))
    pd.testing.assert_frame_equal(full.loc[:64, columns], prefix[columns], check_exact=True)
    scaled = raw.copy()
    scaled[["Open", "High", "Low", "Close", "VWAP"]] *= 2
    changed = generate_alpha158_features(scaled)
    np.testing.assert_array_equal(full.beta_5, changed.beta_5)
    pd.testing.assert_frame_equal(full, generate_alpha158_features(raw), check_exact=True)
    assert set(cache.od) == before


def test_original_ties_warmup_and_zero_volume():
    flat = validation_cases()["flat"]
    features = generate_alpha158_features(flat)
    assert features.loc[4, "rank_5"] == pytest.approx(0.6)
    assert features.loc[4, "imax_5"] == pytest.approx(0.2)
    assert features.loc[4, "imin_5"] == pytest.approx(0.2)
    assert features.loc[0, "ma_60"] == 1
    assert pd.isna(features.loc[0, "std_60"])
    assert features.rsqr_5.isna().all()
    assert features.corr_5.isna().all()
    flat.Volume = 0
    features = generate_alpha158_features(flat)
    assert np.isfinite(features.vma_5).all()
    assert features.vma_5.eq(0).all()


def test_research_contract_preserves_legacy_and_non_alpha_inputs():
    raw = validation_cases()["normal"]
    days = set(raw.Date.dt.date)
    expected = legacy_frame(raw, days)
    pd.testing.assert_frame_equal(build_feature_frame(raw, days), expected, check_exact=True)
    original = build_feature_frame(raw, days, QLIB_PREPROCESSING)
    preserved = ["Date", "Close", "Volume", "VWAP", "Change", "Trading_Halt", "Sigma",
                 "Barrier_Up", "Barrier_Down", *FLOW_FEATURES]
    pd.testing.assert_frame_equal(original[preserved], expected[preserved], check_exact=True)
    assert [c for c in original if c in BASE_FEATURES and c not in
            {"Change", "Barrier_Up", "Barrier_Down"}] == list(BASE_FEATURES)[1:-2]
    assert processing_contract() == legacy_contract()
    assert processing_contract(QLIB_PREPROCESSING)["sha256"] != legacy_contract()["sha256"]
    assert not np.allclose(original.beta_5.iloc[60:], expected.beta_5.iloc[60:])


def test_qlib_contract_is_rejected_by_existing_serving_pack_gate():
    from serving.internal.pack import validate_builder

    contract = processing_contract(QLIB_PREPROCESSING)
    with pytest.raises(ValueError, match="builder settings mismatch"):
        validate_builder({"feature_builder_id": contract["builder_id"], "processing_contract": contract})


@pytest.mark.parametrize("problem", ["missing_vwap", "duplicate_dates", "unsorted_dates", "already_built"])
def test_original_rejects_ambiguous_source_rows(problem):
    raw = validation_cases()["normal"]
    if problem == "missing_vwap":
        raw = raw.drop(columns="VWAP")
    elif problem == "duplicate_dates":
        raw.loc[1, "Date"] = raw.loc[0, "Date"]
    elif problem == "unsorted_dates":
        raw = raw.iloc[::-1]
    else:
        raw["beta_5"] = 0
    with pytest.raises(ValueError):
        generate_alpha158_features(raw)
