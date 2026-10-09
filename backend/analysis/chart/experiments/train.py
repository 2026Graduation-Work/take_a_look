# ruff: noqa: I001

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import gc
import json
import os

import lightgbm as lgb
import numpy as np
import pandas as pd
import scipy.stats as stats

from experiment_utils import (
    cache_dir,
    find_processed_dir,
    generate_dataset_hash,
    generate_predictions_hash,
    load_universe_intervals,
    label_params_from_config,
    result_dir,
    resolve_splits,
    resolve_tickers,
)
from train_src.lgbm_wrapper import LGBMWrapper
from train_src.loaders import load_parquet_data


def _json_safe(value):
    if isinstance(value, (np.floating, np.integer)):
        return value.item()
    if pd.isna(value):
        return None
    return value


def _validation_window(train_end: str, embargo_days: int) -> tuple[str, str, str]:
    train_end_dt = pd.to_datetime(train_end)
    pure_train_end_dt = train_end_dt - pd.DateOffset(months=6)
    val_start_dt = pure_train_end_dt + pd.Timedelta(days=embargo_days)
    return (
        pure_train_end_dt.strftime("%Y-%m-%d"),
        val_start_dt.strftime("%Y-%m-%d"),
        train_end,
    )


def _training_windows(
    split_info: dict, embargo_days: int, skip_validation: bool
) -> tuple[str, str, str, str, str | None]:
    """Resolve leakage-safe train/validation label observation boundaries.

    Final holdout runs may deliberately skip the internal six-month validation
    window.  In that case the configured training period is used in full, but
    labels are never allowed to observe beyond ``train_end`` (and therefore
    never into the holdout year).
    """
    train_end = split_info["train_end"]
    if skip_validation:
        return train_end, train_end, train_end, train_end, None

    pure_train_end, val_start, val_end = _validation_window(train_end, embargo_days)
    train_label_observation_end = (pd.to_datetime(val_start) - pd.Timedelta(days=1)).strftime(
        "%Y-%m-%d"
    )
    validation_label_observation_end = (
        pd.to_datetime(split_info["test_start"]) - pd.Timedelta(days=1)
    ).strftime("%Y-%m-%d")
    return (
        pure_train_end,
        train_label_observation_end,
        val_start,
        val_end,
        validation_label_observation_end,
    )


def _get_spearman(group):
    if len(group) < 5:
        return np.nan
    if group["Prob"].std() == 0 or group["Y_Label"].std() == 0:
        return np.nan
    return group["Prob"].corr(group["Y_Label"], method="spearman")


