"""Serving calls the common causal v3 builder directly."""
from shared.features.builder import build_feature_frame as build_feature_frame
from shared.features.builder import (  # noqa: F401
    generate_full_alpha158_features,
    normalize_trading_halts,
)
from shared.settings import BUILDER_ID  # noqa: F401
