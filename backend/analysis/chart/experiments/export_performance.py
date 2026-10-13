"""Export verified, completed psychology A/B runs without training or changing models."""

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd
from experiments.comparison.metrics import expected_calibration_error, select_volatile_dates
from experiments.evaluation.metrics import calculate_classification_metrics
from shared.io import sha256

METRICS = {
    "auc": "delta_B_minus_A_auc", "hit_rate": "delta_B_minus_A_hit_rate",
    "calibration_brier": "delta_B_minus_A_calibration_brier",
    "calibration_ece": "delta_B_minus_A_calibration_ece", "sharpe": "delta_B_minus_A_sharpe",
    "mdd": "delta_B_minus_A_mdd", "cumulative_return": "delta_B_minus_A_cumulative_return",
    "trade_count": "delta_B_minus_A_trade_count",
}


def metric_row(frame, backtest, *, profile, variant, sample, feature_count):
    """Equal-weight annual ML means; annual strategy means, never a synthetic seven-year portfolio."""
    annual = []
    for _, part in frame.groupby(frame.Date.dt.year, sort=True):
        part = part.reset_index(drop=True)
        metrics = calculate_classification_metrics(part.Y_Label, part.prob_up, threshold=0.5)
        annual.append({"auc": metrics["roc_auc"], "hit_rate": metrics["accuracy"],
                       "positive_rate": metrics["up_class_ratio"], "calibration_brier": metrics["brier_score"],
                       "calibration_ece": expected_calibration_error((part.Y_Label == 2).astype(int), part.prob_up)})
    if not annual:
        raise ValueError("No observed labels in performance sample")
    means = pd.DataFrame(annual).mean(skipna=False).to_dict()
    means = {key: None if not np.isfinite(value) else float(value) for key, value in means.items()}
    strategy = {key: None for key in ("sharpe", "mdd", "cumulative_return", "trade_count")}
    if backtest is not None:
        for key, column in [("sharpe", "sharpe_ratio"), ("mdd", "max_drawdown"), ("cumulative_return", "total_return")]:
            values = backtest[column].to_numpy(dtype=float)
            strategy[key] = float(values.mean()) if np.isfinite(values).all() else None
        strategy["trade_count"] = int(backtest.number_of_trades.sum())
    return {"profile": profile, "variant": variant, "feature_set": "baseline" if variant == "A" else "treatment",
            "sample": sample, "feature_count": feature_count, "sample_rows": len(frame),
            "sample_dates": int(frame.Date.nunique()), **means, **strategy}


def paired_frames(left, right):
    keys = ["Date", "Code", "fold_id", "Y_Label", "label_observed"]
    result = []
    for frame in (left, right):
        frame = frame.sort_values(["Date", "Code"]).reset_index(drop=True)
        if frame.duplicated(["Date", "Code"]).any():
            raise ValueError("Duplicate OOS keys")
        if not np.isfinite(frame.prob_up).all() or not frame.prob_up.between(0, 1).all():
            raise ValueError("Invalid OOS probabilities")
        if not np.allclose(frame.Prob, frame.prob_up, rtol=0, atol=1e-12):
            raise ValueError("OOS score columns disagree")
        if not frame.loc[frame.label_observed, "Y_Label"].isin([0, 1, 2]).all():
            raise ValueError("Invalid observed OOS label")
        result.append(frame)
    if not result[0][keys].equals(result[1][keys]):
        raise ValueError("A/B samples or labels differ")
    return result


