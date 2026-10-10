# ruff: noqa: I001

import argparse
from pathlib import Path

import json
import os

import numpy as np
import pandas as pd
from experiments.evaluation.metrics import (
    calculate_calibration_table,
    calculate_classification_metrics,
    calculate_rank_ic,
)
from experiments.experiment_utils import (
    build_fold_alignment,
    find_processed_dir,
    filter_to_test_fold_rows,
    generate_predictions_hash,
    label_params_from_config,
    load_universe_intervals,
    load_predictions,
    resolve_splits,
    resolve_tickers,
    result_dir,
    test_date_bounds,
)
from experiments.train_src.loaders import load_parquet_data  # noqa: F401


def _json_safe(value):
    if isinstance(value, (np.floating, np.integer)):
        return value.item()
    if pd.isna(value):
        return None
    return value


def _restrict_predictions_to_labeled_rows(
    predictions: pd.DataFrame, actual: pd.DataFrame
) -> tuple[pd.DataFrame, int]:
    """Keep evaluable predictions while rejecting missing or duplicate keys.

    Predictions can legitimately contain the unlabeled tail of delisted stocks.
    Those rows remain available to the canonical backtest, but ML metrics can
    only use rows whose future outcome is observable.
    """
    keys = ["Date", "Code"]
    if predictions.duplicated(keys).any():
        raise ValueError("예측 캐시에 중복 Date/Code 키가 있습니다.")
    if actual.duplicated(keys).any():
        raise ValueError("평가 라벨에 중복 Date/Code 키가 있습니다.")

    labeled_keys = actual[keys].copy()
    aligned = labeled_keys.merge(predictions, on=keys, how="left", validate="one_to_one")
    prediction_columns = [column for column in predictions.columns if column not in keys]
    missing = aligned[prediction_columns].isna().all(axis=1)
    if missing.any():
        examples = aligned.loc[missing, keys].head(5).to_dict("records")
        raise ValueError(
            "평가 라벨에 대응하는 prediction이 없습니다. "
            f"누락 {int(missing.sum())}건, 예시={examples}"
        )
    return aligned, int(len(predictions) - len(aligned))


