"""Empirical distribution for an explicitly selected OOS score bucket.

No label generation or backtest here. The research pipeline supplies audited
fixed-horizon returns, including the agreed handling of halts and delistings.
"""

import numpy as np
import pandas as pd


def build_distribution(samples, *, as_of, model_version, horizon_days,
                       score_low, score_high, min_samples=100, bins=12, ci_level=0.68):
    """Band and histogram use exactly the same mature, OOS sample.

Input return_pct is 100 * (adjusted_close[t+H]/adjusted_close[t] - 1).
Input outcome_class uses the model release's first-barrier label rule.
Score buckets are [low, high), except the final bucket includes score 1.
The default sample threshold is a preview policy, not statistical certification.
"""
    if not (0 <= score_low < score_high <= 1 and 0 < ci_level < 1):
        raise ValueError("Invalid score bucket or interval level")
    if min_samples < 1 or bins < 1 or horizon_days < 1:
        raise ValueError("Counts and horizon must be positive")
    required = {"code", "prediction_date", "training_end", "outcome_date",
                "model_version", "horizon_days", "score", "outcome_class", "return_pct"}
    if not required.issubset(samples.columns):
        raise ValueError(f"Missing OOS columns: {sorted(required - set(samples.columns))}")
    frame = samples.copy()
    if frame[list(required)].isna().any().any():
        raise ValueError("Null OOS fields")
    for key in ("prediction_date", "training_end", "outcome_date"):
        frame[key] = pd.to_datetime(frame[key], errors="raise").dt.normalize()
    if frame.duplicated(["code", "prediction_date"]).any():
        raise ValueError("Duplicate OOS observations")
    if not (frame.model_version == model_version).all():
        raise ValueError("Model versions cannot be mixed")
    if not (frame.horizon_days == horizon_days).all():
        raise ValueError("Horizons cannot be mixed")
    if (frame.training_end >= frame.prediction_date).any():
        raise ValueError("In-sample observations are not allowed")
    if ((frame.outcome_date <= frame.prediction_date).any()
            or (frame.outcome_date > pd.Timestamp(as_of)).any()):
        raise ValueError("Returns must be fully observed as of the artifact date")
    numbers = frame[["score", "return_pct"]].to_numpy(dtype=float)
    if (not np.isfinite(numbers).all() or not frame.score.between(0, 1).all()
            or (frame.return_pct < -100).any()):
        raise ValueError("Invalid scores or return percentages")
    if not frame.outcome_class.isin([0, 1, 2]).all():
        raise ValueError("Outcome class must be 0, 1 or 2")
    selected = frame.loc[(frame.score >= score_low) & (
        (frame.score <= score_high) if score_high == 1 else (frame.score < score_high)
    )]
    result = {
        "model_version": model_version, "horizon_days": horizon_days,
        "data_asof": pd.Timestamp(as_of).date().isoformat(),
        "return_definition": "adjusted_close_to_close_fixed_horizon_percent",
        "event_definition": "upper_barrier_first_within_horizon",
        "cohort_definition": "same_model_horizon_score_bucket_only",
        "score_bucket": {"low": score_low, "high": score_high},
        "sample_count": len(selected), "minimum_samples": min_samples,
    }
    if len(selected) < min_samples:
        return dict(result, status="insufficient_samples", return_band=None, histogram=[])
    returns = selected.return_pct.to_numpy(dtype=float)
    tail = (1 - ci_level) / 2
    low, high = np.quantile(returns, [tail, 1 - tail])
    counts, edges = np.histogram(returns, bins=bins)
    return dict(
        result, status="available",
        period_start=selected.prediction_date.min().date().isoformat(),
        period_end=selected.prediction_date.max().date().isoformat(),
        sample_dates=int(selected.prediction_date.nunique()),
        sample_stocks=int(selected.code.nunique()),
        bucket_hit_rate=float((selected.outcome_class == 2).mean()),
        positive_return_rate=float((returns > 0).mean()),
        return_band={"low": float(low), "high": float(high), "ci_level": ci_level},
        histogram=[{"from": float(left), "to": float(right), "count": int(count)}
                   for left, right, count in zip(edges[:-1], edges[1:], counts)],
        histogram_interval="[from,to); final bin includes right edge",
    )
