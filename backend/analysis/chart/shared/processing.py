from pathlib import Path

import numpy as np
import pandas as pd

from shared.features import builder as legacy
from shared.features.columns import BASE_FEATURES
from shared.features.qlib_alpha158 import ENGINE, generate_alpha158_features, upstream_identity
from shared.io import canonical_hash, sha256
from shared.settings import PREPROCESSING
from shared.settings import processing_contract as legacy_contract

QLIB_PREPROCESSING = {**PREPROCESSING, "feature_engine": ENGINE}


def processing_contract(settings=None):
    settings = dict(PREPROCESSING if settings is None else settings)
    engine = settings.get("feature_engine")
    if engine is None:
        return legacy_contract(settings)
    if engine != ENGINE:
        raise ValueError(f"Unsupported feature_engine: {engine}")
    contract = legacy_contract(settings)
    sources = {**contract["implementation_sha256"]}
    for name in ("processing.py", "features/qlib_alpha158.py"):
        sources[name] = sha256(Path(__file__).parent / name)
    payload = {key: value for key, value in contract.items() if key != "sha256"}
    payload.update(builder_id=ENGINE, implementation_sha256=sources, upstream=upstream_identity())
    return {**payload, "sha256": canonical_hash(payload)}


def build_feature_frame(raw, trading_days, settings=None):
    settings = dict(PREPROCESSING if settings is None else settings)
    engine = settings.get("feature_engine")
    if engine is None:
        return legacy.build_feature_frame(raw, trading_days, settings)
    if engine != ENGINE:
        raise ValueError(f"Unsupported feature_engine: {engine}")
    from shared.features.flow import build_flow_features

    frame = generate_alpha158_features(legacy.normalize_trading_halts(raw, trading_days))
    frame = legacy.add_sigma_barriers(frame, settings)
    if "Change" not in frame:
        frame["Change"] = frame.Close.pct_change(fill_method=None) * 100
    frame = frame.drop(columns=["Y_Label", "y_label"], errors="ignore")
    numeric = frame.select_dtypes(include="number").columns
    frame[numeric] = frame[numeric].replace([np.inf, -np.inf], np.nan)
    if "Amount" in raw and "Code" in raw:
        flow = build_flow_features(raw, pd.to_datetime(sorted(trading_days))).drop(columns=["Code", "AvailableDate"])
        frame = frame.drop(columns=[c for c in flow if c.startswith("flow_")], errors="ignore")
        frame = frame.merge(flow, on="Date", how="left", validate="one_to_one")
    alpha = [name for name in BASE_FEATURES if name not in {"Change", "Barrier_Up", "Barrier_Down"}]
    metadata = [name for name in frame if name not in alpha]
    return frame[[*metadata, *alpha]]