def main(config_path, predictions_path=None):
    print(f"[*] Loading config from {config_path}...")
    from experiments.config import load_experiment_config
    config = load_experiment_config(config_path)
    from functools import partial
    from experiments.train_src.loaders import load_parquet_data as base_loader
    global load_parquet_data
    load_parquet_data = partial(base_loader, feature_columns=config["feature_columns"], sample_only=True)

    exp_name = config.get("experiment_name", "default_exp")
    print(f"\n📊 [*] Starting ML Evaluation: {exp_name}")

    splits = resolve_splits(config)
    if not splits:
        raise ValueError("분할 폴드(Splits) 목록이 비어 있습니다. 설정을 확인하세요.")

    predictions_hash = generate_predictions_hash(config, splits)
    print(f"[*] Target Predictions Cache Hash: {predictions_hash}")

    # Load predictions (either cached or explicitly passed path)
    final_predictions = load_predictions(config, splits, __file__, predictions_path)
    final_predictions["Date"] = pd.to_datetime(final_predictions["Date"]).dt.tz_localize(None)

    processed_dir = find_processed_dir(config, __file__)
    print(f"[*] 데이터 소스 디렉토리: {processed_dir}")

    full_test_start, full_test_end = test_date_bounds(splits)
    tickers_cfg = resolve_tickers(config, __file__)
    universe_intervals = load_universe_intervals(config)

    # Load actual labels
    label_params = label_params_from_config(config)
    label_cols = ["Date", "Code", "Y_Label"]
    actual_df = load_parquet_data(
        processed_dir,
        full_test_start,
        full_test_end,
        columns_only=label_cols,
        tickers=tickers_cfg,
        label_params=label_params,
        training=False,  # Load all requested columns normally
        sample_only=config.get("contract_version") == 3,
        universe_only=config.get("data", {}).get("point_in_time", False),
        strict=config.get("data", {}).get("point_in_time", False),
        universe_intervals=universe_intervals,
    )
    actual_df["Date"] = pd.to_datetime(actual_df["Date"]).dt.tz_localize(None)
    actual_df = filter_to_test_fold_rows(actual_df, splits)

    # 미래 outcome을 확인할 수 없는 상장폐지 종목의 마지막 tail은 정답 라벨이 없다.
    # 백테스트용 원본 prediction은 보존하고 ML 평가에서만 labeled key로 제한한다.
    all_oos_predictions = final_predictions.copy()
    final_predictions, unlabeled_prediction_rows = _restrict_predictions_to_labeled_rows(
        final_predictions, actual_df
    )

    # Align predictions and actual labels
    alignment_df, alignment_status = build_fold_alignment(final_predictions, splits, eval_df=actual_df)
    if not alignment_status["is_exact_row_match"]:
        raise ValueError(
            "예측 캐시와 실제 라벨이 config의 test fold 행 키와 정확히 매칭되지 않습니다. "
            f"alignment={alignment_status}"
        )

    # Merge predictions with actuals
    eval_df = pd.merge(
        final_predictions,
        actual_df,
        on=["Date", "Code"],
        how="inner",
        validate="one_to_one",
    )

    # Calculate fold alignment details
    alignment_df.to_csv(os.path.join(result_dir(config, __file__), "fold_alignment.csv"), index=False)

    # Compute fold-by-fold metrics
    model_metrics_list = []
    calibration_list = []
    bins = config.get("evaluation", {}).get("probability_bins", [0.0, 0.2, 0.4, 0.6, 0.8, 1.0])

    for idx, split in enumerate(splits):
        fold_id = split.get("fold_id", idx)
        fold_name = split.get("name", f"Fold {fold_id}")
        test_start = pd.to_datetime(split["test_start"])
        test_end = pd.to_datetime(split["test_end"])

        fold_df = eval_df[(eval_df["Date"] >= test_start) & (eval_df["Date"] <= test_end)]
        if fold_df.empty:
            print(f"[!] Warning: Fold {fold_name} has no matching evaluation samples.")
            continue

        # Classifications metrics
        cls_metrics = calculate_classification_metrics(fold_df["Y_Label"], fold_df["Prob"])
        # Rank IC metrics
        ic_metrics = calculate_rank_ic(fold_df, prob_col="Prob", target_col="Y_Label")

        fold_record = {
            "fold_id": fold_id,
            "Fold": fold_name,
            "sample_count": len(fold_df),
            "up_class_ratio": cls_metrics["up_class_ratio"],
            "accuracy": cls_metrics["accuracy"],
            "balanced_accuracy": cls_metrics["balanced_accuracy"],
            "macro_f1": cls_metrics["macro_f1"],
            "brier_score": cls_metrics["brier_score"],
            "roc_auc": cls_metrics["roc_auc"],
            "pr_auc": cls_metrics["pr_auc"],
            "ic_mean": ic_metrics["ic_mean"],
            "ic_std": ic_metrics["ic_std"],
            "ic_t_stat": ic_metrics["ic_t_stat"],
            "ic_p_value": ic_metrics["ic_p_value"],
            "ic_positive_day_ratio": ic_metrics["positive_day_ratio"],
            "ic_n_days": ic_metrics["n_days"],
        }
        model_metrics_list.append(fold_record)

        # Calibration
        fold_calib = calculate_calibration_table(fold_df["Y_Label"], fold_df["Prob"], bins)
        fold_calib.insert(0, "Fold", fold_name)
        fold_calib.insert(0, "fold_id", fold_id)
        calibration_list.append(fold_calib)

    model_metrics_df = pd.DataFrame(model_metrics_list)
    calibration_df = pd.concat(calibration_list, ignore_index=True) if calibration_list else pd.DataFrame()

    # Compute overall metrics
    overall_cls = calculate_classification_metrics(eval_df["Y_Label"], eval_df["Prob"])
    overall_ic = calculate_rank_ic(eval_df, prob_col="Prob", target_col="Y_Label")

    summary = {
        "ml_sample_count": len(eval_df),
        "ml_up_class_ratio": overall_cls["up_class_ratio"],
        "ml_accuracy": overall_cls["accuracy"],
        "ml_balanced_accuracy": overall_cls["balanced_accuracy"],
        "ml_macro_f1": overall_cls["macro_f1"],
        "ml_brier_score": overall_cls["brier_score"],
        "ml_roc_auc": overall_cls["roc_auc"],
        "ml_pr_auc": overall_cls["pr_auc"],
        "ic_ic_mean": overall_ic["ic_mean"],
        "ic_ic_std": overall_ic["ic_std"],
        "ic_ic_t_stat": overall_ic["ic_t_stat"],
        "ic_ic_p_value": overall_ic["ic_p_value"],
        "ic_positive_day_ratio": overall_ic["positive_day_ratio"],
        "ic_n_days": overall_ic["n_days"],
        "prediction_hash": predictions_hash,
        "fold_alignment_exact": bool(alignment_status["is_exact_fold_match"]),
        "excluded_unlabeled_prediction_rows": unlabeled_prediction_rows,
        **{f"fold_alignment_{k}": _json_safe(v) for k, v in alignment_status.items()}
    }

    # Save files
    out_dir = result_dir(config, __file__)
    from shared.io import atomic_json, atomic_parquet
    from shared.io import sha256

    history = all_oos_predictions.merge(actual_df[["Date", "Code", "Y_Label"]],
                                        on=["Date", "Code"], how="left", validate="one_to_one")
    history["label_observed"] = history.Y_Label.notna()
    history_path = Path(out_dir) / "oos_history.parquet"
    atomic_parquet(history_path, history)
    atomic_json(Path(out_dir) / "oos_history.manifest.json", {
        "prediction_hash": predictions_hash, "sha256": sha256(history_path),
        "rows": len(history), "label_observed_rows": int(history.label_observed.sum()),
        "years": sorted(history.Date.dt.year.unique().tolist()), "splits": splits,
        "feature_columns": config.get("feature_columns"),
        "purpose": "full OOS score distribution; no strategy threshold/top-N filtering",
    })
    model_metrics_df.to_csv(os.path.join(out_dir, "model_metrics_by_fold.csv"), index=False)
    calibration_df.to_csv(os.path.join(out_dir, "calibration_by_fold.csv"), index=False)

    with open(os.path.join(out_dir, "ml_metrics_summary.json"), "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=4, ensure_ascii=False)

    print(f"✅ ML 평가지표 산출 완료: {out_dir}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=str, required=True, help="Path to config yaml")
    parser.add_argument(
        "--predictions-path",
        type=str,
        default=None,
        help="Path to pre-computed predictions parquet file",
    )
    args = parser.parse_args()
    main(args.config, args.predictions_path)
