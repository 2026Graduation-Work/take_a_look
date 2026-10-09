import csv
import hashlib
import json
import os
from pathlib import Path

import pandas as pd

CACHE_SCHEMA_VERSION = 3


def _normalize_split(split: dict, fold_id: int) -> dict:
    normalized = {
        "fold_id": int(split.get("fold_id", fold_id)),
        "train_start": split["train_start"],
        "train_end": split["train_end"],
        "test_start": split["test_start"],
        "test_end": split["test_end"],
    }
    if "name" in split:
        normalized["name"] = split["name"]
    return normalized


def split_identity(split: dict) -> dict:
    return {
        "fold_id": int(split["fold_id"]),
        "train_start": split["train_start"],
        "train_end": split["train_end"],
        "test_start": split["test_start"],
        "test_end": split["test_end"],
    }


def _bound_splits_to_data_range(splits: list[dict], data_cfg: dict) -> list[dict]:
    """Clip generated folds to the configured data range and drop empty folds."""
    data_start = pd.to_datetime(data_cfg.get("start_date"), errors="coerce")
    data_end = pd.to_datetime(data_cfg.get("end_date"), errors="coerce")
    bounded = []

    for split in splits:
        normalized = _normalize_split(split, len(bounded))
        train_start = pd.to_datetime(normalized["train_start"])
        train_end = pd.to_datetime(normalized["train_end"])
        test_start = pd.to_datetime(normalized["test_start"])
        test_end = pd.to_datetime(normalized["test_end"])

        if pd.notna(data_start):
            train_start = max(train_start, data_start)
            test_start = max(test_start, data_start)
        if pd.notna(data_end):
            train_end = min(train_end, data_end)
            test_end = min(test_end, data_end)

        if train_start > train_end or test_start > test_end:
            continue

        normalized.update(
            {
                "fold_id": len(bounded),
                "train_start": train_start.strftime("%Y-%m-%d"),
                "train_end": train_end.strftime("%Y-%m-%d"),
                "test_start": test_start.strftime("%Y-%m-%d"),
                "test_end": test_end.strftime("%Y-%m-%d"),
            }
        )
        bounded.append(normalized)

    return bounded


