"""One label definition: future high/close, downside wins simultaneous touches."""

import numpy as np
import pandas as pd

LABEL_VERSION = 3


def barrier_labels(df, horizon, *, up_mult=None, down_mult=None, tp=None, sl=None):
    if not isinstance(horizon, int) or isinstance(horizon, bool) or horizon < 1:
        raise ValueError("horizon must be positive integer")
    dynamic = up_mult is not None
    if dynamic and "Sigma" not in df:
        raise ValueError("Dynamic labels require signal-time Sigma")
    sigma = df.Sigma.to_numpy(dtype=float) if dynamic else np.ones(len(df))
    up = df.Close.to_numpy(dtype=float) * (1 + (up_mult * sigma if dynamic else tp / 100))
    down = df.Close.to_numpy(dtype=float) * (1 - (down_mult * sigma if dynamic else sl / 100))
    n = len(df)
    high = df.High.to_numpy(dtype=float)
    close = df.Close.to_numpy(dtype=float)
    halt = df.get("Trading_Halt", pd.Series(0, index=df.index)).to_numpy() == 1
    search_limit = int(horizon * 2.5) if dynamic else horizon
    active_count = np.cumsum(~halt)
    hit_up = np.full(n, np.inf)
    hit_down = np.full(n, np.inf)
    valid_path = np.ones(n, dtype=bool)
    for distance in range(1, min(search_limit, n - 1) + 1):
        passed = active_count[distance:] - active_count[:-distance]
        active = ~halt[distance:] & (passed <= horizon)
        finite = np.isfinite(high[distance:]) & np.isfinite(close[distance:])
        valid_path[:-distance] &= ~active | finite
        first_up = active & finite & (high[distance:] >= up[:-distance])
        first_down = active & finite & (close[distance:] <= down[:-distance])
        hit_up[:-distance] = np.minimum(hit_up[:-distance], np.where(first_up, passed, np.inf))
        hit_down[:-distance] = np.minimum(
            hit_down[:-distance], np.where(first_down, passed, np.inf)
        )
    result = np.zeros(n, dtype=float)
    result[(hit_up < hit_down) & np.isfinite(hit_up)] = 1
    result[(hit_down <= hit_up) & np.isfinite(hit_down)] = -1
    window_end = np.minimum(np.arange(n) + search_limit, n - 1)
    matured = active_count[window_end] - active_count >= horizon
    known = matured & valid_path & ~halt & np.isfinite(sigma)
    if dynamic:
        known &= sigma > 0
    result[~known] = np.nan
    return pd.Series(result, index=df.index)


def apply_fixed_barrier_labeling(df, horizon, tp_pct, sl_pct):
    return barrier_labels(df, horizon, tp=tp_pct, sl=sl_pct)


def apply_dynamic_sigma_barrier_labeling(df, horizon, up_mult, down_mult):
    return barrier_labels(df, horizon, up_mult=up_mult, down_mult=down_mult)
