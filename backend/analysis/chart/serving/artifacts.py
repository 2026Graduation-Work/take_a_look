"""Audit imported experiment files without importing experiment code."""

import hashlib
import json
from pathlib import Path

import lightgbm as lgb
import numpy as np
import pandas as pd
import yaml

from serving.release import sha256_file

CHART = Path(__file__).resolve().parents[1]
INPUTS = {5: ("38753398", "sliding_2019_2025_h5.yaml"),
          20: ("568d2288", "sliding_2019_2025_h20.yaml")}


def prediction_cache_key(config, root):
    """Independent check of the research cache naming rule, without importing it."""
    data = config["data"]
    source_dir = root / data["price_dir"]
    digest = hashlib.sha256()
    files = sorted(source_dir.rglob("*.parquet"))
    for path in files:
        stat = path.stat()
        digest.update(str(path.relative_to(source_dir)).encode())
        digest.update(f"{stat.st_size}:{stat.st_mtime_ns}".encode())
    splits = [{"fold_id": i, "train_start": f"{year-3}-01-01",
               "train_end": f"{year-1}-12-31", "test_start": f"{year}-01-07",
               "test_end": f"{year}-12-31"} for i, year in enumerate(range(2019, 2026))]
    payload = {
        "cache_schema_version": 2,
        "data": {"tickers": data.get("tickers"),
                 "universe_file_sha256": sha256_file(root / data["universe_file"]),
                 "universe": data.get("universe"), "price_dir": data.get("price_dir"),
                 "data_fingerprint": {"status": "available", "configured_version": data.get("version"),
                                      "file_count": len(files), "manifest_sha256": digest.hexdigest()},
                 "start_date": data.get("start_date"), "end_date": data.get("end_date"),
                 "split_strategy": data.get("split_strategy", "single"),
                 "embargo_days": data.get("embargo_days", 7), "splits": splits},
        "features": config.get("features", {}), "labels": config.get("labels", {}),
        "model": config.get("model", {}), "training": config.get("training", {}),
    }
    return hashlib.md5(json.dumps(payload, sort_keys=True).encode(), usedforsecurity=False).hexdigest()[:8]


def inspect_inputs(chart_root=CHART, *, strict=True):
    root = Path(chart_root)
    result = {"format": "chart_serving_inputs_v1", "horizons": {}}
    for horizon, (cache_key, config_name) in INPUTS.items():
        config_file = root / "experiments/configs" / config_name
        config = yaml.safe_load(config_file.read_text())
        if config["labels"]["horizon"] != horizon or not config["data"]["point_in_time"]:
            raise ValueError(f"Invalid historical config: {config_file}")
        if prediction_cache_key(config, root) != cache_key:
            raise ValueError(f"Config, processed file fingerprint and cache key disagree: H{horizon}")
        cache = root / "experiments/cache" / f"{cache_key}_predictions.parquet"
        predictions = pd.read_parquet(cache)
        if list(predictions.columns) != ["Date", "Code", "Prob"]:
            raise ValueError("Unexpected OOS cache columns")
        if predictions.duplicated(["Date", "Code"]).any():
            raise ValueError("Duplicate OOS predictions")
        if not predictions.Prob.between(0, 1).all():
            raise ValueError("Invalid OOS scores")
        calendar_file = root / "data/krx_trading_calendar.json"
        calendar = json.loads(calendar_file.read_text())
        if (calendar.get("source") != "KOSPI index trading days" or
            calendar.get("coverage_start") > "2019-01-01" or
            calendar.get("coverage_end") < "2025-12-31"):
            raise ValueError("Official calendar does not cover OOS period")
        official = pd.DatetimeIndex(pd.to_datetime(calendar["trading_days"]))
        issues = []
        non_session = ~predictions.Date.isin(official)
        if non_session.any():
            issues.append({"reason": "non_krx_prediction_date",
                           "rows": int(non_session.sum()),
                           "dates": int(predictions.loc[non_session, "Date"].nunique())})
        universe_path = root / config["data"]["universe_file"]
        universe = pd.read_csv(universe_path, dtype={"Code": str}, parse_dates=["ListingDate", "DelistingDate"])
        if universe.Code.duplicated().any():
            raise ValueError("Duplicate PIT listing interval codes")
        dated = predictions[["Date", "Code"]].merge(
            universe[["Code", "ListingDate", "DelistingDate"]], on="Code", how="left",
            validate="many_to_one")
        bad_pit = dated.ListingDate.isna() | dated.Date.lt(dated.ListingDate) | (
            dated.DelistingDate.notna() & dated.Date.ge(dated.DelistingDate))
        if bad_pit.any():
            issues.append({"reason": "pit_interval_violation", "rows": int(bad_pit.sum())})
        folds = []
        feature_names = None
        covered = pd.Series(False, index=predictions.index)
        for index, year in enumerate(range(2019, 2026)):
            start, end = f"{year}-01-07", f"{year}-12-31"
            mask = predictions.Date.between(start, end)
            if (covered & mask).any() or not mask.any():
                raise ValueError(f"Missing or overlapping OOS fold {horizon}/{year}")
            covered |= mask
            model_path = root / "experiments/train_src/cache/models" / f"{cache_key}_fold{index}_model.txt"
            model = lgb.Booster(model_file=str(model_path))
            names = model.feature_name()
            if feature_names is not None and names != feature_names:
                raise ValueError("Fold feature order differs")
            feature_names = names
            folds.append({"fold": index, "year": year, "train_end": f"{year-1}-12-31",
                          "test_start": start, "test_end": end, "prediction_rows": int(mask.sum()),
                          "model_file": str(model_path.resolve()), "model_sha256": sha256_file(model_path)})
        if not covered.all():
            raise ValueError("OOS predictions outside seven folds")
        result["horizons"][str(horizon)] = {
            "cache_key": cache_key,
            "profile": "aggressive" if horizon == 5 else "stable",
            "training_policy": config["experiment_name"],
            "config_file": str(config_file.resolve()), "config_sha256": sha256_file(config_file),
            "prediction_file": str(cache.resolve()), "prediction_sha256": sha256_file(cache),
            "calendar_sha256": sha256_file(calendar_file),
            "universe_sha256": sha256_file(universe_path),
            "processed_dir": str((root / "data/processed").resolve()),
            "raw_dir": str((root / "data/raw").resolve()),
            "feature_names": feature_names,
            "feature_names_sha256": hashlib.sha256(json.dumps(feature_names).encode()).hexdigest(),
            "feature_barriers": {"up_mult": 1.5, "down_mult": 1.2},
            "label_barriers": {"up_mult": config["labels"]["up_mult"],
                               "down_mult": config["labels"]["down_mult"]},
            "folds": folds,
            "issues": issues,
        }
        sample = pd.read_parquet(root / "data/processed/005930.parquet",
                                 columns=["Close", "Sigma", "Barrier_Up", "Barrier_Down"])
        sample = sample.loc[sample.Sigma.notna()].tail(30)
        if sample.empty or not np.allclose(sample.Barrier_Up,
                                           sample.Close * (1 + 1.5 * sample.Sigma)) or not np.allclose(
                                               sample.Barrier_Down, sample.Close * (1 - 1.2 * sample.Sigma)):
            issues.append({"reason": "feature_barrier_formula_unverified"})
        if strict and issues:
            raise ValueError(f"H{horizon} OOS input fails release audit: {issues}")
    return result