def resolve_splits(config: dict) -> list[dict]:
    """Return canonical split dictionaries shared by train/evaluation/backtest tools.

    Sliding and expanding strategies use non-overlapping test windows.  A
    two-year window, for example, evaluates ``2020-01-08..2021-12-31`` and
    then starts the next fold in 2022; this prevents the same OOS observation
    from being evaluated in multiple folds.
    """
    data_cfg = config.get("data", {})
    strategy = data_cfg.get("split_strategy", "single")
    embargo_days = data_cfg.get("embargo_days", 7)

    if strategy == "single":
        splits = data_cfg.get("splits", [])
        return _bound_splits_to_data_range(splits, data_cfg)

    if strategy == "custom_blocks":
        blocks = data_cfg.get("custom_blocks", [])
        return _bound_splits_to_data_range(blocks, data_cfg)

    if strategy == "sliding":
        cfg = data_cfg.get("sliding", {})
        train_window_years = cfg.get("train_window_years", 3)
        test_window_years = cfg.get("test_window_years", 1)
        start_year = cfg.get("start_year", 2016)
        end_year = cfg.get("end_year", 2025)

        if train_window_years < 1 or test_window_years < 1:
            raise ValueError(
                "sliding train_window_years/test_window_years must be positive integers"
            )

        folds = []
        for y in range(
            start_year + train_window_years,
            end_year - test_window_years + 2,
            test_window_years,
        ):
            test_start = (
                pd.to_datetime(f"{y - 1}-12-31") + pd.Timedelta(days=embargo_days)
            ).strftime("%Y-%m-%d")
            folds.append(
                {
                    "fold_id": len(folds),
                    "train_start": f"{y - train_window_years}-01-01",
                    "train_end": f"{y - 1}-12-31",
                    "test_start": test_start,
                    "test_end": f"{y + test_window_years - 1}-12-31",
                }
            )
        return _bound_splits_to_data_range(folds, data_cfg)

    if strategy == "expanding":
        cfg = data_cfg.get("expanding", {})
        initial_train_years = cfg.get("initial_train_years", 5)
        test_window_years = cfg.get("test_window_years", 1)
        start_year = cfg.get("start_year", 2016)
        end_year = cfg.get("end_year", 2025)

        if initial_train_years < 1 or test_window_years < 1:
            raise ValueError(
                "expanding initial_train_years/test_window_years must be positive integers"
            )

        folds = []
        for y in range(
            start_year + initial_train_years,
            end_year - test_window_years + 2,
            test_window_years,
        ):
            test_start = (
                pd.to_datetime(f"{y - 1}-12-31") + pd.Timedelta(days=embargo_days)
            ).strftime("%Y-%m-%d")
            folds.append(
                {
                    "fold_id": len(folds),
                    "train_start": f"{start_year}-01-01",
                    "train_end": f"{y - 1}-12-31",
                    "test_start": test_start,
                    "test_end": f"{y + test_window_years - 1}-12-31",
                }
            )
        return _bound_splits_to_data_range(folds, data_cfg)

    if strategy == "regime":
        regimes = [
            {
                "name": "Regime 1: 대세 상승 후 반전 국면 (2017 ~ 2018 상반기)",
                "train_start": "2016-01-01",
                "train_end": "2016-12-31",
                "test_start": (
                    pd.to_datetime("2016-12-31") + pd.Timedelta(days=embargo_days)
                ).strftime("%Y-%m-%d"),
                "test_end": "2018-06-30",
            },
            {
                "name": "Regime 2: 초고변동성 및 유동성 장세 (2020 ~ 2021 상반기)",
                "train_start": "2017-01-01",
                "train_end": "2019-12-31",
                "test_start": (
                    pd.to_datetime("2019-12-31") + pd.Timedelta(days=embargo_days)
                ).strftime("%Y-%m-%d"),
                "test_end": "2021-06-30",
            },
            {
                "name": "Regime 3: 대세 하락 국면 (2022)",
                "train_start": "2019-01-01",
                "train_end": "2021-12-31",
                "test_start": (
                    pd.to_datetime("2021-12-31") + pd.Timedelta(days=embargo_days)
                ).strftime("%Y-%m-%d"),
                "test_end": "2022-12-31",
            },
            {
                "name": "Regime 4: 개별 종목 및 테마 순환매 장세 (2023 ~ 2024)",
                "train_start": "2020-01-01",
                "train_end": "2022-12-31",
                "test_start": (
                    pd.to_datetime("2022-12-31") + pd.Timedelta(days=embargo_days)
                ).strftime("%Y-%m-%d"),
                "test_end": "2024-12-31",
            },
        ]
        return _bound_splits_to_data_range(regimes, data_cfg)

    raise ValueError(f"지원하지 않는 split 전략: {strategy}")


def validate_embargo(splits: list[dict], embargo_days: int) -> bool:
    for split in splits:
        train_end = pd.to_datetime(split["train_end"])
        test_start = pd.to_datetime(split["test_start"])
        gap = (test_start - train_end).days
        if gap < embargo_days:
            print(
                f"[EMBARGO VIOLATION] Fold {split.get('fold_id', '?')}: "
                f"{split['train_end']} -> {split['test_start']} "
                f"(간격 {gap}일, 최소 {embargo_days}일 필요)"
            )
            return False
    return True


def _candidate_price_dirs(config: dict) -> list[Path]:
    """Find the configured processed-data directory without relying on CWD."""
    configured = Path(config.get("data", {}).get("price_dir", "data/processed"))
    if configured.is_absolute():
        return [configured]

    return [(Path(__file__).resolve().parent.parent / configured).resolve()]


def _universe_path(config: dict) -> Path:
    path = Path(config["data"]["universe_file"])
    return path if path.is_absolute() else Path(__file__).resolve().parent.parent / path


