"""One v3 processing definition for experiments and serving."""
from pathlib import Path

from .features.columns import BASE_FEATURES, FLOW_FEATURES
from .io import canonical_hash, sha256

CHART_ROOT = Path(__file__).resolve().parents[1]
CONTRACT_VERSION = VALIDATION_VERSION = 3
PRICE_BASIS = "krx_raw_ohlc_uniform_close_ratio_v1"
BUILDER_ID = "shared_v3_uniform_ohlc_flow_v1"
PREPROCESSING = {"sigma_window": 20, "sigma_min_periods": 10,
                 "barrier_feature_up_mult": 1.5, "barrier_feature_down_mult": 1.2}
IMPLEMENTATIONS = ("settings.py", "io.py", "data/providers.py", "data/prices.py",
                   "data/metadata.py", "data/krx.py", "data/calendar.py", "data/trading_calendar.py", "data/validation.py",
                   "data/bulk_prices.py", "features/builder.py", "features/flow.py", "features/columns.py")


def processing_contract(settings=None):
    payload = {"contract_version": CONTRACT_VERSION, "builder_id": BUILDER_ID,
               "price_basis": PRICE_BASIS, "preprocessing": dict(PREPROCESSING if settings is None else settings),
               "base_feature_columns": list(BASE_FEATURES), "flow_feature_columns": list(FLOW_FEATURES),
               "implementation_sha256": {name: sha256(Path(__file__).parent / name) for name in IMPLEMENTATIONS}}
    return {**payload, "sha256": canonical_hash(payload)}


def serving_root():
    import os
    return Path(os.environ.get("CHART_SERVING_DATA_DIR", CHART_ROOT / "workspace/serving"))
