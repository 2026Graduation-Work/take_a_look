"""Internal preview output, not the frozen chart_output v1 contract.

Prices can be exported without a model. Inference consumes an explicitly selected
feature snapshot: it never trains, regenerates labels, or imports experiments.
"""

import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd


def price_snapshot(frame, code, as_of, source):
    """Export observed bars only; do not forward-fill missing sessions."""
    required = {"Date", "Close", "Volume"}
    if not required.issubset(frame.columns):
        raise ValueError(f"Missing price columns: {sorted(required - set(frame.columns))}")
    prices = frame.copy()
    prices["Date"] = pd.to_datetime(prices["Date"], errors="raise").dt.normalize()
    cutoff = pd.Timestamp(as_of).normalize()
    prices = prices.loc[prices.Date <= cutoff].sort_values("Date")
    if prices.empty or prices.Date.duplicated().any():
        raise ValueError("Empty price history or duplicate dates")
    values = prices[["Close", "Volume"]].to_numpy(dtype=float)
    if not np.isfinite(values).all() or (values[:, 0] <= 0).any() or (values[:, 1] < 0).any():
        raise ValueError("Prices must be positive and volumes nonnegative, all finite")
    last = prices.iloc[-1]
    history = prices.tail(60)
    return {
        "code": str(code),
        "requested_asof": cutoff.date().isoformat(),
        "data_asof": last.Date.date().isoformat(),
        "status": "available" if last.Date == cutoff else "stale",
        "source": source,
        "price_basis": "adjusted_close",
        "close": float(last.Close),
        "volume": float(last.Volume),
        "change_percent": (
            float((last.Close / prices.iloc[-2].Close - 1) * 100)
            if len(prices) >= 2 else None
        ),
        "history": [
            {"date": row.Date.date().isoformat(), "close": float(row.Close),
             "volume": float(row.Volume)}
            for row in history.itertuples()
        ],
    }


def predict_snapshot(model, features, code, as_of, *, allow_missing=False):
    """Return class scores and signed class-2 raw-margin contributions.

Use model-embedded feature names/order, including any historical barrier
features. A caller must select a feature snapshot compatible with that model.
"""
    frame = features.copy()
    frame["Date"] = pd.to_datetime(frame["Date"], errors="raise").dt.normalize()
    row = frame.loc[frame.Date == pd.Timestamp(as_of).normalize()]
    if len(row) != 1:
        raise ValueError("Exactly one feature row is required for the requested date")
    names = model.feature_name()
    missing = set(names) - set(row.columns)
    if missing:
        raise ValueError(f"Missing model features: {sorted(missing)}")
    x = row[names].astype(float)
    if np.isinf(x.to_numpy()).any() or (not allow_missing and x.isna().any().any()):
        raise ValueError("Nonfinite model features")
    scores = np.asarray(model.predict(x), dtype=float)
    if (scores.shape != (1, 3) or not np.isfinite(scores).all()
            or (scores < 0).any() or (scores > 1).any()
            or not np.isclose(scores.sum(), 1)):
        raise ValueError("Expected three normalized scores: down, neutral, up")
    contributions = np.asarray(model.predict(x, pred_contrib=True), dtype=float)
    if contributions.shape != (1, 3 * (len(names) + 1)):
        raise ValueError("Unexpected multiclass contribution shape")
    if not np.isfinite(contributions).all():
        raise ValueError("Nonfinite model contributions")
    up = contributions.reshape(3, len(names) + 1)[2]
    top = sorted(range(len(names)), key=lambda i: (-abs(up[i]), names[i]))[:3]
    return {
        "code": str(code), "data_asof": pd.Timestamp(as_of).date().isoformat(),
        "scores": dict(zip(("down", "neutral", "up"), scores[0].tolist())),
        "score_event": "triple_barrier_class_2",
        "contribution_space": "class_2_raw_margin",
        "top_features": [
            {"feature": names[i], "value": None if pd.isna(x.iloc[0, i]) else float(x.iloc[0, i]),
             "contribution": float(up[i])}
            for i in top
        ],
        "return_distribution": {"status": "unavailable", "reason": "oos_artifact_required"},
    }


def rank_predictions(rows):
    """Midrank percentile within the explicitly exported universe, ties preserved."""
    if not rows:
        return []
    if len({row["data_asof"] for row in rows}) != 1:
        raise ValueError("Cannot rank predictions from different dates")
    if len({row["code"] for row in rows}) != len(rows):
        raise ValueError("Duplicate prediction codes")
    values = pd.Series([row["scores"]["up"] for row in rows])
    # One stock/all ties is the middle, never a fabricated top-1% signal.
    ranks = (values.rank(method="average") - 0.5) / len(values)
    return [dict(row, rank_percentile=float(rank), ranking_population=len(rows))
            for row, rank in zip(rows, ranks)]


def write_artifact(payload, destination):
    """Strict JSON + atomic replacement; hash covers the full deterministic payload."""
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, allow_nan=False)
    envelope = dict(payload, artifact_hash=hashlib.sha256(canonical.encode()).hexdigest())
    path = Path(destination)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(envelope, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)
