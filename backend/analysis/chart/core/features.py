"""Research compatibility functions using local causal features and shared labels."""

import numpy as np
import pandas as pd

from .local_features import generate_full_alpha158_features as generate_full_alpha158_features
from .local_features import normalize_trading_halts as normalize_trading_halts


def calculate_dynamic_triple_barrier(df, horizon=5, up_mult=1.5, down_mult=1.2):
    from experiments.train_src.labels import apply_dynamic_sigma_barrier_labeling

    df = df.copy()
    df["Log_Ret"] = np.log(df.Close / df.Close.shift(1))
    halt = df.get("Trading_Halt", pd.Series(0, index=df.index))
    df.loc[halt.eq(1), "Log_Ret"] = 0.0
    df["Sigma"] = df.Log_Ret.where(halt.eq(0)).rolling(20, min_periods=10).std()
    df["Barrier_Up"] = df.Close * (1 + up_mult * df.Sigma)
    df["Barrier_Down"] = df.Close * (1 - down_mult * df.Sigma)
    df["Y_Label"] = apply_dynamic_sigma_barrier_labeling(df, horizon, up_mult, down_mult)
    return df
