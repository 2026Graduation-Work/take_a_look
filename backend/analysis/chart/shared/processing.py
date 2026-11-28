import re
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


def processing_compatibility(contract):
    fields = ("contract_version", "builder_id", "price_basis", "preprocessing",
              "base_feature_columns", "flow_feature_columns")
    if not isinstance(contract, dict):
        raise ValueError("Missing processing contract")
    payload = {name: value for name, value in contract.items() if name != "sha256"}
    digest = contract.get("sha256")
    lineage = payload.get("implementation_sha256")
    required = {*fields, "implementation_sha256"}
    if (not required <= payload.keys() or payload.keys() - required - {"upstream"}
            or canonical_hash(payload) != digest
            or not isinstance(lineage, dict) or "features/builder.py" not in lineage
            or not all(isinstance(value, str) and re.fullmatch(r"[a-f0-9]{64}", value)
                       for value in lineage.values())):
        raise ValueError("Invalid processing contract")
    compatibility = {name: payload[name] for name in fields}
    if "upstream" in payload:
        upstream = payload["upstream"]
        keys = ("package", "version", "input_dtype")
        if not isinstance(upstream, dict) or not set(keys) <= upstream.keys():
            raise ValueError("Invalid processing engine contract")
        compatibility["upstream"] = {name: upstream[name] for name in keys}
    return compatibility


def processing_compatible(recorded, expected):
    try:
        return processing_compatibility(recorded) == processing_compatibility(expected)
    except (TypeError, ValueError):
        return False


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
