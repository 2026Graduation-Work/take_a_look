from __future__ import annotations

import argparse
import json
import platform
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from experiments.features.psychology import (  # noqa: E402
    FEATURE_COLUMNS,
    FEATURE_PROFILE,
    GENERATOR_VERSION,
    TREATMENT_FEATURES,
    PsychologyFeatureConfig,
    PsychologyInputError,
    build_psychology_features,
)
from experiments.features.psychology.demo_panel import (  # noqa: E402
    DEMO_CODES,
    DEMO_SEED,
    build_demo_price_panel,
)
from shared.data.resolution_snapshot import PRICE_POLICY, price_store_manifest  # noqa: E402
from shared.data.segmented_prices import validate_segments  # noqa: E402

DEFAULT_OUTPUT = "data/external/psychology_market_v1.parquet"


def chart_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _resolve_chart_path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else (chart_root() / path).resolve()


def _read_price_frame(path: Path) -> pd.DataFrame:
    if path.suffix.lower() == ".csv":
        return pd.read_csv(path, dtype={"Code": "string"})
    return pd.read_parquet(path)


def _segmented_store(folder):
    return price_store_manifest(folder).get("price_policy") == PRICE_POLICY


def load_price_panel(
    *,
    price_dir: Path | None = None,
    price_file: Path | None = None,
    demo: bool = False,
    demo_periods: int = 180,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    if demo:
        panel = build_demo_price_panel(periods=demo_periods)
        return panel, {
            "kind": "synthetic_demo_panel",
            "seed": DEMO_SEED,
            "codes": list(DEMO_CODES),
            "periods": demo_periods,
            "warning": "합성 데이터입니다. 연구 결과로 보고하지 마세요.",
        }
    if price_file is not None:
        frame = _read_price_frame(price_file)
        validate_segments(frame, required=_segmented_store(price_file.parent))
        return frame, {"kind": "file", "path": str(price_file)}
    if price_dir is None:
        raise PsychologyInputError("--price-dir, --price-file, --demo 중 하나가 필요합니다.")
    files = sorted(path for path in price_dir.glob("*.parquet") if path.name != "sample_keys.parquet")
    if not files:
        raise PsychologyInputError(f"가격 Parquet이 없습니다: {price_dir}")
    frames = []
    segmented = _segmented_store(price_dir)
    for file in files:
        frame = _read_price_frame(file)
        if "Code" not in frame.columns:
            frame = frame.assign(Code=file.stem)
        validate_segments(frame, required=segmented)
        frames.append(frame[[column for column in frame.columns if column in _WANTED_COLUMNS]])
    panel = pd.concat(frames, ignore_index=True)
    return panel, {"kind": "directory", "path": str(price_dir), "files": len(files)}


_WANTED_COLUMNS = {"Date", "Code", "Close", "Volume", "SegmentId"}


def _filter_panel(
    panel: pd.DataFrame,
    *,
    codes: list[str] | None,
    start: str | None,
    end: str | None,
) -> pd.DataFrame:
    filtered = panel
    if codes:
        wanted = {code.strip().zfill(6) for code in codes}
        filtered = filtered.loc[
            filtered["Code"].astype("string").str.strip().str.zfill(6).isin(wanted)
        ]
    if start or end:
        dates = pd.to_datetime(filtered["Date"], errors="coerce")
        if start:
            filtered = filtered.loc[dates >= pd.Timestamp(start)]
            dates = dates.loc[filtered.index]
        if end:
            filtered = filtered.loc[dates <= pd.Timestamp(end)]
    if filtered.empty:
        raise PsychologyInputError("종목·기간 필터 뒤에 남은 행이 없습니다.")
    return filtered.reset_index(drop=True)


def _metadata_path(output_path: Path) -> Path:
    return output_path.with_suffix(".meta.json")


def write_outputs(
    features: pd.DataFrame,
    metadata: dict[str, Any],
    output_path: Path,
    *,
    overwrite: bool = False,
) -> Path:
    if output_path.exists() and not overwrite:
        raise FileExistsError(
            f"기존 산출물을 덮어쓰지 않습니다: {output_path}. --overwrite를 쓰거나 새 경로를 지정하세요."
        )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    features.to_parquet(output_path, index=False)
    with _metadata_path(output_path).open("w", encoding="utf-8") as handle:
        json.dump(metadata, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
    return output_path


def write_sample_csv(features: pd.DataFrame, sample_path: Path, rows: int) -> Path:
    sample_path.parent.mkdir(parents=True, exist_ok=True)
    sample = features.groupby("Code", sort=True, observed=True).head(rows)
    sample = sample.sort_values(["Code", "Date"], kind="stable")
    sample.to_csv(sample_path, index=False, float_format="%.10g", lineterminator="\n")
    return sample_path


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="가격·거래량에서 시장 심리 피처를 생성합니다.")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--price-dir", type=Path, help="<Code>.parquet이 있는 가격 패널 디렉터리")
    source.add_argument("--price-file", type=Path, help="단일 가격 Parquet/CSV")
    source.add_argument(
        "--demo",
        action="store_true",
        help="시드 고정 합성 패널로 생성한다(형식·결정론 확인용, 연구 결과 아님)",
    )
    parser.add_argument("--demo-periods", type=int, default=180, help="합성 패널 거래일 수")
    parser.add_argument("--out", type=Path, default=Path(DEFAULT_OUTPUT), help="출력 Parquet 경로")
    parser.add_argument("--codes", help="쉼표로 구분한 6자리 종목 코드 목록")
    parser.add_argument("--start", help="시작일 YYYY-MM-DD")
    parser.add_argument("--end", help="종료일 YYYY-MM-DD")
    parser.add_argument("--overwrite", action="store_true", help="기존 산출물을 덮어쓴다")
    parser.add_argument("--sample-csv", type=Path, help="소규모 검증 샘플 CSV 경로")
    parser.add_argument("--sample-rows", type=int, default=10, help="종목당 샘플 행 수")
    for field, default in (
        ("fear-greed-window", PsychologyFeatureConfig.fear_greed_window),
        ("herding-window", PsychologyFeatureConfig.herding_window),
        ("overreaction-short-window", PsychologyFeatureConfig.overreaction_short_window),
        ("overreaction-long-window", PsychologyFeatureConfig.overreaction_long_window),
        ("disposition-window", PsychologyFeatureConfig.disposition_window),
    ):
        parser.add_argument(f"--{field}", type=int, default=default, help=f"기본값 {default}")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    config = PsychologyFeatureConfig(
        fear_greed_window=args.fear_greed_window,
        herding_window=args.herding_window,
        overreaction_short_window=args.overreaction_short_window,
        overreaction_long_window=args.overreaction_long_window,
        disposition_window=args.disposition_window,
    )
    try:
        panel, source_info = load_price_panel(
            price_dir=_resolve_chart_path(args.price_dir) if args.price_dir else None,
            price_file=_resolve_chart_path(args.price_file) if args.price_file else None,
            demo=args.demo,
            demo_periods=args.demo_periods,
        )
        codes = args.codes.split(",") if args.codes else None
        panel = _filter_panel(panel, codes=codes, start=args.start, end=args.end)
        features, metadata = build_psychology_features(panel, config)
    except (ValueError, FileNotFoundError) as error:
        parser.exit(2, f"심리 피처 생성 오류: {error}\n")

    metadata["source"] = source_info
    metadata["selection"] = {"codes": codes, "start": args.start, "end": args.end}
    metadata["environment"] = {
        "python": platform.python_version(),
        "pandas": pd.__version__,
        "numpy": np.__version__,
    }

    output_path = _resolve_chart_path(args.out)
    try:
        write_outputs(features, metadata, output_path, overwrite=args.overwrite)
    except FileExistsError as error:
        parser.exit(2, f"심리 피처 생성 오류: {error}\n")
    if args.sample_csv:
        write_sample_csv(features, _resolve_chart_path(args.sample_csv), args.sample_rows)

    print(f"profile: {FEATURE_PROFILE} (generator {GENERATOR_VERSION})")
    print(f"출력: {output_path}")
    print(f"메타데이터: {_metadata_path(output_path)}")
    print(f"행 수: {metadata['output']['rows']} / 종목 수: {metadata['output']['codes']}")
    print(f"기간: {metadata['output']['start_date']} ~ {metadata['output']['end_date']}")
    print(f"피처 컬럼: {', '.join(FEATURE_COLUMNS)}")
    print(f"features.treatment 권장: {', '.join(TREATMENT_FEATURES)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
