"""Current-value-centered, same-stock OOS case selection."""

import math
from decimal import Decimal

import numpy as np
import pandas as pd

POLICY_ID = "same_stock_up_down_001_sigma_rel010_v1"
TOLERANCES = {"up_absolute": 0.01, "down_absolute": 0.01, "sigma_relative": 0.1}


def _within(values, center, width):
    """Compare full decimal representations; do not round model outputs."""
    target, limit = Decimal(str(center)), Decimal(str(width))
    return values.map(lambda value: abs(Decimal(str(value)) - target) <= limit)


def matching_cases(ledger: pd.DataFrame, *, code: str, horizon: int, up: float,
                   down: float, sigma: float, as_of: str, policy_id: str = POLICY_ID):
    """Return a deterministic selected frame and its summary; 0 and 1 are valid."""
    if policy_id != POLICY_ID or horizon not in (5, 20):
        raise ValueError("Unsupported cohort policy or horizon")
    if not all(math.isfinite(v) for v in (up, down, sigma)) or not (
        0 <= up <= 1 and 0 <= down <= 1 and up + down <= 1 + 1e-12 and sigma >= 0
    ):
        raise ValueError("Invalid current model outputs or Sigma")
    required = {"Code", "Date", "horizon", "policy_id", "p_up", "p_down", "Sigma",
                "up_hit", "down_hit", "observed_through", "fold"}
    if required - set(ledger):
        raise ValueError(f"Missing ledger fields: {sorted(required - set(ledger))}")
    rows = ledger.loc[
        ledger.Code.eq(code) & ledger.horizon.eq(horizon) & ledger.policy_id.eq(policy_id)
    ].copy()
    if rows.duplicated(["Code", "Date", "horizon"]).any():
        raise ValueError("Duplicate historical case keys")
    if not rows.empty:
        numeric = rows[["p_up", "p_down", "Sigma"]].to_numpy(dtype=float)
        if not np.isfinite(numeric).all() or (numeric < 0).any():
            raise ValueError("Invalid historical outputs or Sigma")
        # Date and observation end must both precede the query cutoff.
        dates = pd.to_datetime(rows.Date)
        completed = pd.to_datetime(rows.observed_through)
        cutoff = pd.Timestamp(as_of)
        rows = rows.loc[
            dates.between("2019-01-01", "2025-12-31") & dates.lt(cutoff) & completed.le(cutoff)
            & _within(rows.p_up, up, "0.01")
            & _within(rows.p_down, down, "0.01")
            & _within(rows.Sigma, sigma, Decimal(str(sigma)) * Decimal("0.10"))
        ].sort_values(["Date", "fold"]).reset_index(drop=True)
    count = len(rows)
    up_count = int(rows.up_hit.sum()) if count else 0
    down_count = int(rows.down_hit.sum()) if count else 0
    both_count = int((rows.up_hit & rows.down_hit).sum()) if count else 0
    neither = count - up_count - down_count + both_count
    summary = {
        "status": "available" if count else "no_cases", "reason": None,
        "policy_id": POLICY_ID, "current": {"up": up, "down": down, "sigma": sigma},
        "tolerances": TOLERANCES.copy(), "sample_count": count,
        "up_count": up_count, "down_count": down_count,
        "both_count": both_count, "neither_count": neither,
        "up_rate": up_count / count if count else None,
        "down_rate": down_count / count if count else None,
        "period_start": pd.Timestamp(rows.Date.min()).date().isoformat() if count else None,
        "period_end": pd.Timestamp(rows.Date.max()).date().isoformat() if count else None,
        "observed_through": pd.Timestamp(rows.observed_through.max()).date().isoformat() if count else None,
        "by_fold": {str(key): int(value) for key, value in rows.fold.value_counts().sort_index().items()},
        "by_year": {str(key): int(value) for key, value in
                    pd.to_datetime(rows.Date).dt.year.value_counts().sort_index().items()},
    }
    assert up_count + down_count - both_count + neither == count
    return rows, summary