def resolve_tickers(config: dict, anchor_file: str) -> str | list[str]:
    """Use the frozen experiment universe when one is configured."""
    data = config.get("data", {})
    universe_file = data.get("universe_file")
    if not universe_file:
        return data.get("tickers", "")
    if data.get("tickers"):
        raise ValueError("Set either data.tickers or data.universe_file")
    path = _universe_path(config)
    with path.open(newline="", encoding="utf-8-sig") as source:
        rows = csv.DictReader(source)
        if "Code" not in (rows.fieldnames or []):
            raise ValueError(f"Universe file needs a Code column: {path}")
        codes = [row["Code"].strip().upper().zfill(6) for row in rows]
    has_intervals = {"ListingDate", "DelistingDate"} <= set(rows.fieldnames or [])
    if (
        not codes
        or (not has_intervals and len(codes) != len(set(codes)))
        or any(not code.isalnum() for code in codes)
    ):
        raise ValueError(f"Empty, duplicate or invalid universe codes: {path}")
    codes = list(dict.fromkeys(codes))
    processed = Path(find_processed_dir(config, anchor_file))
    missing = [code for code in codes if not (processed / f"{code}.parquet").is_file()]
    if missing:
        raise ValueError(
            f"Missing processed files for universe: {missing[:10]} ({len(missing)} total)"
        )
    return codes


def load_universe_intervals(config: dict) -> pd.DataFrame | None:
    """Read the existing listing/delisting metadata used for point-in-time membership."""
    if not config.get("data", {}).get("universe_file"):
        return None
    frame = pd.read_csv(_universe_path(config), dtype={"Code": str})
    if not {"Code", "ListingDate", "DelistingDate"} <= set(frame):
        raise ValueError("Point-in-time universe needs Code, ListingDate and DelistingDate columns")
    frame["Code"] = frame.Code.str.strip().str.upper().str.zfill(6)
    frame["ListingDate"] = pd.to_datetime(frame.ListingDate, errors="coerce")
    frame["DelistingDate"] = pd.to_datetime(frame.DelistingDate, errors="coerce")
    if frame.ListingDate.isna().any():
        raise ValueError("Universe ListingDate values must be valid")
    return frame


def data_fingerprint(config: dict) -> dict:
    """Return a low-cost data-source fingerprint for cache invalidation.

    The manifest hashes relative parquet names, byte sizes and nanosecond mtimes
    rather than scanning every file's full content on each training run.  Set
    ``data.version`` when replacing data while intentionally preserving those
    metadata values (for example, restoring an archive verbatim).
    """
    configured_version = config.get("data", {}).get("version")
    source_dir = next((path for path in _candidate_price_dirs(config) if path.is_dir()), None)
    if source_dir is None:
        return {"status": "missing", "configured_version": configured_version}

    digest = hashlib.sha256()
    count = 0
    for file_path in sorted(source_dir.rglob("*.parquet")):
        stat = file_path.stat()
        digest.update(str(file_path.relative_to(source_dir)).encode())
        if config.get("contract_version") == 3:
            from core.local_dataset import sha256

            digest.update(sha256(file_path).encode())
        else:
            digest.update(f"{stat.st_size}:{stat.st_mtime_ns}".encode())
        count += 1
    return {
        "status": "available",
        "configured_version": configured_version,
        "file_count": count,
        "manifest_sha256": digest.hexdigest(),
    }


def _hash_payload(config: dict, resolved_splits: list[dict], include_model: bool) -> dict:
    data_cfg = config.get("data", {})
    payload = {
        "cache_schema_version": CACHE_SCHEMA_VERSION,
        "data": {
            "tickers": data_cfg.get("tickers", None),
            "universe_file_sha256": (
                hashlib.sha256(_universe_path(config).read_bytes()).hexdigest()
                if data_cfg.get("universe_file")
                else None
            ),
            "universe": data_cfg.get("universe", None),
            "price_dir": data_cfg.get("price_dir", None),
            "data_fingerprint": data_fingerprint(config),
            "start_date": data_cfg.get("start_date", None),
            "end_date": data_cfg.get("end_date", None),
            "split_strategy": data_cfg.get("split_strategy", "single"),
            "embargo_days": data_cfg.get("embargo_days", 7),
            "splits": [split_identity(split) for split in resolved_splits],
        },
        "features": config.get("features", {}),
        "labels": config.get("labels", {}),
    }
    if config.get("contract_version") == 3:
        from core.local_dataset import sha256

        root = Path(__file__).resolve().parent
        implementations = [
            root / "train_src" / filename
            for filename in ("labels.py", "loaders.py", "lgbm_wrapper.py")
        ]
        payload["implementation"] = {str(p.name): sha256(p) for p in implementations}
        payload["feature_columns"] = config["feature_columns"]
        payload["dataset"] = config["dataset"]
        payload["class_weight"] = config.get("model", {}).get("params", {}).get("class_weight")
        payload["max_bin"] = config.get("model", {}).get("params", {}).get("max_bin", 255)
    if include_model:
        payload["model"] = config.get("model", {})
        if config.get("training"):
            payload["training"] = config.get("training", {})
    return payload


