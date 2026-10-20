"""Export completed H5/H20 A predictions and verified horizon returns, without retraining."""

import argparse
import json
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd
from experiments.experiment_utils import resolve_splits
from experiments.export_performance import checked_manifest, paired_frames, validate_pair_contract
from experiments.train_src.labels import barrier_labels
from shared.io import sha256


def outcomes(prices, labels):
    """Use the label's non-halted sessions and bounded observation window for close returns."""
    prices = prices.sort_values("Date").reset_index(drop=True)
    if prices.Date.isna().any() or prices.Date.duplicated().any():
        raise ValueError("Invalid or duplicate price dates")
    if labels["type"] != "dynamic_sigma":
        raise ValueError("Only dynamic_sigma labels are supported")
    horizon = labels["horizon"]
    actual = barrier_labels(prices, horizon, up_mult=labels["up_mult"], down_mult=labels["down_mult"])
    active_count = prices.Trading_Halt.ne(1).to_numpy().cumsum()
    endpoint = np.searchsorted(active_count, active_count + horizon)
    valid = actual.notna().to_numpy() & (endpoint < len(prices))
    valid &= endpoint <= np.arange(len(prices)) + int(horizon * 2.5)
    selected = np.flatnonzero(valid)
    close = prices.Close.to_numpy(dtype=float)
    if (not np.isfinite(close[selected]).all() or (close[selected] <= 0).any()
            or (close[endpoint[selected]] <= 0).any()):
        raise ValueError("Return prices must be positive")
    result = prices[["Date", "Trading_Halt"]].copy()
    result["Y_Label"] = actual.map({-1: 0, 0: 1, 1: 2})
    result["return_date"] = pd.NaT
    result["forward_return"] = np.nan
    result.loc[selected, "return_date"] = prices.Date.to_numpy()[endpoint[selected]]
    result.loc[selected, "forward_return"] = close[endpoint[selected]] / close[selected] - 1
    return result


def attach_outcomes(predictions, prices, labels):
    result = predictions.merge(outcomes(prices, labels), on="Date", how="left",
                               validate="one_to_one", suffixes=("", "_recomputed"), indicator=True)
    if not result._merge.eq("both").all():
        raise ValueError("OOS price dates are missing")
    observed = result.Y_Label_recomputed.notna()
    if (not observed.equals(result.label_observed)
            or not result.loc[observed, "Y_Label"].eq(result.loc[observed, "Y_Label_recomputed"]).all()):
        raise ValueError("Recomputed labels differ from completed OOS labels")
    result["return_observed"] = result.forward_return.notna()
    return result.drop(columns=["Y_Label_recomputed", "_merge"])