def _evaluate_validation(
    config: dict,
    split_info: dict,
    fold_idx: int,
    model_wrapper: LGBMWrapper,
    val_df: pd.DataFrame,
    feature_cols: list[str],
) -> dict:
    prob_threshold = config.get("strategy", {}).get("prob_threshold", 0.65)
    top_n = config.get("strategy", {}).get("top_n", 5)
    fold_id = split_info.get("fold_id", fold_idx)
    fold_name = split_info.get("name", f"Fold {fold_id}")

    X_val = val_df[feature_cols]
    val_probs = model_wrapper.predict(X_val)
    required_metadata = {"Date", "Code", "Close", "Trading_Halt", "Y_Label"}
    missing_metadata = sorted(required_metadata - set(val_df.columns))
    if missing_metadata:
        raise ValueError(
            f"검증 데이터에 실제 거래 가능 여부 판단용 메타데이터가 없습니다: {missing_metadata}"
        )

    val_eval_cols = ["Date", "Code", "Y_Label", "Close", "Trading_Halt"]
    val_eval_df = val_df[val_eval_cols].copy()
    val_eval_df["Prob"] = val_probs

    daily_ic = val_eval_df.groupby("Date").apply(_get_spearman).dropna()
    n_days = len(daily_ic)

    if n_days < 5:
        mean_ic = np.nan
        std_ic = np.nan
        t_stat = 0.0
        p_val_t = 1.0
    else:
        mean_ic = daily_ic.mean()
        std_ic = daily_ic.std()
        t_stat = 0.0 if std_ic == 0 else mean_ic / (std_ic / np.sqrt(n_days))
        p_val_t = stats.t.sf(t_stat, df=n_days - 1)

    val_eval_df["Is_Valid"] = (
        (val_eval_df["Prob"] >= prob_threshold)
        & (val_eval_df["Close"] > 1.0)
        & (val_eval_df["Trading_Halt"] == 0)
    )

    def select_top_signals(group):
        valid_group = group[group["Is_Valid"]]
        if valid_group.empty:
            return pd.DataFrame()
        return valid_group.nlargest(top_n, "Prob")

    selected_signals = val_eval_df.groupby("Date", group_keys=False).apply(select_top_signals)
    n_signals = len(selected_signals)
    base_rate = (val_eval_df["Y_Label"] == 2).mean()

    if n_signals == 0:
        n_success = 0
        success_rate = 0.0
        p_val_binom = 1.0
    else:
        n_success = (selected_signals["Y_Label"] == 2).sum()
        success_rate = n_success / n_signals
        p_val_binom = (
            1.0 - stats.binom.cdf(n_success - 1, n_signals, base_rate) if n_success > 0 else 1.0
        )

    ic_passed = bool(pd.notna(mean_ic) and mean_ic >= 0.02)
    t_stat_passed = bool(t_stat >= 2.0 and p_val_t <= 0.05)
    binom_passed = bool(p_val_binom <= 0.05)
    validation_passed = bool(ic_passed and t_stat_passed and binom_passed)

    failure_reasons = []
    if n_days < 5:
        failure_reasons.append("insufficient_ic_days")
    if not ic_passed:
        failure_reasons.append("ic_mean<0.02")
    if not t_stat_passed:
        failure_reasons.append("t_stat_or_p_value_failed")
    if not binom_passed:
        failure_reasons.append("binomial_p_value>0.05")

    return {
        "fold_id": fold_id,
        "Fold": fold_name,
        "train_start": split_info["train_start"],
        "train_end": split_info["train_end"],
        "validation_start": val_eval_df["Date"].min(),
        "validation_end": val_eval_df["Date"].max(),
        "sample_count": len(val_eval_df),
        "up_class_ratio": base_rate,
        "ic_mean": mean_ic,
        "ic_std": std_ic,
        "ic_t_stat": t_stat,
        "ic_p_value": p_val_t,
        "ic_positive_day_ratio": (daily_ic > 0).mean() if n_days else 0.0,
        "ic_n_days": n_days,
        "prob_threshold": prob_threshold,
        "top_n": top_n,
        "selected_signal_count": n_signals,
        "selected_success_count": n_success,
        "selected_success_rate": success_rate,
        "selected_base_rate": base_rate,
        "selected_binomial_p_value": p_val_binom,
        "ic_passed": ic_passed,
        "t_stat_passed": t_stat_passed,
        "binomial_passed": binom_passed,
        "validation_passed": validation_passed,
        "failure_reasons": ",".join(failure_reasons),
    }


