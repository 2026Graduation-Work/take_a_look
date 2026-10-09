"""Build and locally activate corrected models from completed research runs."""

import argparse
import json
from pathlib import Path

import lightgbm as lgb
import numpy as np
import pandas as pd
import yaml
from core.local_config import atomic_json

from .internal.features import BUILDER_ID, build_feature_frame
from .internal.hashing import sha256_file
from .internal.inference import infer_batch
from .internal.pack import build_pack, load_pack
from .internal.prices import attach_actual_vwap

ROOT = Path(__file__).resolve().parents[1]


def verify_inputs(dataset, names):
    days = pd.to_datetime(json.loads((dataset / "calendar.json").read_text())["trading_days"])
    evidence = []
    cases = {"005930": None, "000040": None, "001527": "2024-03-28",
             "015540": "2016-03-25", "016380": "2016-02-16", "016385": "2016-02-16",
             "047810": "2017-10-11", "145210": "2025-03-21"}
    for code, target in cases.items():
        raw = pd.read_parquet(dataset / "raw" / f"{code}.parquet")
        as_of = pd.Timestamp(target) if target else pd.to_datetime(raw.Date).max()
        raw = raw.loc[pd.to_datetime(raw.Date).le(as_of)].copy()
        indexed = raw.set_index("Date")
        # Reconstruct a provider response, then exercise serving's actual price path.
        source = indexed[[f"Raw{c}" for c in ("Open", "High", "Low", "Close", "Volume")]+["Amount"]]
        supplied = indexed[["Open", "High", "Low", "Close", "Volume"]].copy()
        supplied["Change"] = supplied.Close.pct_change(fill_method=None) * 100
        attached = attach_actual_vwap(supplied, source).reset_index()
        for col in raw:
            if col not in attached:
                attached[col] = raw[col].to_numpy()
        rebuilt = build_feature_frame(attached, set(days.date))
        expected = pd.read_parquet(dataset / "processed" / f"{code}.parquet")
        expected = expected.loc[pd.to_datetime(expected.Date).eq(as_of)].iloc[0]
        actual = rebuilt.loc[rebuilt.Date.eq(as_of)].iloc[0]
        if not np.allclose(actual[names].to_numpy(dtype=float), expected[names].to_numpy(dtype=float),
                           rtol=1e-8, atol=1e-10, equal_nan=True):
            raise ValueError(f"Serving/training feature mismatch: {code}/{as_of.date()}")
        evidence.append({"code": code, "date": as_of.date().isoformat(), "features_match": len(names)})
    return evidence


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--h5-result", type=Path, required=True)
    parser.add_argument("--h20-result", type=Path, required=True)
    parser.add_argument("--pack-id", required=True)
    parser.add_argument("--activate", action="store_true", help="Update local serving config after validation")
    args = parser.parse_args(argv)
    manifests = {h: json.loads(p.joinpath("run_manifest.json").read_text())
                 for h, p in ((5, args.h5_result), (20, args.h20_result))}
    models, predictions, provenance = {}, {}, {}
    for h, manifest in manifests.items():
        cfg = manifest["config"]
        if cfg["features"]["groups"] != ["base"] or cfg["labels"]["horizon"] != h:
            raise ValueError("Expected corrected basic H5/H20 research runs")
        if cfg["data"]["sliding"]["end_year"] != 2026:
            raise ValueError("Expected latest completed 2026 fold")
        cache_hash = manifest["predictions_hash"]
        models[h] = ROOT / "experiments/train_src/cache/models" / f"{cache_hash}_fold7_model.txt"
        predictions[h] = ROOT / "experiments/cache" / f"{cache_hash}_predictions.parquet"
        model_meta = json.loads(models[h].with_suffix(".txt.manifest.json").read_text())
        if sha256_file(models[h]) != model_meta["sha256"]:
            raise ValueError("Research model checksum mismatch")
        model = lgb.Booster(model_file=str(models[h]))
        if model.feature_name() != manifest["feature_columns"]:
            raise ValueError("Research model feature mismatch")
        provenance[f"h{h}"] = {"run_manifest_sha256": sha256_file((args.h5_result if h==5 else args.h20_result)/"run_manifest.json"),
                                "prediction_hash": cache_hash, "model_sha256": model_meta["sha256"], "fold_id": 7}
    dataset = Path(manifests[5]["config"]["dataset"]["root"])
    if dataset != Path(manifests[20]["config"]["dataset"]["root"]):
        raise ValueError("H5/H20 dataset mismatch")
    names = manifests[5]["feature_columns"]
    evidence = verify_inputs(dataset, names)
    info = {"feature_builder_id": BUILDER_ID, "training_period": {"start": "2023-01-01", "end": "2025-12-31"},
            "validation_status": "local_price_feature_and_inference_checks_passed",
            "known_issues": ["Adjusted prices are current snapshots, not point-in-time archives.",
                             "Past KOSPI membership history is not fully verified.",
                             "These base models do not consume the separately collected investor-flow features."],
            "models": provenance, "feature_parity_cases": evidence}
    root = ROOT / "serving/data/packs" / args.pack_id
    if root.exists():
        existing, _ = load_pack(root)
        if existing.get("research_provenance") != info:
            raise ValueError("Existing pack has different research provenance")
        archive = root.parent / f"{args.pack_id}.tar.gz"
        if not archive.is_file():
            raise FileNotFoundError(archive)
        reports = json.loads((root / "build_report.json").read_text())
    else:
        root, archive, reports = build_pack(pack_id=args.pack_id, output=ROOT/"serving/data/packs",
                                           models=models, predictions=predictions, processed_dir=dataset/"processed",
                                           calendar_file=dataset/"calendar.json", research_manifest=info)
    pack, paths = load_pack(root)
    raw = pd.read_parquet(dataset/"raw/005930.parquet")
    dates = pd.to_datetime(raw.Date)
    raw = raw.loc[dates.le(dates.max())]
    days = pd.to_datetime(json.loads((dataset/"calendar.json").read_text())["trading_days"])
    features = build_feature_frame(raw, set(days.date)).tail(1)
    scores = {str(h): infer_batch(paths[h][0], features)[0][0] for h in (5,20)}
    atomic_json(root/"serving_check.json", {"feature_parity": evidence, "stock_code": "005930", "scores": scores})
    if args.activate:
        config_path = ROOT/"serving/config.yaml"
        previous = yaml.safe_load(config_path.read_text())
        if previous["active_pack"]["pack_id"] != args.pack_id:
            atomic_json(root/"previous_active_pack.json", previous)
        temporary = config_path.with_suffix(".yaml.tmp")
        temporary.write_text(yaml.safe_dump({"active_pack": {"pack_id": args.pack_id,
            "release_tag": "chart-serving-"+args.pack_id, "asset_name": archive.name,
            "sha256": sha256_file(archive)}},sort_keys=False))
        temporary.replace(config_path)
    print(json.dumps({"pack_id": args.pack_id, "archive": str(archive), "sha256": sha256_file(archive),
                      "activated_locally": args.activate, "reports": reports, "scores": scores}))


if __name__ == "__main__":
    main()
