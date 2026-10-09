"""Serving inputs use the same causal builder as the corrected local models."""

import pandas as pd
from core.local_features import build_feature_frame as build_local_features
from core.local_features import (  # noqa: F401
    generate_full_alpha158_features,
    normalize_trading_halts,
)
from experiments.features.flow import build_flow_features

SETTINGS = {"sigma_window": 20, "sigma_min_periods": 10,
            "barrier_feature_up_mult": 1.5, "barrier_feature_down_mult": 1.2}
BUILDER_ID = "local_v3_uniform_ohlc_flow_v1"


def build_feature_frame(raw, trading_days):
    if "VWAP" not in raw:
        raise ValueError("Actual VWAP is required")
    frame = build_local_features(raw, trading_days, SETTINGS)
    if "Amount" in raw and "Code" in raw:
        days = pd.to_datetime(sorted(trading_days))
        flow = build_flow_features(raw, days).drop(columns=["Code", "AvailableDate"])
        frame = frame.drop(columns=[c for c in flow if c.startswith("flow_")], errors="ignore")
        frame = frame.merge(flow, on="Date", how="left", validate="one_to_one")
    return frame
