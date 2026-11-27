"""Compare all factors with Qlib's file provider and inspect legacy model compatibility."""

import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd
from shared.features.builder import build_feature_frame as legacy_frame
from shared.features.builder import normalize_trading_halts
from shared.features.columns import BASE_FEATURES
from shared.features.qlib_alpha158 import generate_alpha158_features, local_name, upstream_identity
from shared.io import atomic_json
from shared.processing import QLIB_PREPROCESSING, build_feature_frame, processing_contract


def validation_cases():
    fixture = Path(__file__).parents[2] / "shared/tests/fixtures/v3-golden.json"
    cases = {}
    for case in json.loads(fixture.read_text())["cases"]:
        raw = pd.DataFrame(case["raw"])
        raw.Date = pd.to_datetime(raw.Date)
        cases[case["name"]] = normalize_trading_halts(raw, set(raw.Date.dt.date))
    normal = cases["normal"]
    flat = normal.copy()
    flat[["Open", "High", "Low", "Close", "VWAP"]] = 1000.0
    flat["Volume"] = 1000
    cases["flat"] = flat
    ties = flat.copy()
    ties["Close"] = np.resize([1000, 1000, 1020, 1000, 1020], len(ties))
    ties["High"] = ties.Close + 20
    ties["Low"] = ties.Close - 20
    ties["Volume"] = np.resize([0, 100, 100, 1000, 10000], len(ties))
    cases["ties_zero_volume"] = ties
    missing = normal.copy()
    missing.loc[[5, 6, 20], ["Close", "Volume"]] = np.nan
    cases["missing"] = missing
    for length in (1, 2, 5, 59, 60, 61):
        cases[f"short_{length}"] = normal.head(length).copy()
    return cases


def reference_provider(source, output):
    import qlib
    from qlib.contrib.data.loader import Alpha158DL
    from qlib.data import D

    frames = pd.read_parquet(source)
    with tempfile.TemporaryDirectory(prefix="alpha158-provider-") as directory:
        root = Path(directory)
        (root / "calendars").mkdir()
        dates = pd.DatetimeIndex(sorted(frames.Date.unique()))
        (root / "calendars/day.txt").write_text("\n".join(dates.strftime("%Y-%m-%d")) + "\n")
        for name, frame in frames.groupby("Case", sort=False):
            target = root / "features" / name
            target.mkdir(parents=True)
            for column in ("Open", "High", "Low", "Close", "Volume", "VWAP"):
                values = np.r_[np.float32(0), frame[column].to_numpy(dtype="float32")]
                values.astype("<f4").tofile(target / f"{column.lower()}.day.bin")
        qlib.init(provider_uri=str(root), expression_cache=None, dataset_cache=None,
                  kernels=1, joblib_backend="threading", exp_manager={
                      "class": "MLflowExpManager", "module_path": "qlib.workflow.expm",
                      "kwargs": {"uri": str(root / "mlruns"), "default_exp_name": "Alpha158"},
                  })
        fields, names = Alpha158DL.get_feature_config()
        results = []
        for name, frame in frames.groupby("Case", sort=False):
            result = D.features([name], fields, start_time=frame.Date.min(),
                                end_time=frame.Date.max(), disk_cache=0)
            result.columns = names
            result = result.droplevel("instrument").reset_index(names="Date")
            result["Case"] = name
            results.append(result)
        pd.concat(results, ignore_index=True).to_parquet(output, index=False)


def verify(output, pack=None):
    from qlib.contrib.data.loader import Alpha158DL

    cases = validation_cases()
    with tempfile.TemporaryDirectory(prefix="alpha158-parity-") as directory:
        source, reference = Path(directory) / "input.parquet", Path(directory) / "reference.parquet"
        pd.concat([frame.assign(Case=f"case{i}") for i, frame in enumerate(cases.values())],
                  ignore_index=True).to_parquet(source, index=False)
        environment = {**os.environ, "PYTHONPATH": str(Path(__file__).parents[2])}
        subprocess.run([sys.executable, "-m", __name__ if __name__ != "__main__" else
                        "experiments.features.verify_qlib_alpha158", "--reference-input", str(source),
                        "--reference-output", str(reference)], check=True, env=environment,
                       capture_output=True, text=True, timeout=120)
        expected = pd.read_parquet(reference)
    _, names = Alpha158DL.get_feature_config()
    columns = [local_name(name) for name in names]
    reports = []
    for i, (name, frame) in enumerate(cases.items()):
        actual = generate_alpha158_features(frame)
        reference = expected.loc[expected.Case.eq(f"case{i}"), names].reset_index(drop=True)
        reference.columns = columns
        pd.testing.assert_frame_equal(actual[columns].reset_index(drop=True), reference,
                                      check_exact=True)
        reports.append({"case": name, "rows": len(frame), "columns": len(columns),
                        "exact_match": True})
    differences = []
    raw = cases["normal"]
    days = set(raw.Date.dt.date)
    legacy, original = legacy_frame(raw, days), build_feature_frame(raw, days, QLIB_PREPROCESSING)
    for column in columns:
        a, b = legacy[column].to_numpy(float), original[column].to_numpy(float)
        equal = np.isclose(a, b, rtol=1e-6, atol=1e-8, equal_nan=True)
        mature = np.arange(len(raw)) >= 60
        if not equal.all():
            differences.append({"column": column, "different_rows": int((~equal).sum()),
                                "different_after_warmup": int((~equal & mature).sum()),
                                "nan_mask_differences": int((np.isnan(a) != np.isnan(b)).sum())})
    models = []
    if pack is not None:
        import lightgbm as lgb
        from serving.internal.inference import infer_batch
        from serving.internal.pack import load_pack

        manifest, paths, _ = load_pack(pack)
        for horizon, (model_path, _) in paths.items():
            model = lgb.Booster(model_file=str(model_path))
            names = model.feature_name()
            a = model.predict(legacy.loc[60:, names], validate_features=True)
            b = model.predict(original.loc[60:, names], validate_features=True)
            score = infer_batch(model_path, legacy.tail(1))
            if len(score) != 1 or not np.isfinite(a).all() or not np.isfinite(b).all():
                raise AssertionError("Legacy model smoke inference failed")
            models.append({"horizon": horizon, "features": len(names),
                           "feature_order_matches": names == list(BASE_FEATURES) + [
                               name for name in names if name.startswith("flow_")],
                           "rows": len(a), "max_probability_difference": float(np.max(np.abs(a - b))),
                           "changed_predictions": int(np.any(a != b, axis=1).sum()),
                           "legacy_infer_batch_passed": True,
                           "compatible_with_original_values": False})
        pack_id = manifest["pack_id"]
    else:
        pack_id = None
    report = {"upstream": upstream_identity(), "processing_contract": processing_contract(QLIB_PREPROCESSING),
              "parity": reports, "comparison_tolerance": {"rtol": 1e-6, "atol": 1e-8},
              "legacy_differences": differences, "pack_id": pack_id, "models": models,
              "scope": "Synthetic price and flow fixtures. Prediction changes do not measure forecast quality."}
    atomic_json(output, report)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--pack", type=Path)
    parser.add_argument("--reference-input", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--reference-output", type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.reference_input:
        reference_provider(args.reference_input, args.reference_output)
    elif args.output:
        report = verify(args.output, args.pack)
        print(json.dumps({"parity_cases": len(report["parity"]), "models": report["models"],
                          "report": str(args.output)}))
    else:
        parser.error("--output is required")


if __name__ == "__main__":
    main()