def _write_validation_artifacts(
    validation_records: list[dict],
    out_dir: str,
    predictions_hash: str,
) -> None:
    if not validation_records:
        return

    validation_df = pd.DataFrame(validation_records)
    validation_df.to_csv(os.path.join(out_dir, "validation_metrics_by_fold.csv"), index=False)

    passed = validation_df["validation_passed"].astype(bool)
    summary = {
        "prediction_hash": predictions_hash,
        "validation_fold_count": int(len(validation_df)),
        "validation_passed_fold_count": int(passed.sum()),
        "validation_failed_fold_count": int((~passed).sum()),
        "validation_all_passed": bool(passed.all()),
        "validation_ic_mean": _json_safe(validation_df["ic_mean"].mean()),
        "validation_ic_min": _json_safe(validation_df["ic_mean"].min()),
        "validation_selected_success_rate_mean": _json_safe(
            validation_df["selected_success_rate"].mean()
        ),
        "validation_selected_binomial_p_value_max": _json_safe(
            validation_df["selected_binomial_p_value"].max()
        ),
    }
    with open(os.path.join(out_dir, "validation_metrics_summary.json"), "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=4, ensure_ascii=False)


def _load_validation_df(
    processed_dir: str,
    val_start: str,
    val_end: str,
    label_observation_end: str,
    tickers_cfg,
    label_params: dict,
    feature_cols: list[str],
    universe_intervals: pd.DataFrame = None,
) -> pd.DataFrame:
    val_df = load_parquet_data(
        processed_dir,
        val_start,
        val_end,
        tickers=tickers_cfg,
        label_params=label_params,
        label_observation_end=label_observation_end,
        training=False,
        universe_intervals=universe_intervals,
    )
    val_cols = ["Date", "Code", "Y_Label", "Close", "Trading_Halt"] + feature_cols
    return val_df[[c for c in val_cols if c in val_df.columns]].copy()


def _print_validation_report(fold_number: int, validation_metrics: dict) -> None:
    print("=" * 85)
    print(f"📊 [VALIDATION REPORT] Fold {fold_number} Validation Summary")
    print("=" * 85)
    print(
        f"  - Mean Rank IC:   {validation_metrics['ic_mean']:.4f}  "
        f"(Threshold: >= 0.02) -> {'PASSED ✅' if validation_metrics['ic_passed'] else 'FAILED ❌'}"
    )
    print(
        f"  - t-statistic:    {validation_metrics['ic_t_stat']:.4f}  "
        f"(Threshold: >= 2.0)  -> {'PASSED ✅' if validation_metrics['t_stat_passed'] else 'FAILED ❌'}"
    )
    print(
        f"  - Success Rate:   {validation_metrics['selected_success_rate'] * 100:.2f}% "
        f"(Base Rate: {validation_metrics['selected_base_rate'] * 100:.2f}%)"
    )
    print(
        f"  - Binomial p-val: {validation_metrics['selected_binomial_p_value']:.6f}  "
        f"(Threshold: <= 0.05) -> {'PASSED ✅' if validation_metrics['binomial_passed'] else 'FAILED ❌'}"
    )
    print("=" * 85)


def main(config_path):
    print(f"[*] Loading config from {config_path}...")
    from core.local_config import load_experiment_config

    config = load_experiment_config(config_path)
    from functools import partial
    from train_src.loaders import load_parquet_data as base_loader

    global load_parquet_data
    load_parquet_data = partial(
        base_loader, feature_columns=config["feature_columns"], sample_only=True
    )

    exp_name = config.get("experiment_name", "default_exp")
    print(f"\n🚀 [*] Starting Quant Experiment: {exp_name}")

    # 데이터 분할 전략에 따른 fold 목록 결정
    splits = resolve_splits(config)
    if not splits:
        raise ValueError("분할 폴드(Splits) 목록이 비어 있습니다. 설정을 확인하세요.")

    print(
        f"[*] 데이터 분할 전략: {config.get('data', {}).get('split_strategy', 'single')} (총 {len(splits)}개 폴드)"
    )
    for idx, split_info in enumerate(splits):
        print(
            f"    - [Fold {idx + 1}] Train: {split_info['train_start']} ~ {split_info['train_end']} | Test: {split_info['test_start']} ~ {split_info['test_end']}"
        )

    # 캐시용 해시 생성
    dataset_hash = generate_dataset_hash(config, splits)
    predictions_hash = generate_predictions_hash(config, splits)
    print(f"[*] Dataset Cache Hash: {dataset_hash} | Predictions Cache Hash: {predictions_hash}")
    out_dir = result_dir(config, __file__)

    # 데이터 경로 자동 탐색
    processed_dir = find_processed_dir(config, __file__)
    print(f"[*] 데이터 소스 디렉토리: {processed_dir}")
    if not os.path.exists(processed_dir) or not os.listdir(processed_dir):
        print(
            f"[!] 경고: {processed_dir}가 비어있거나 존재하지 않습니다. 먼저 수집 및 전처리를 실행해야 할 수 있습니다."
        )

    tickers_cfg = resolve_tickers(config, __file__)
    universe_intervals = load_universe_intervals(config)
    skip_validation = bool(config.get("training", {}).get("skip_validation", False))

    # OOS 예측 확률 캐시 확인
    exp_cache_dir = cache_dir(__file__)
    predictions_cache_path = os.path.join(exp_cache_dir, f"{predictions_hash}_predictions.parquet")

    if os.path.exists(predictions_cache_path):
        from experiment_utils import load_predictions

        load_predictions(config, splits, __file__)
        print("\n⚡ [CACHE HIT] 기존 설정 기반 예측 캐시를 찾았습니다!")
        print(f"   -> 캐시 파일: {os.path.basename(predictions_cache_path)}")
        if skip_validation:
            print("[*] Validation 복원 생략: config training.skip_validation=true")
            print(f"\n🎉 모델 학습 및 예측 캐시 빌드 [{exp_name}] 완료!")
            return
        print("[*] 저장된 fold 모델로 Validation 결과 파일을 복원합니다.")

        validation_records = []
        for idx, split_info in enumerate(splits):
            train_end = split_info["train_end"]
            embargo_days = config.get("data", {}).get("embargo_days", 7)
            label_params = label_params_from_config(config)
            _, val_start, val_end = _validation_window(train_end, embargo_days)
            label_observation_end = (
                pd.to_datetime(split_info["test_start"]) - pd.Timedelta(days=1)
            ).strftime("%Y-%m-%d")
            fold_pred_hash = f"{predictions_hash}_fold{idx}"
            model_wrapper = LGBMWrapper(config)
            model_save_path = os.path.join(
                model_wrapper.cache_dir, "models", f"{fold_pred_hash}_model.txt"
            )
            if not os.path.exists(model_save_path):
                print(
                    f"[!] Validation 복원 스킵: fold 모델 캐시가 없습니다 -> "
                    f"{os.path.basename(model_save_path)}"
                )
                continue

            model_wrapper.load_cached_model(model_save_path)
            feature_cols = model_wrapper.model.feature_name()
            val_df = _load_validation_df(
                processed_dir,
                val_start,
                val_end,
                label_observation_end,
                tickers_cfg,
                label_params,
                feature_cols,
                universe_intervals,
            )
            validation_metrics = _evaluate_validation(
                config, split_info, idx, model_wrapper, val_df, feature_cols
            )
            validation_records.append(validation_metrics)
            _write_validation_artifacts(validation_records, out_dir, predictions_hash)
            _print_validation_report(idx + 1, validation_metrics)

            if not validation_metrics["validation_passed"]:
                raise RuntimeError(
                    "Cached prediction validation failed: "
                    f"fold={idx + 1}, reason={validation_metrics['failure_reasons']}"
                )

            del val_df
            gc.collect()
    else:
        all_predictions = []
        validation_records = []

        for idx, split_info in enumerate(splits):
            print(f"\n{'=' * 60}")
            print(f"▶ [데이터 분할 Fold {idx + 1}/{len(splits)}] 학습 및 추론 진행 중...")
            print(f"{'=' * 60}")

            train_start = split_info["train_start"]
            train_end = split_info["train_end"]
            test_start = split_info["test_start"]
            test_end = split_info["test_end"]
            embargo_days = config.get("data", {}).get("embargo_days", 7)
            label_params = label_params_from_config(config)
            (
                pure_train_end,
                train_label_observation_end,
                val_start,
                val_end,
                validation_label_observation_end,
            ) = _training_windows(split_info, embargo_days, skip_validation)

            fold_pred_hash = f"{predictions_hash}_fold{idx}"
            model_wrapper = LGBMWrapper(config)
            models_dir = os.path.join(model_wrapper.cache_dir, "models")
            os.makedirs(models_dir, exist_ok=True)
            model_save_path = os.path.join(models_dir, f"{fold_pred_hash}_model.txt")

            if os.path.exists(model_save_path):
                print(
                    f"\n⚡ [MODEL CACHE HIT] 기존 학습된 모델 파라미터 발견! -> {os.path.basename(model_save_path)}"
                )
                model_wrapper.load_cached_model(model_save_path)
                feature_cols = model_wrapper.model.feature_name()
            else:
                # ---------------------------------------------------------
                # 1. 학습 데이터 (Train) 준비 및 라벨링
                # ---------------------------------------------------------
                print("\n[2] 모델 학습 준비 (LGBM Wrapper)...")
                fold_data_hash = f"{dataset_hash}_fold{idx}"

                train_bin_path = os.path.join(
                    model_wrapper.cache_dir, f"{fold_data_hash}_train.bin"
                )
                if os.path.exists(train_bin_path):
                    print(
                        f"  [CACHE HIT] 기존 Train .bin으로 학습 데이터 로드 -> "
                        f"{os.path.basename(train_bin_path)}"
                    )
                    train_data = model_wrapper.load_cached_dataset(train_bin_path)
                    train_data.construct()
                    feature_cols = train_data.feature_name
                else:
                    print("\n[1] Train 데이터 로딩 및 동적 라벨(Y) 생성...")

                    # 순수 Alpha158 학습 (노이즈 필터링 배제)
                    train_df = load_parquet_data(
                        processed_dir,
                        train_start,
                        pure_train_end,
                        tickers=tickers_cfg,
                        label_params=label_params,
                        label_observation_end=train_label_observation_end,
                        training=True,
                        keep_date=False,
                        universe_intervals=universe_intervals,
                    )

                    feature_cols = config["feature_columns"]

                    X_train, y_train = train_df[feature_cols], train_df["Y_Label"]
                    train_data = model_wrapper._build_dataset(X_train, y_train, train_bin_path)

                    del train_df, X_train, y_train
                    gc.collect()

                # ---------------------------------------------------------
                # 2.5. 검증 데이터 (Val) 준비 및 라벨링
                # ---------------------------------------------------------
                if skip_validation:
                    print("\n[2.5] Validation 생략: config training.skip_validation=true")
                    val_df = None
                    model_wrapper.fit(train_data, None, cache_hash=fold_pred_hash)
                else:
                    print("\n[2.5] Val 데이터 로딩 및 동적 라벨(Y) 생성...")
                    val_df = load_parquet_data(
                        processed_dir,
                        val_start,
                        train_end,
                        tickers=tickers_cfg,
                        label_params=label_params,
                        label_observation_end=validation_label_observation_end,
                        training=False,
                        universe_intervals=universe_intervals,
                    )

                    val_cols = ["Date", "Code", "Y_Label", "Close", "Trading_Halt"] + feature_cols
                    val_df = val_df[[c for c in val_cols if c in val_df.columns]].copy()

                    X_val, y_val = val_df[feature_cols], val_df["Y_Label"]

                    print("[LGBM] Validation 데이터셋 준비 중...")

                    sample_weights_val = model_wrapper.sample_weights(y_val)
                    valid_data = lgb.Dataset(
                        X_val,
                        label=y_val,
                        weight=sample_weights_val,
                        reference=train_data,
                        free_raw_data=False,
                    )

                    # 모델 학습
                    model_wrapper.fit(train_data, valid_data, cache_hash=fold_pred_hash)

                    del X_val, y_val, valid_data
                    gc.collect()

            # ---------------------------------------------------------
            # 2.6. 검증 데이터에 대한 통계적 검정 (OOS 과적합 통제)
            # ---------------------------------------------------------
            if skip_validation:
                print("\n[2.6] Validation 검정 생략: 최종 holdout 평가로 검증합니다.")
            else:
                print("\n[2.6] Validation 셋에 대한 통계적 신뢰성 검증 진행...")
            if (not skip_validation) and "val_df" not in locals():
                print("\n[2.5] Val 데이터 로딩 및 동적 라벨(Y) 생성...")
                val_df = _load_validation_df(
                    processed_dir,
                    val_start,
                    val_end,
                    validation_label_observation_end,
                    tickers_cfg,
                    label_params,
                    feature_cols,
                    universe_intervals,
                )

            if not skip_validation:
                validation_metrics = _evaluate_validation(
                    config, split_info, idx, model_wrapper, val_df, feature_cols
                )
                validation_records.append(validation_metrics)
                _write_validation_artifacts(validation_records, out_dir, predictions_hash)

                _print_validation_report(idx + 1, validation_metrics)

                if not validation_metrics["validation_passed"]:
                    print(
                        f"\n❌ [VALIDATION FAILED] Fold {idx + 1} 통계적 검정 미통과 "
                        f"(과적합 위험): {validation_metrics['failure_reasons']}"
                    )
                    raise RuntimeError("Validation Statistical Test Failed.")

            if "val_df" in locals():
                del val_df
            gc.collect()

            # ---------------------------------------------------------
            # 3. 테스트(OOS) 추론
            # ---------------------------------------------------------
            print("\n[3] Test(Out-of-Sample) 데이터 로딩 및 추론...")
            test_df = load_parquet_data(
                processed_dir,
                test_start,
                test_end,
                columns_only=feature_cols + ["Date", "Code"],
                tickers=tickers_cfg,
                universe_intervals=universe_intervals,
            )
            X_test = test_df[feature_cols]

            probs = model_wrapper.predict(X_test)

            test_preds = test_df[["Date", "Code"]].copy()
            test_preds["Prob"] = probs
            class_probs = model_wrapper.model.predict(X_test)
            for class_idx, column in enumerate(("prob_down", "prob_neutral", "prob_up")):
                test_preds[column] = class_probs[:, class_idx]
            test_preds["fold_id"] = int(split_info.get("fold_id", idx))
            all_predictions.append(test_preds)

            del test_df, X_test
            gc.collect()

        final_predictions = pd.concat(all_predictions, ignore_index=True)
        final_predictions.to_parquet(predictions_cache_path, index=False)
        from core.local_config import atomic_json
        from core.local_dataset import sha256

        atomic_json(
            predictions_cache_path + ".manifest.json",
            {
                "predictions_hash": predictions_hash,
                "feature_columns": config["feature_columns"],
                "config": config,
                "sha256": sha256(predictions_cache_path),
            },
        )
        print(
            f"\n💾 [CACHE SAVE] 예측 결과 캐시 완료 -> {os.path.basename(predictions_cache_path)}"
        )
    print(f"\n🎉 모델 학습 및 예측 캐시 빌드 [{exp_name}] 완료!")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=str, required=True, help="Path to config yaml")
    args = parser.parse_args()
    main(args.config)