def validate_manifest(manifest):
    for horizon in (5, 20):
        item = manifest["horizons"][str(horizon)]
        if item.get("issues"):
            raise ValueError(f"H{horizon} input has unresolved audit issues: {item['issues']}")
        config = yaml.safe_load(Path(item["config_file"]).read_text())
        chart_root = Path(item["processed_dir"]).parents[1]
        if prediction_cache_key(config, chart_root) != item["cache_key"]:
            raise ValueError(f"H{horizon} processed input fingerprint changed")
        for key in ("config", "prediction"):
            if sha256_file(item[f"{key}_file"]) != item[f"{key}_sha256"]:
                raise ValueError(f"Modified {key} input for H{horizon}")
        for fold in item["folds"]:
            if sha256_file(fold["model_file"]) != fold["model_sha256"]:
                raise ValueError(f"Modified fold model for H{horizon}/{fold['year']}")


def audit_feature_equivalence(item, raw_dir, processed_dir, trading_days, codes):
    """Compare rebuilt past-only features with actual training snapshots."""
    from serving.features import build_feature_frame
    from serving.prices import load_prices

    names = item["feature_names"]
    comparisons = []
    for code in sorted(set(codes)):
        raw_path = Path(raw_dir) / f"{code}.parquet"
        training_path = Path(processed_dir) / f"{code}.parquet"
        raw = load_prices(raw_path)
        rebuilt = build_feature_frame(raw, trading_days)
        training = pd.read_parquet(training_path, columns=["Date", *names])
        joined = training.merge(rebuilt[["Date", *names]], on="Date", suffixes=("_old", "_new"),
                                validate="one_to_one")
        if joined.empty:
            raise ValueError(f"No shared training dates: {code}")
        old = joined[[f"{name}_old" for name in names]].to_numpy(dtype=float)
        new = joined[[f"{name}_new" for name in names]].to_numpy(dtype=float)
        if not np.allclose(old, new, rtol=1e-10, atol=1e-8, equal_nan=True):
            row, col = np.argwhere(~np.isclose(old, new, rtol=1e-10, atol=1e-8,
                                               equal_nan=True))[0]
            raise ValueError(f"Feature mismatch: {code}/{joined.Date.iloc[row]}/{names[col]}")
        comparisons.append({"code": code, "rows": len(joined),
                            "raw_sha256": sha256_file(raw_path),
                            "training_sha256": sha256_file(training_path)})
    if not comparisons:
        raise ValueError("No feature parity comparisons")
    return {"status": "passed", "rows_compared": sum(row["rows"] for row in comparisons),
            "model_sha256": item["folds"][-1]["model_sha256"],
            "feature_names_sha256": item["feature_names_sha256"],
            "inputs": comparisons}


def main(argv=None):
    import argparse

    parser = argparse.ArgumentParser(description="Audit seven-fold H5/H20 OOS inputs")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--strict", action="store_true", help="Exit on any release-blocking issue")
    args = parser.parse_args(argv)
    manifest = inspect_inputs(strict=args.strict)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({h: item["issues"] for h, item in manifest["horizons"].items()}))


if __name__ == "__main__":
    main()