def generate_dataset_hash(config: dict, resolved_splits: list[dict]) -> str:
    hash_str = json.dumps(
        _hash_payload(config, resolved_splits, include_model=False), sort_keys=True
    )
    return hashlib.md5(hash_str.encode()).hexdigest()[:8]


def generate_predictions_hash(config: dict, resolved_splits: list[dict]) -> str:
    hash_str = json.dumps(
        _hash_payload(config, resolved_splits, include_model=True), sort_keys=True
    )
    return hashlib.md5(hash_str.encode()).hexdigest()[:8]


def experiments_dir(anchor_file: str) -> str:
    return os.path.dirname(os.path.abspath(anchor_file))


def chart_root(anchor_file: str) -> str:
    return os.path.dirname(experiments_dir(anchor_file))


def find_processed_dir(config: dict, anchor_file: str) -> str:
    path = _candidate_price_dirs(config)[0]
    if config.get("contract_version") == 3:
        from core.local_dataset import sha256

        manifest_path = path / "feature_manifest.json"
        if not manifest_path.exists():
            raise FileNotFoundError(
                "Run python -m experiments.features.build_feature_panel --config first"
            )
        manifest = json.loads(manifest_path.read_text())
        if manifest["feature_columns"] != config["feature_columns"]:
            raise ValueError("Feature list changed; prepare features again")
        for name, digest in manifest["file_hashes"].items():
            if not (path / name).exists() or sha256(path / name) != digest:
                raise ValueError(f"Modified/missing feature input {name}; prepare features again")
    return str(path)


def cache_dir(anchor_file: str) -> str:
    path = os.path.join(experiments_dir(anchor_file), "cache")
    os.makedirs(path, exist_ok=True)
    return path


def model_cache_dir(anchor_file: str) -> str:
    """Return the LightGBM wrapper's model cache location.

    Keep this path in one place so the dashboard reads the same models that
    ``train.py`` writes through ``train_src.lgbm_wrapper.LGBMWrapper``.
    """
    return os.path.join(experiments_dir(anchor_file), "train_src", "cache", "models")


def predictions_cache_path(config: dict, resolved_splits: list[dict], anchor_file: str) -> str:
    pred_hash = generate_predictions_hash(config, resolved_splits)
    return os.path.join(cache_dir(anchor_file), f"{pred_hash}_predictions.parquet")


def result_dir(config: dict, anchor_file: str) -> str:
    exp_name = config.get("experiment_name", "default_exp")
    if config.get("contract_version") == 3:
        from core.local_config import identity

        exp_name += "_" + identity(config)
    path = os.path.join(experiments_dir(anchor_file), "results", exp_name)
    os.makedirs(path, exist_ok=True)
    if config.get("contract_version") == 3:
        from core.local_config import atomic_json

        atomic_json(
            Path(path) / "run_manifest.json",
            {
                "config": config,
                "predictions_hash": generate_predictions_hash(config, resolve_splits(config)),
                "feature_columns": config["feature_columns"],
            },
        )
    return path


def label_params_from_config(config: dict) -> dict:
    labels = config.get("labels", {})
    return {
        "type": labels.get("type", "dynamic_sigma"),
        "horizon": labels["horizon"],
        "tp": labels.get("tp", 3.5),
        "sl": labels.get("sl", 2.0),
        "up_mult": labels.get("up_mult", 1.5),
        "down_mult": labels.get("down_mult", 1.2),
        "volatility_mode": labels.get("volatility_mode", "current_sigma"),
        "volatility_window": labels.get("volatility_window", 20),
        "ewma_span": labels.get("ewma_span", 20),
    }


