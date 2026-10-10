"""Research compatibility functions using local causal features and shared labels."""

from shared.features.builder import (
    generate_full_alpha158_features as generate_full_alpha158_features,
)
from shared.features.builder import normalize_trading_halts as normalize_trading_halts


def calculate_dynamic_triple_barrier(df, horizon=5, up_mult=1.5, down_mult=1.2):
    from experiments.train_src.labels import apply_dynamic_sigma_barrier_labeling
    from shared.features.builder import add_sigma_barriers
    from shared.settings import PREPROCESSING
    settings = {**PREPROCESSING, "barrier_feature_up_mult": up_mult, "barrier_feature_down_mult": down_mult}
    if "Trading_Halt" not in df:
        df = df.assign(Trading_Halt=0)
    df = add_sigma_barriers(df, settings)
    df["Y_Label"] = apply_dynamic_sigma_barrier_labeling(df, horizon, up_mult, down_mult)
    return df
