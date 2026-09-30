"""Observed return histogram from matching walk-forward scores and Sigma."""

import math

import numpy as np
import pandas as pd

POLICY_ID = "multi_stock_up_sigma_001_005_v1"
TOLERANCES = {"up_absolute": 0.01, "sigma_relative": 0.05}
HISTOGRAM_STEP_PCT = 2


class SampleIndex:
    def __init__(self, samples):
        required = {"code", "prediction_date", "outcome_date", "horizon", "fold", "score", "sigma", "return_pct"}
        if required - set(samples):
            raise ValueError(f"Missing sample columns: {sorted(required - set(samples))}")
        self.samples = samples.copy()
        for key in ("prediction_date", "outcome_date"):
            self.samples[key] = pd.to_datetime(self.samples[key])
        if self.samples.duplicated(["code", "prediction_date", "horizon"]).any():
            raise ValueError("Duplicate sample key")
        numbers = self.samples[["score", "sigma", "return_pct"]].to_numpy(dtype=float)
        if not np.isfinite(numbers).all() or not self.samples.score.between(0, 1).all() or (self.samples.sigma < 0).any():
            raise ValueError("Invalid historical sample number")
        self.samples = self.samples.sort_values(["horizon", "score"]).reset_index(drop=True)
        self.by_horizon = {}
        for horizon, group in self.samples.groupby("horizon", sort=True):
            self.by_horizon[int(horizon)] = group.reset_index(drop=True)

    def select(self, *, horizon, score, sigma, as_of):
        if not math.isfinite(score) or not 0 <= score <= 1 or not math.isfinite(sigma) or sigma < 0:
            raise ValueError("Invalid current score or Sigma")
        frame = self.by_horizon.get(horizon)
        if frame is None:
            raise ValueError("No samples for horizon")
        values = frame.score.to_numpy(dtype=float)
        # Include decimal-looking boundaries despite one ULP of binary float error.
        low = np.searchsorted(values, np.nextafter(score - .01, -np.inf), side="left")
        high = np.searchsorted(values, np.nextafter(score + .01, np.inf), side="right")
        narrowed = frame.iloc[low:high]
        cutoff = pd.Timestamp(as_of)
        selected = narrowed.loc[
            narrowed.sigma.ge(np.nextafter(sigma * .95, -np.inf))
            & narrowed.sigma.le(np.nextafter(sigma * 1.05, np.inf))
            & narrowed.prediction_date.lt(cutoff)
            & narrowed.outcome_date.le(cutoff)
        ]
        return selected

    def distribution(self, *, horizon, score, sigma, as_of):
        selected = self.select(horizon=horizon, score=score, sigma=sigma, as_of=as_of)
        base = {"status": "available" if len(selected) else "no_cases", "reason": None,
                "policy_id": POLICY_ID, "current": {"up": float(score), "sigma": float(sigma)},
                "tolerances": TOLERANCES,
                "sample_count": len(selected), "stock_count": int(selected.code.nunique()),
                "period_start": selected.prediction_date.min().date().isoformat() if len(selected) else None,
                "period_end": selected.prediction_date.max().date().isoformat() if len(selected) else None,
                "observed_through": selected.outcome_date.max().date().isoformat() if len(selected) else None,
                "by_fold": {str(int(k)): int(v) for k, v in selected.groupby("fold").size().items()}}
        if not len(selected):
            return dict(base, histogram={"bins": [], "central_68": None})
        returns = selected.return_pct.to_numpy(dtype=float)
        band = np.quantile(returns, [.16, .84])
        step = HISTOGRAM_STEP_PCT
        left = math.floor(float(returns.min()) / step) * step
        right = max(left + step, math.ceil(float(returns.max()) / step) * step)
        counts, edges = np.histogram(returns, bins=np.arange(left, right + step, step))
        bins = [{"left": float(a), "right": float(b), "count": int(n)}
                for a, b, n in zip(edges[:-1], edges[1:], counts)]
        if sum(item["count"] for item in bins) != len(selected):
            raise ValueError("Histogram count mismatch")
        return dict(base, histogram={"bins": bins,
                                     "central_68": {"low": float(band[0]), "high": float(band[1])}})
