"""Reconstruct OOS class outputs and independently observed cases."""

from pathlib import Path

import lightgbm as lgb
import numpy as np
import pandas as pd

from serving.artifacts import validate_manifest
from serving.barriers import observe_many
from serving.cohorts import POLICY_ID


def restore_fold(item, fold, *, codes=None, batch_size=30000):
    """Use that fold's model and the original processed feature snapshot."""
    model = lgb.Booster(model_file=fold["model_file"])
    names = model.feature_name()
    if names != item["feature_names"]:
        raise ValueError("Model feature order mismatch")
    cached = pd.read_parquet(item["prediction_file"])
    cached = cached.loc[cached.Date.between(fold["test_start"], fold["test_end"])]
    if codes is not None:
        cached = cached.loc[cached.Code.isin(codes)]
    if cached.duplicated(["Date", "Code"]).any():
        raise ValueError("Duplicate OOS keys")
    inputs, expected, meta, outputs = [], [], [], []
    size = 0

    def flush():
        nonlocal inputs, expected, meta, size
        if not inputs:
            return
        frame = pd.concat(inputs, ignore_index=True)[names]
        scores = np.asarray(model.predict(frame, num_threads=2), dtype=float)
        old = np.concatenate(expected)
        if scores.shape != (len(old), 3) or not np.isfinite(scores).all() or (
            (scores < 0).any() or (scores > 1).any()
            or not np.allclose(scores.sum(axis=1), 1, rtol=1e-6, atol=1e-8)
        ):
            raise ValueError("Invalid restored three-class output")
        if not np.allclose(scores[:, 2], old, rtol=1e-6, atol=1e-8):
            difference = np.max(np.abs(scores[:, 2] - old))
            raise ValueError(f"Fold {fold['fold']} up output disagrees with cache: {difference}")
        info = pd.concat(meta, ignore_index=True)
        info[["p_down", "p_neutral", "p_up"]] = scores
        outputs.append(info)
        inputs, expected, meta, size = [], [], [], 0

    for code, rows in cached.groupby("Code", sort=True):
        path = Path(item["processed_dir"]) / f"{code}.parquet"
        if not path.is_file():
            raise FileNotFoundError(path)
        available = pd.read_parquet(path, columns=["Date", "Close", "High", "Trading_Halt", "Sigma", *names])
        if available.Date.duplicated().any():
            raise ValueError(f"Duplicate processed dates: {code}")
        merged = rows[["Date", "Code", "Prob"]].merge(available, on="Date", validate="one_to_one")
        if len(merged) != len(rows):
            raise ValueError(f"Missing training-time feature snapshot: {code}")
        inputs.append(merged[names])
        expected.append(merged.Prob.to_numpy(dtype=float))
        meta.append(merged[["Date", "Code", "Close", "High", "Trading_Halt", "Sigma"]])
        size += len(merged)
        if size >= batch_size:
            flush()
    flush()
    restored = pd.concat(outputs, ignore_index=True) if outputs else pd.DataFrame()
    if codes is None and len(restored) != fold["prediction_rows"]:
        raise ValueError("Restored fold row count mismatch")
    restored["fold"] = fold["fold"]
    restored["horizon"] = int(item["horizon"])
    restored["model_sha256"] = fold["model_sha256"]
    restored["policy_id"] = POLICY_ID
    return restored


def build_ledger(manifest, horizon, out_dir, *, codes=None):
    """Persist reconstructed outputs, completed cases and excluded-row audit."""
    validate_manifest(manifest)
    item = dict(manifest["horizons"][str(horizon)], horizon=horizon)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    restored_parts, case_parts, excluded = [], [], []
    for fold in item["folds"]:
        restored = restore_fold(item, fold, codes=codes)
        restored_parts.append(restored)
    restored = pd.concat(restored_parts, ignore_index=True)
    for code, group in restored.groupby("Code", sort=True):
        processed = pd.read_parquet(Path(item["processed_dir"]) / f"{code}.parquet",
                                    columns=["Date", "Close", "High", "Trading_Halt", "Sigma"])
        observations = observe_many(processed, horizon)
        joined = group.merge(observations, on="Date", validate="one_to_one")
        if len(joined) != len(group):
            raise ValueError(f"Missing observation base date: {code}")
        for row in joined.loc[~joined.complete, ["Code", "Date", "reason"]].itertuples():
            excluded.append({"Code": row.Code, "Date": row.Date,
                             "horizon": horizon, "reason": row.reason})
        case_parts.append(joined.loc[joined.complete].drop(columns=["High", "Trading_Halt",
                                                                    "complete", "reason"]))
    ledger = pd.concat(case_parts, ignore_index=True)
    if ledger.duplicated(["Code", "Date", "horizon"]).any():
        raise ValueError("Duplicate ledger keys")
    restored.to_parquet(out_dir / f"oos_outputs_h{horizon}.parquet", index=False)
    ledger.to_parquet(out_dir / f"cases_h{horizon}.parquet", index=False)
    pd.DataFrame(excluded, columns=["Code", "Date", "horizon", "reason"]).to_csv(
        out_dir / f"excluded_h{horizon}.csv", index=False)
    return len(ledger), len(excluded)


def main(argv=None):
    import argparse
    import json

    parser = argparse.ArgumentParser(description="Restore fold OOS scores and completed cases")
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    manifest = json.loads(args.manifest.read_text())
    for horizon in (5, 20):
        count, excluded = build_ledger(manifest, horizon, args.out_dir)
        print(f"H{horizon}: {count} completed, {excluded} excluded")


if __name__ == "__main__":
    main()
