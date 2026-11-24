"""Replay a local KRX training dataset from preserved bars and official actions."""

import argparse
import json
from pathlib import Path

import pandas as pd
from experiments.dataset.pipeline import _require_current_training_prices
from shared.data.events import EVENT_COLUMNS
from shared.data.training_prices import adjust_training_window, load_training_raw
from shared.data.validation import expected_sessions
from shared.io import sha256


def verify(root):
    manifest = json.loads((root / "dataset_manifest.json").read_text())
    provenance = _require_current_training_prices(manifest, root)
    if not manifest.get("prices_complete"):
        raise ValueError("Verify a complete KRX training dataset")
    snapshot_path = root / "official_actions" / f"{provenance['sha256']}.json"
    snapshot = json.loads(snapshot_path.read_text())
    calendar = json.loads((root / "calendar.json").read_text())
    metadata = pd.read_csv(root / "ticker_metadata.csv", dtype={"Code": str},
                           parse_dates=["ListingDate", "DelistingDate"])
    event_path = root / manifest["price_events"]["path"]
    if sha256(event_path) != manifest["price_events"]["sha256"]:
        raise ValueError("The applied event table hash differs from the manifest")
    saved_events = pd.read_parquet(event_path)
    checks = []
    for name, digest in sorted(manifest["raw_files"].items()):
        code = Path(name).stem
        path = root / "raw" / name
        if sha256(path) != digest:
            raise ValueError(f"{code}: adjusted price hash differs from the manifest")
        stored = pd.read_parquet(path)
        intervals = metadata.loc[metadata.Code.eq(code)]
        raw = load_training_raw(root / "krx_raw_prices" / name, expected_sessions(intervals, calendar),
                                manifest["krx_raw_files"][name])
        checked_events = []
        for i, interval in intervals.iterrows():
            days = expected_sessions(intervals.loc[[i]], calendar)
            if days.empty:
                continue
            reviewed, applied = adjust_training_window(
                code, raw.loc[raw.Date.isin(days)].reset_index(drop=True), days, manifest["end_date"], snapshot,
                listing=interval.ListingDate.date(),
                delisting=None if pd.isna(interval.DelistingDate) else interval.DelistingDate.date(),
                isin=None if pd.isna(interval.get("Isin")) else interval.Isin,
                market=interval.Market,
            )
            matched = stored.loc[stored.Date.isin(days), reviewed.columns].reset_index(drop=True)
            pd.testing.assert_frame_equal(matched, reviewed, check_dtype=False)
            if not applied.empty:
                checked_events.append(applied)
        applied = pd.concat(checked_events, ignore_index=True) if checked_events else pd.DataFrame(columns=EVENT_COLUMNS)
        applied["ExDate"] = pd.to_datetime(applied.ExDate)
        pd.testing.assert_frame_equal(saved_events.loc[saved_events.Code.eq(code)].reset_index(drop=True),
                                      applied, check_dtype=False)
        checks.append({"code": code, "raw_rows": len(raw), "applied_events": len(applied)})
    return checks


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(verify(args.root), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
