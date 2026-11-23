from __future__ import annotations

import math
from collections.abc import Iterable

import numpy as np
import pandas as pd


def expected_calibration_error(
    y_true: Iterable[int], probabilities: Iterable[float], bins: int = 10
) -> float:
    if bins < 2:
        raise ValueError("calibration bins must be at least 2")
    actual = np.asarray(list(y_true), dtype=float)
    predicted = np.asarray(list(probabilities), dtype=float)
    if len(actual) == 0 or len(actual) != len(predicted):
        raise ValueError("calibration inputs must be non-empty and have equal length")
    boundaries = np.linspace(0.0, 1.0, bins + 1)
    bucket_ids = np.minimum(np.digitize(predicted, boundaries[1:-1]), bins - 1)
    return float(
        sum(
            (bucket_ids == bucket).mean()
            * abs(predicted[bucket_ids == bucket].mean() - actual[bucket_ids == bucket].mean())
            for bucket in range(bins)
            if (bucket_ids == bucket).any()
        )
    )


def select_volatile_dates(
    frame: pd.DataFrame,
    *,
    date_column: str,
    volatility_column: str,
    fraction: float = 0.2,
) -> tuple[pd.DatetimeIndex, float]:
    if not 0.0 < fraction <= 1.0:
        raise ValueError("volatile fraction must be in (0, 1]")
    daily_volatility = frame.groupby(date_column, sort=True)[volatility_column].mean()
    if daily_volatility.empty:
        raise ValueError("cannot select volatile dates from an empty test set")
    count = max(1, math.ceil(len(daily_volatility) * fraction))
    ranked = (
        daily_volatility.rename("volatility")
        .reset_index()
        .sort_values(["volatility", date_column], ascending=[False, True], kind="stable")
        .head(count)
    )
    return pd.DatetimeIndex(ranked[date_column].sort_values()), float(
        ranked["volatility"].min()
    )
