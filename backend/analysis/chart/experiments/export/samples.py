"""Join stored walk-forward scores to the next H actually traded price rows."""

from collections import Counter
from pathlib import Path

import numpy as np
import pandas as pd


def build_samples(prediction_file, processed_dir, horizon, *, calendar_days=None):
    if horizon not in (5, 20):
        raise ValueError("Only H5/H20 supported")
    predictions = pd.read_parquet(prediction_file)
    score = "prob_up" if "prob_up" in predictions else "Prob"
    if not {"Date", "Code", score} <= set(predictions):
        raise ValueError("Unexpected prediction columns")
    if "fold_id" in predictions and not predictions.fold_id.eq(pd.to_datetime(predictions.Date).dt.year - 2019).all():
        raise ValueError("Prediction fold/year mismatch")
    predictions = predictions[["Date", "Code", score]].rename(columns={score: "Prob"})
    if predictions.duplicated(["Code", "Date"]).any():
        raise ValueError("Duplicate prediction key")
    predictions["Date"] = pd.to_datetime(predictions.Date)
    if not np.isfinite(predictions.Prob.to_numpy(dtype=float)).all() or not predictions.Prob.between(0, 1).all():
        raise ValueError("Invalid prediction score")
    output = []
    excluded = Counter()
    official = set(pd.to_datetime(list(calendar_days))) if calendar_days is not None else None
    for code, group in predictions.groupby("Code", sort=True):
        path = Path(processed_dir) / f"{code}.parquet"
        if not path.is_file():
            excluded["missing_price_file"] += len(group)
            continue
        prices = pd.read_parquet(path, columns=["Date", "Close", "Trading_Halt", "Sigma"])
        prices.Date = pd.to_datetime(prices.Date)
        prices = prices.sort_values("Date").reset_index(drop=True)
        if prices.Date.duplicated().any():
            raise ValueError(f"Duplicate price date: {code}")
        indexed = prices.set_index("Date")
        joined = group.join(indexed, on="Date", how="left")
        valid = pd.Series(True, index=joined.index)
        def exclude(mask, reason):
            nonlocal valid
            rejected = valid & mask
            excluded[reason] += int(rejected.sum())
            valid &= ~mask
        if official is not None:
            exclude(~joined.Date.isin(official), "non_krx_prediction_date")
        exclude(joined.Close.isna(), "price_join_failure")
        exclude(joined.Sigma.isna(), "sigma_missing")
        exclude(joined.Trading_Halt.eq(1), "base_halted")
        numeric = np.isfinite(joined[["Close", "Sigma"]].fillna(0).to_numpy(dtype=float)).all(axis=1)
        numeric &= joined.Close.gt(0) & joined.Sigma.ge(0)
        exclude(~numeric, "invalid_base_number")
        group = joined.loc[valid].copy()
        if group.empty:
            continue
        # Outcomes use observed executable rows after normalization, skipping unavailable sessions.
        traded = prices.loc[prices.Trading_Halt.ne(1)].copy()
        dates = traded.Date.to_numpy()
        positions = np.searchsorted(dates, group.Date.to_numpy())
        target = positions + horizon
        complete = target < len(traded)
        excluded["observation_incomplete"] += int((~complete).sum())
        group = group.iloc[np.flatnonzero(complete)].copy()
        if group.empty:
            continue
        future = traded.iloc[target[complete]].reset_index(drop=True)
        good_future = np.isfinite(future.Close.to_numpy(dtype=float)) & future.Close.gt(0).to_numpy()
        excluded["invalid_future_price"] += int((~good_future).sum())
        group = group.iloc[np.flatnonzero(good_future)].reset_index(drop=True)
        future = future.iloc[np.flatnonzero(good_future)].reset_index(drop=True)
        if group.empty:
            continue
        years = group.Date.dt.year
        result = pd.DataFrame({
            "code": str(code), "prediction_date": group.Date,
            "horizon": horizon, "fold": years - 2019,
            "training_end": pd.to_datetime((years - 1).astype(str) + "-12-31"),
            "score": group.Prob.to_numpy(dtype=float),
            "sigma": group.Sigma.to_numpy(dtype=float),
            "outcome_date": future.Date,
            "return_pct": (future.Close.to_numpy(dtype=float) / group.Close.to_numpy(dtype=float) - 1) * 100,
        })
        output.append(result)
    if not output:
        raise ValueError("No completed historical samples")
    samples = pd.concat(output, ignore_index=True).sort_values(["score", "prediction_date", "code"])
    if samples.duplicated(["code", "prediction_date", "horizon"]).any():
        raise ValueError("Duplicate completed sample")
    report = {"prediction_rows": len(predictions), "sample_rows": len(samples),
              "excluded": {k: int(v) for k, v in sorted(excluded.items()) if v}}
    report["excluded_total"] = report["prediction_rows"] - report["sample_rows"]
    if sum(report["excluded"].values()) != report["excluded_total"]:
        raise ValueError("Historical exclusion counts do not reconcile")
    report["prediction_period"] = {"start": predictions.Date.min().date().isoformat(), "end": predictions.Date.max().date().isoformat()}
    report["completed_outcome_period"] = {"start": samples.outcome_date.min().date().isoformat(), "end": samples.outcome_date.max().date().isoformat()}
    report["partial_years"] = [2026] if predictions.Date.max().year == 2026 else []
    return samples.reset_index(drop=True), report