def test_date_bounds(splits: list[dict]) -> tuple[str, str]:
    if not splits:
        raise ValueError("분할 폴드(Splits) 목록이 비어 있습니다.")

    starts = [pd.to_datetime(split["test_start"]) for split in splits]
    ends = [pd.to_datetime(split["test_end"]) for split in splits]
    return min(starts).strftime("%Y-%m-%d"), max(ends).strftime("%Y-%m-%d")


def load_predictions(
    config: dict, splits: list[dict], anchor_file: str, predictions_path: str = None
) -> pd.DataFrame:
    path = predictions_path or predictions_cache_path(config, splits, anchor_file)
    if not os.path.exists(path):
        pred_hash = generate_predictions_hash(config, splits)
        raise FileNotFoundError(
            "예측 결과 캐시를 찾을 수 없습니다.\n"
            f"  - path: {path}\n"
            f"  - expected hash: {pred_hash}\n"
            "먼저 train.py로 OOS 예측 캐시를 생성하세요."
        )

    if config.get("contract_version") == 3:
        manifest_path = Path(str(path) + ".manifest.json")
        if not manifest_path.exists():
            raise ValueError("Prediction manifest required; rerun train.py")
        manifest = json.loads(manifest_path.read_text())
        if (
            manifest.get("predictions_hash") != generate_predictions_hash(config, splits)
            or manifest.get("feature_columns") != config["feature_columns"]
        ):
            raise ValueError("Predictions belong to another run")
    if config.get("contract_version") == 3:
        from core.local_dataset import sha256

        if manifest.get("sha256") != sha256(path):
            raise ValueError("Prediction file changed; rerun train.py")
    predictions = pd.read_parquet(path)
    required_cols = {"Date", "Code", "Prob"}
    if config.get("contract_version") == 3:
        required_cols |= {"fold_id", "prob_down", "prob_neutral", "prob_up"}
    missing = required_cols - set(predictions.columns)
    if missing:
        raise ValueError(f"예측 캐시에 필수 컬럼이 없습니다: {sorted(missing)}")

    predictions = predictions.copy()
    predictions["Date"] = pd.to_datetime(predictions["Date"]).dt.tz_localize(None)
    if config.get("contract_version") == 3:
        import numpy as np

        probabilities = predictions[["prob_down", "prob_neutral", "prob_up"]].to_numpy()
        if (
            predictions.duplicated(["Date", "Code"]).any()
            or not np.isfinite(probabilities).all()
            or (probabilities < 0).any()
            or (probabilities > 1).any()
            or not np.allclose(probabilities.sum(axis=1), 1)
        ):
            raise ValueError("Invalid prediction keys/probabilities")
        for row in predictions.itertuples():
            matches = [
                split
                for split in splits
                if pd.Timestamp(split["test_start"]) <= row.Date <= pd.Timestamp(split["test_end"])
            ]
            if len(matches) != 1 or int(row.fold_id) != int(matches[0]["fold_id"]):
                raise ValueError("Prediction fold/date mismatch")
    return predictions.sort_values(["Date", "Code"]).reset_index(drop=True)


