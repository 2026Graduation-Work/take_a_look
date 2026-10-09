"""Config-driven local preprocessing. Warmup and price paths are preserved."""
import argparse
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.local_features import (
    generate_full_alpha158_features as generate_full_alpha158_features,  # noqa: E402
)
from core.local_features import normalize_trading_halts as normalize_trading_halts  # noqa: E402
from data_collectors.trading_calendar import get_krx_trading_days  # noqa: E402


def _load_trading_days_for_files(raw_files: list[str]) -> set:
    """원본 파일 전체 기간을 덮는 KRX 캘린더를 한 번만 조회합니다."""
    min_date = None
    max_date = None
    for file_path in raw_files:
        try:
            dates = pd.to_datetime(pd.read_parquet(file_path, columns=["Date"])["Date"])
        except Exception:
            continue
        if dates.empty:
            continue
        file_min = dates.min()
        file_max = dates.max()
        min_date = file_min if min_date is None else min(min_date, file_min)
        max_date = file_max if max_date is None else max(max_date, file_max)

    if min_date is None or max_date is None:
        return set()
    return get_krx_trading_days(
        min_date.strftime("%Y-%m-%d"), max_date.strftime("%Y-%m-%d")
    )


def _processed_has_actual_vwap(file_path: str) -> bool:
    """구형 HLC3 기반 processed 파일과 실제 VWAP 기반 파일을 구분합니다."""
    try:
        pd.read_parquet(file_path, columns=["VWAP"])
        return True
    except Exception:
        return False


def main():
    from core.local_dataset import preprocess_dataset
    parser = argparse.ArgumentParser(description="Local past-only preprocessing")
    parser.add_argument("--config", required=True)
    parser.add_argument("--mode", choices=["full", "update"], default="full")
    parser.add_argument("--rebuild", action="store_true")
    parser.add_argument(
        "--allow-partial", action="store_true",
        help="Use verified available price files even when collection is incomplete; report exclusions",
    )
    args = parser.parse_args()
    if args.rebuild and args.mode != "full":
        parser.error("--rebuild requires full")
    preprocess_dataset(
        args.config, rebuild=args.rebuild or args.mode == "update",
        allow_partial=args.allow_partial,
    )


if __name__ == "__main__":
    main()