def export(suite, output, input_evidence):
    if output.exists():
        raise FileExistsError(f"Export destination already exists: {output}")
    pinned = json.loads(input_evidence.read_text())
    status = checked_manifest(suite / "status.json", pinned["completion_status_sha256"])
    prepared = json.loads((suite / "prepared.json").read_text())
    if status["status"] != "complete" or not status["run_id"] == prepared["run_id"] == pinned["run_id"]:
        raise ValueError("A/B completion identities differ")
    manifests, frames, evidence = {}, {}, {}
    for name in ("h5_A", "h5_B", "h20_A", "h20_B"):
        files = status["completed"][f"{name}:ml"]
        oos = next(Path(p) for p in files if Path(p).name == "oos_history.parquet")
        for filename, digest in files.items():
            if sha256(Path(filename)) != digest:
                raise ValueError(f"Completed ML artifact changed: {Path(filename).name}")
        manifests[name] = checked_manifest(oos.parent / "run_manifest.json", pinned["run_manifest_sha256"][name])
        frames[name] = pd.read_parquet(oos)
        probabilities = frames[name][["prob_down", "prob_neutral", "prob_up"]].to_numpy(dtype=float)
        if (not np.isfinite(probabilities).all() or (probabilities < 0).any() or (probabilities > 1).any()
                or not np.allclose(probabilities.sum(axis=1), 1, rtol=0, atol=1e-10)):
            raise ValueError("Invalid class probabilities")
        evidence[name] = {"oos_sha256": files[str(oos)], "run_manifest_sha256": pinned["run_manifest_sha256"][name]}
    for h in (5, 20):
        validate_pair_contract(manifests[f"h{h}_A"], manifests[f"h{h}_B"])
        frames[f"h{h}_A"], _ = paired_frames(frames[f"h{h}_A"], frames[f"h{h}_B"])
        if manifests[f"h{h}_A"]["config"]["labels"]["horizon"] != h:
            raise ValueError("OOS horizon differs from run identity")
        frame = frames[f"h{h}_A"]
        memberships = np.zeros(len(frame), dtype=int)
        for split in resolve_splits(manifests[f"h{h}_A"]["config"]):
            if pd.Timestamp(split["train_end"]) >= pd.Timestamp(split["test_start"]):
                raise ValueError("Training overlaps OOS dates")
            inside = frame.Date.between(split["test_start"], split["test_end"])
            if not frame.loc[inside, "fold_id"].eq(split["fold_id"]).all():
                raise ValueError("OOS fold/date mismatch")
            memberships += inside.to_numpy()
        if not (memberships == 1).all():
            raise ValueError("Missing or overlapping OOS folds")
    # B's pinned inputs preserve the common price path; never substitute today's prices.
    root = Path(manifests["h5_B"]["config"]["data"]["price_dir"])
    if manifests["h20_B"]["config"]["data"]["price_dir"] != str(root):
        raise ValueError("H5/H20 B input stores differ")
    feature_manifest = checked_manifest(root / "feature_manifest.json", pinned["sigma_feature_manifest_sha256"])
    if feature_manifest["feature_columns"] != manifests["h5_B"]["feature_columns"]:
        raise ValueError("Price input feature contract differs")
    groups = {h: {code: part for code, part in frames[f"h{h}_A"].groupby("Code", sort=False)} for h in (5, 20)}
    parts = {5: [], 20: []}
    for filename, digest in sorted(feature_manifest["file_hashes"].items()):
        source = root / filename
        if sha256(source) != digest:
            raise ValueError(f"Feature input changed: {filename}")
        prices = pd.read_parquet(source, columns=["Date", "Code", "High", "Close", "Sigma", "Trading_Halt"])
        if not prices.Code.eq(source.stem).all():
            raise ValueError("Price file/code mismatch")
        for h in (5, 20):
            predictions = groups[h].pop(source.stem, None)
            if predictions is not None:
                parts[h].append(attach_outcomes(predictions, prices, manifests[f"h{h}_A"]["config"]["labels"]))
    if any(groups.values()):
        raise ValueError("OOS stock price files are missing")
    report = {"run_id": status["run_id"], "input_evidence_sha256": sha256(input_evidence),
              "feature_manifest_sha256": pinned["sigma_feature_manifest_sha256"],
              "source_artifacts": evidence, "exporter_sha256": sha256(Path(__file__)),
              "label_implementation_sha256": sha256(Path(__file__).parent / "train_src/labels.py"),
              "return_definition": "Close[t+h non-halted sessions]/Close[t]-1; label search limit floor(2.5*h); no fees",
              "runs": {}}
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="oos-export-", dir=output.parent) as temporary:
        staging = Path(temporary) / "result"
        staging.mkdir()
        for h in (5, 20):
            result = pd.concat(parts[h], ignore_index=True).sort_values(["Date", "Code"]).reset_index(drop=True)
            if len(result) != len(frames[f"h{h}_A"]):
                raise ValueError("Export row count differs from completed OOS predictions")
            result["horizon"] = h
            path = staging / f"h{h}_A.parquet"
            result.to_parquet(path, index=False)
            report["runs"][f"h{h}_A"] = {"rows": len(result), "labeled_rows": int(result.label_observed.sum()),
                "return_rows": int(result.return_observed.sum()), "sha256": sha256(path),
                "labels": manifests[f"h{h}_A"]["config"]["labels"]}
        (staging / "manifest.json").write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n")
        staging.rename(output)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--suite-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--input-evidence", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(export(args.suite_dir, args.output_dir, args.input_evidence), indent=2))


if __name__ == "__main__":
    main()
