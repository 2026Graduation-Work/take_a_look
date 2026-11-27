"""Freeze the common builder's expectations for a serving pack."""
import argparse
import json
import platform
import shlex
import subprocess
from pathlib import Path

import numpy as np
import pandas as pd
from shared.features.columns import BASE_FEATURES, FLOW_FEATURES
from shared.golden import check_coverage, compute
from shared.settings import BUILDER_ID, CHART_ROOT, PREPROCESSING, PRICE_BASIS

DEFAULT_INPUTS = Path("shared/tests/fixtures/v3-golden.json")


def varied_candle_and_turnover(normal):
    raw = [row.copy() for row in normal["raw"]]
    selected_bar = 40
    for row in raw[:selected_bar]:
        row["AdjustmentFactor"] = 0.5
        for column in ("RawOpen", "RawHigh", "RawLow", "RawClose", "Amount"):
            row[column] *= 2
    raw[selected_bar]["High"] += 4
    raw[selected_bar]["RawHigh"] = raw[selected_bar]["High"]
    return {"name": "corporate_event", "kind": "corporate_event", "raw": raw,
            "rows": sorted({*normal["rows"], 29, 30, selected_bar - 1, selected_bar, selected_bar + 1})}


def generate(pack_id, inputs, out, *, model_features=None):
    cases = [{"name": case["name"], "kind": case.get("kind", case["name"]),
              "raw": case["raw"], "rows": case["rows"]}
             for case in json.loads(Path(inputs).read_text())["cases"]]
    if Path(inputs).resolve() == CHART_ROOT / DEFAULT_INPUTS:
        cases.append(varied_candle_and_turnover(next(case for case in cases if case["name"] == "normal")))
    names = [*BASE_FEATURES, *FLOW_FEATURES]
    for case, values in zip(cases, compute(cases, names), strict=True):
        case["expected"] = np.where(np.isnan(values), None, values).tolist()
    command = shlex.join(["python", "-m", "experiments.export.golden", "--pack-id", pack_id,
                          "--inputs", str(inputs), "--out", str(out)])
    commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=CHART_ROOT, text=True).strip()
    golden = {"pack_id": pack_id, "builder_id": BUILDER_ID, "price_basis": PRICE_BASIS,
              "preprocessing": dict(PREPROCESSING), "generated_from_commit": commit,
              "generation": {"command": command, "python": platform.python_version(),
                             "pandas": pd.__version__, "numpy": np.__version__},
              "tolerance": {"rtol": 1e-8, "atol": 1e-10}, "feature_names": names, "cases": cases}
    check_coverage(golden, names if model_features is None else model_features)
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(golden, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pack-id", required=True)
    parser.add_argument("--inputs", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    generate(args.pack_id, args.inputs, args.out)


if __name__ == "__main__":
    main()
