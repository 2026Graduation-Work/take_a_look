"""Rebuild recorded UI data with whole-feature shares; never publish to Supabase."""

import argparse
import json
from pathlib import Path

import lightgbm as lgb
import numpy as np
import pandas as pd

from .internal.distribution import SampleIndex
from .internal.hashing import canonical_hash
from .internal.inference import infer_batch
from .internal.pipeline import active_pack
from .publish_preview import load_preview


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--features", type=Path, required=True, help="Archived feature frame for the preview date")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    _, snapshots, _ = load_preview()
    _, paths = active_pack()
    frame = pd.read_parquet(args.features)
    rows = []
    for snapshot in snapshots:
        horizon = snapshot["horizon"]
        current = frame.loc[pd.to_datetime(frame.Date).eq(pd.Timestamp(snapshot["data_asof"]))]
        if len(current) != 1:
            raise ValueError("Expected exactly one archived input row on the preview date")
        model = lgb.Booster(model_file=str(paths[horizon][0]))
        scores, features, digest, total = infer_batch(model, current, class_index=2)[0]
        old = snapshot["inference"]
        if (not all(np.isclose(scores[k], old["scores"][k], rtol=0, atol=1e-10) for k in scores)
                or features != old["features"]):
            raise ValueError("Archived inputs do not reproduce the recorded prediction")
        snapshot["inference"]["contribution_abs_sum"] = total
        # Rebuilt input can differ in floating point representation; keep its own provenance.
        snapshot["sources"]["features_sha256"] = digest
        distribution = SampleIndex(pd.read_parquet(paths[horizon][1])).distribution(
            horizon=horizon, score=scores["up"], sigma=old["sigma"], as_of=snapshot["data_asof"])
        if distribution["sample_count"] != snapshot["distribution"]["sample_count"]:
            raise ValueError("Historical sample membership changed")
        snapshot["distribution"] = distribution
        rows.append({"batch_id": snapshot["batch_id"], "stock_code": snapshot["stock_code"],
                     "horizon": horizon, "payload": snapshot})
    local_batch_id = canonical_hash({"display_policy": "whole_feature_contribution_hist2_v1",
                                    "snapshots": [{k: v for k, v in s.items() if k != "batch_id"}
                                                  for s in snapshots]})
    for row in rows:
        row["batch_id"] = row["payload"]["batch_id"] = local_batch_id
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({"mode": "local_display_data", "snapshots": len(rows), "output": str(args.output)}))


if __name__ == "__main__":
    main()