def export(suite, output):
    status = json.loads((suite / "status.json").read_text())
    prepared = json.loads((suite / "prepared.json").read_text())
    if status["status"] != "complete" or status["run_id"] != prepared["run_id"]:
        raise ValueError("A/B suite is incomplete or identities differ")
    evidence = []
    runs = {}
    for name in ("h5_A", "h5_B", "h20_A", "h20_B"):
        stages = [status["completed"][f"{name}:{stage}"] for stage in ("train", "ml", "backtest")]
        for files in stages:
            for filename, digest in files.items():
                path = Path(filename)
                if sha256(path) != digest:
                    raise ValueError(f"Completed artifact changed: {path.name}")
                evidence.append({"run": name, "file": f"{path.parent.name}/{path.name}", "sha256": digest})
        oos = next(Path(p) for p in stages[1] if Path(p).name == "oos_history.parquet")
        backtest = next(Path(p) for p in stages[2] if Path(p).name == "backtest_metrics_by_year.csv")
        manifest_path = oos.parent / "run_manifest.json"
        manifest = json.loads(manifest_path.read_text())
        evidence.append({"run": name, "file": f"{oos.parent.name}/run_manifest.json", "sha256": sha256(manifest_path)})
        runs[name] = (pd.read_parquet(oos), pd.read_csv(backtest), manifest)

    # Sigma comes from the actual, hashed B inputs, not recomputed current prices.
    feature_root = Path(runs["h5_B"][2]["config"]["data"]["price_dir"])
    feature_manifest = json.loads((feature_root / "feature_manifest.json").read_text())
    sigma_parts = []
    for filename, digest in feature_manifest["file_hashes"].items():
        path = feature_root / filename
        if sha256(path) != digest:
            raise ValueError(f"Feature input changed: {filename}")
        sigma_parts.append(pd.read_parquet(path, columns=["Date", "Code", "Sigma"]))
    sigmas = pd.concat(sigma_parts, ignore_index=True)
    if sigmas.duplicated(["Date", "Code"]).any():
        raise ValueError("Duplicate volatility keys")
    evidence.append({"file": "feature_manifest.json", "sha256": sha256(feature_root / "feature_manifest.json")})
    rows = []
    periods, years = [], None
    for horizon, profile in [(5, "aggressive"), (20, "stable")]:
        config_a = runs[f"h{horizon}_A"][2]["config"]
        config_b = runs[f"h{horizon}_B"][2]["config"]
        for field in ("labels", "model", "strategy", "backtest"):
            if config_a[field] != config_b[field]:
                raise ValueError(f"A/B {field} settings differ")
        if (config_a["strategy"]["prob_threshold"] != 0.65
                or config_a["data"]["sliding"]["train_window_years"] != 3
                or runs[f"h{horizon}_B"][2]["config"]["data"]["price_dir"] != str(feature_root)):
            raise ValueError("Unsupported strategy, training window or B input store")
        a, b = paired_frames(runs[f"h{horizon}_A"][0], runs[f"h{horizon}_B"][0])
        volatility = a[["Date", "Code"]].merge(sigmas, on=["Date", "Code"], how="left", validate="one_to_one")
        if not np.isfinite(volatility.Sigma).all():
            raise ValueError("Missing OOS volatility")
        volatile = []
        for _, part in volatility.groupby(volatility.Date.dt.year, sort=True):
            dates, _ = select_volatile_dates(part, date_column="Date", volatility_column="Sigma")
            volatile.extend(dates)
        periods.append((a.Date.min(), a.Date.max()))
        current_years = sorted(a.Date.dt.year.unique().tolist())
        if years is not None and current_years != years:
            raise ValueError("H5/H20 evaluation years differ")
        years = current_years
        for variant, frame in [("A", a), ("B", b)]:
            _, backtest, manifest = runs[f"h{horizon}_{variant}"]
            if sorted(backtest.year.tolist()) != years or not backtest.initial_cash.eq(10_000_000).all():
                raise ValueError("Annual strategy period/capital mismatch")
            for sample in ("all", "volatile_top_20pct"):
                observed = frame.loc[frame.label_observed & (True if sample == "all" else frame.Date.isin(volatile))]
                rows.append(metric_row(observed, backtest if sample == "all" else None,
                                       profile=profile, variant=variant, sample=sample,
                                       feature_count=len(manifest["feature_columns"])))
    deltas = []
    for profile in ("stable", "aggressive"):
        for sample in ("all", "volatile_top_20pct"):
            a, b = [next(row for row in rows if row["profile"] == profile and row["sample"] == sample and row["variant"] == v)
                    for v in ("A", "B")]
            deltas.append({"profile": profile, "sample": sample,
                           **{delta: None if a[key] is None or b[key] is None else b[key] - a[key] for key, delta in METRICS.items()}})
    artifact = {
        "experiment": {"id": suite.name, "run_id": status["run_id"], "years": years,
                       "start": str(min(p[0] for p in periods).date()), "end": str(max(p[1] for p in periods).date()),
                       "primary_metric": "annual_mean_roc_auc", "aggregation": "equal_weight_annual_mean",
                       "initial_cash": 10_000_000, "classification_threshold": 0.5, "strategy_threshold": 0.65,
                       "volatile_definition": "각 연도의 공통 예측 표본에서 일별 Sigma 평균 상위 20% 날짜입니다. 날짜 수는 올림하며 동점은 날짜순입니다.",
                       "source": "2019~2025 KOSPI 공통 수급·심리 관측 표본의 저장된 OOS 예측 및 연도별 백테스트",
                       "limitations": "수급·심리 관측이 완전한 공통 표본에 한정됩니다. 수정가격·정보 시점의 한계가 남고, 손대지 않은 최종 검증 표본이나 통계적 유의성의 증거가 아닙니다.",
                       "backtest_scope": "매년 자금 1,000만 원을 초기화한 독립 평가입니다. 수익률·Sharpe·MDD는 연도별 단순평균, 거래 수는 합계입니다. 고변동일 백테스트는 미산출입니다."},
        "four_run_metrics": [r for r in rows if r["sample"] == "all"],
        "volatile_subsample_metrics": [r for r in rows if r["sample"] != "all"], "comparison_deltas": deltas,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(artifact, ensure_ascii=False, indent=2, allow_nan=False) + "\n")
    output.with_name("performance-provenance.json").write_text(json.dumps(
        {"run_id": status["run_id"], "artifact_sha256": sha256(output), "exporter_sha256": sha256(Path(__file__)),
         "status_sha256": sha256(suite / "status.json"), "prepared_sha256": sha256(suite / "prepared.json"),
         "source_artifacts": evidence}, ensure_ascii=False, indent=2) + "\n")
    return artifact


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--suite-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    export(args.suite_dir, args.output)


if __name__ == "__main__":
    main()