def build_fold_alignment(
    predictions: pd.DataFrame,
    splits: list[dict],
    eval_df: pd.DataFrame | None = None,
) -> tuple[pd.DataFrame, dict]:
    key_columns = ["Date", "Code"]
    if eval_df is not None:
        missing_key_columns = [column for column in key_columns if column not in eval_df.columns]
        if missing_key_columns:
            raise ValueError(f"평가 데이터에 키 컬럼이 없습니다: {missing_key_columns}")

    rows = []
    covered_mask = pd.Series(False, index=predictions.index)
    eval_covered_mask = pd.Series(False, index=eval_df.index) if eval_df is not None else None

    for idx, split in enumerate(splits):
        fold_id = int(split.get("fold_id", idx))
        fold_name = split.get("name", f"Fold {fold_id}")
        test_start = pd.to_datetime(split["test_start"])
        test_end = pd.to_datetime(split["test_end"])

        pred_mask = (predictions["Date"] >= test_start) & (predictions["Date"] <= test_end)
        covered_mask |= pred_mask

        row = {
            "fold_id": fold_id,
            "fold_name": fold_name,
            "test_start": split["test_start"],
            "test_end": split["test_end"],
            "prediction_rows": int(pred_mask.sum()),
        }

        if eval_df is not None:
            eval_mask = (eval_df["Date"] >= test_start) & (eval_df["Date"] <= test_end)
            eval_covered_mask |= eval_mask
            pred_rows = predictions.loc[pred_mask, key_columns]
            eval_rows = eval_df.loc[eval_mask, key_columns]
            pred_keys = pd.MultiIndex.from_frame(pred_rows.sort_values(key_columns))
            eval_keys = pd.MultiIndex.from_frame(eval_rows.sort_values(key_columns))
            row["evaluation_rows"] = int(len(eval_rows))
            row["prediction_duplicate_keys"] = int(pred_rows.duplicated(key_columns).sum())
            row["evaluation_duplicate_keys"] = int(eval_rows.duplicated(key_columns).sum())
            row["is_exact_row_match"] = bool(
                row["prediction_duplicate_keys"] == 0
                and row["evaluation_duplicate_keys"] == 0
                and pred_keys.equals(eval_keys)
            )
            row["merged_row_ratio"] = (
                float(row["evaluation_rows"] / row["prediction_rows"])
                if row["prediction_rows"] > 0
                else 0.0
            )

        rows.append(row)

    alignment_df = pd.DataFrame(rows)
    status = {
        "fold_count": len(splits),
        "prediction_total_rows": int(len(predictions)),
        "prediction_rows_in_config_folds": int(covered_mask.sum()),
        "prediction_rows_outside_config_folds": int((~covered_mask).sum()),
        "folds_with_predictions": int((alignment_df["prediction_rows"] > 0).sum())
        if not alignment_df.empty
        else 0,
    }

    if eval_df is not None:
        status["evaluation_total_rows"] = int(len(eval_df))
        status["evaluation_rows_in_config_folds"] = int(eval_covered_mask.sum())
        status["evaluation_rows_outside_config_folds"] = int((~eval_covered_mask).sum())
        status["folds_with_evaluation_rows"] = int((alignment_df["evaluation_rows"] > 0).sum())
        status["folds_with_equal_prediction_evaluation_rows"] = int(
            (alignment_df["prediction_rows"] == alignment_df["evaluation_rows"]).sum()
        )
        status["folds_with_exact_row_match"] = int(alignment_df["is_exact_row_match"].sum())

    status["is_exact_fold_match"] = (
        status["folds_with_predictions"] == len(splits)
        and status["prediction_rows_outside_config_folds"] == 0
        and status["prediction_rows_in_config_folds"] == status["prediction_total_rows"]
    )
    if eval_df is not None:
        status["is_exact_fold_match"] = (
            status["is_exact_fold_match"]
            and status["folds_with_evaluation_rows"] == len(splits)
            and status["evaluation_rows_outside_config_folds"] == 0
        )
        status["is_exact_row_match"] = status["is_exact_fold_match"] and status[
            "folds_with_exact_row_match"
        ] == len(splits)
    else:
        status["is_exact_row_match"] = status["is_exact_fold_match"]

    return alignment_df, status


def filter_to_test_fold_rows(frame: pd.DataFrame, splits: list[dict]) -> pd.DataFrame:
    """Return only rows whose Date belongs to the union of configured test folds.

    Evaluation labels are loaded with a right-side horizon buffer and may otherwise
    include embargo dates between folds.  Those dates are not OOS predictions and
    must not participate in exact key alignment or metrics.
    """
    if "Date" not in frame.columns:
        raise ValueError("test fold filtering requires a Date column")

    dates = pd.to_datetime(frame["Date"])
    in_test_fold = pd.Series(False, index=frame.index)
    for split in splits:
        in_test_fold |= (dates >= pd.to_datetime(split["test_start"])) & (
            dates <= pd.to_datetime(split["test_end"])
        )
    return frame.loc[in_test_fold].copy()
