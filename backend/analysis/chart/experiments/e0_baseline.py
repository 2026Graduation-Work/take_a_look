"""E0: reproduce the v1.1.0 baseline metrics from shared OOS predictions and add return-based ranking metrics.

No training. Inputs are the Release `research-oos-2019-2025-20261021` (h5_A.parquet, h20_A.parquet)
and a KOSPI close series (Date, Close).

    python -m experiments.e0_baseline --oos-dir <dir> --kospi <KOSPI.parquet> --out <dir>
"""

import argparse
import json
from pathlib import Path

import pandas as pd
from experiments.evaluation.metrics import (calculate_classification_metrics, calculate_rank_ic,
                                            compare_daily_ic, daily_rank_ic, summarize_daily_ic,
                                            top_bottom_spread)


def with_excess(frame, kospi):
    close = kospi.set_index(pd.to_datetime(kospi.Date)).Close
    start, end = close.reindex(frame.Date).to_numpy(), close.reindex(frame.return_date).to_numpy()
    return frame.assign(kospi_return=end / start - 1, excess_return=lambda f: f.forward_return - f.kospi_return)


def reproduction(frame):
    labeled = frame.loc[frame.label_observed]
    annual = [calculate_classification_metrics(part.Y_Label, part.prob_up)["roc_auc"]
              for _, part in labeled.groupby(labeled.Date.dt.year)]
    return {"auc_year_mean": sum(annual) / len(annual),
            "auc_pooled": calculate_classification_metrics(labeled.Y_Label, labeled.prob_up)["roc_auc"],
            "rank_ic_label": calculate_rank_ic(labeled, "prob_up", "Y_Label")["ic_mean"]}


def ranking_rows(frame, horizon):
    rows = []
    returns = frame.loc[frame.return_observed]
    for year, part in [("all", returns), *returns.groupby(returns.Date.dt.year)]:
        row = {"horizon": horizon, "year": year}
        for target in ("forward_return", "excess_return"):
            stats = summarize_daily_ic(daily_rank_ic(part.dropna(subset=[target]), "prob_up", target))
            row.update({f"{target}_{key}": value for key, value in stats.items()})
        spread = top_bottom_spread(part, "prob_up", "forward_return", quantile=0.1)
        row.update({f"decile_{key}": value for key, value in spread.items()})
        rows.append(row)
    return rows


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--oos-dir", type=Path, required=True)
    parser.add_argument("--kospi", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--variants", default="A", help="Comma-separated OOS variants present as h{H}_{V}.parquet")
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    kospi = pd.read_parquet(args.kospi)
    variants = args.variants.split(",")
    reproduced, ranking, comparisons = [], [], []
    for horizon in (5, 20):
        frames = {v: with_excess(pd.read_parquet(args.oos_dir / f"h{horizon}_{v}.parquet"), kospi) for v in variants}
        for variant, frame in frames.items():
            reproduced.append({"horizon": horizon, "variant": variant, **reproduction(frame)})
            ranking += [{"variant": variant, **row} for row in ranking_rows(frame, horizon)]
        base = frames[variants[0]].loc[lambda f: f.return_observed]
        ic = {f"{v}:prob_up": daily_rank_ic(frames[v].loc[frames[v].return_observed], "prob_up", "forward_return")
              for v in variants}
        # Same model, second score: P(up) - P(down). Exercises the comparison when only A is shared.
        ic[f"{variants[0]}:up_minus_down"] = daily_rank_ic(
            base.assign(score=base.prob_up - base.prob_down), "score", "forward_return")
        reference = f"{variants[0]}:prob_up"
        for name, series in ic.items():
            if name != reference:
                comparisons.append({"horizon": horizon, "a": reference, "b": name,
                                    **compare_daily_ic(ic[reference], series, n_boot=2000, seed=0)})
    for name, rows in (("reproduction", reproduced), ("ranking", ranking), ("ic_comparison", comparisons)):
        pd.DataFrame(rows).to_csv(args.out / f"{name}.csv", index=False)
    print(json.dumps({"reproduction": reproduced, "comparisons": comparisons}, default=float, indent=1))


if __name__ == "__main__":
    main()
