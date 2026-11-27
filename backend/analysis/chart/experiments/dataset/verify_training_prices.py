"""Replay a local KRX training dataset from preserved bars and official actions."""

import argparse
import csv
import json
from pathlib import Path

import pandas as pd
from experiments.dataset.pipeline import (
    _require_current_training_prices,
    eligible_training_prices,
    listing_identity,
    verify_training_metadata,
)
from shared.data.resolution_snapshot import SEGMENT_COLUMN, require_price_provenance
from shared.data.segmented_prices import (
    ADJUSTMENT_COLUMNS,
    adjust_training_window,
    validate_segments,
)
from shared.data.training_prices import load_training_raw
from shared.data.validation import expected_sessions
from shared.io import sha256


def verify(root):
    manifest = json.loads((root / "dataset_manifest.json").read_text())
    snapshot = _require_current_training_prices(manifest, root, verify_archive=True)
    if not manifest.get("prices_complete"):
        raise ValueError("Verify a complete KRX training dataset")
    calendar = json.loads((root / "calendar.json").read_text())
    metadata = verify_training_metadata(root, snapshot, manifest["config"]["collection"], calendar)
    expected_files = {f"{code}.parquet" for code in metadata.Code}
    if set(manifest["raw_files"]) != expected_files or set(manifest["krx_raw_files"]) != expected_files:
        raise ValueError("Dataset files differ from the pinned listing scope")
    selected = {listing_identity(row) for row in metadata.itertuples()}
    review = root / "review_queue.csv"
    if sha256(review) != manifest["review_queue"]["sha256"]:
        raise ValueError("The review queue hash differs from the manifest")
    with review.open(newline="", encoding="utf-8") as stream:
        rows = list(csv.DictReader(stream))
    expected_review = sorted(snapshot.review_rows(selected), key=lambda row: (row["Code"], row["Date"]))
    if len(rows) != manifest["review_queue"]["rows"] or rows != [
        {key: str(value) for key, value in row.items()} for row in expected_review
    ]:
        raise ValueError("The review queue differs from the pinned resolutions")
    processed_path = root / "processed_manifest.json"
    processed = json.loads(processed_path.read_text()) if processed_path.is_file() else None
    if processed and (processed["dataset_manifest_sha256"] != sha256(root / "dataset_manifest.json")
                      or require_price_provenance(processed) != snapshot.provenance):
        raise ValueError("Processed provenance differs from the verified dataset")
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
        checked_events, checked_prices = [], []
        validate_segments(stored, required=True)
        for row in intervals.itertuples():
            security = listing_identity(row)
            days = snapshot.days(security)
            reviewed, applied = adjust_training_window(
                security, raw.loc[raw.Date.isin(days)].reset_index(drop=True), days, manifest["end_date"], snapshot,
            )
            checked_prices.append(reviewed.assign(Code=row.Code, Name=row.Name, IsDelisted=row.IsDelisted))
            if not applied.empty:
                checked_events.append(applied)
        replay = pd.concat(checked_prices, ignore_index=True)
        pd.testing.assert_frame_equal(stored[replay.columns], replay, check_dtype=False)
        eligible = eligible_training_prices(replay, intervals, snapshot)
        spac_rows = len(replay) - len(eligible)
        if processed:
            if spac_rows != processed["spac_excluded_rows"].get(name, 0):
                raise ValueError(f"{code}: SPAC policy exclusion differs from the replay")
            if name in processed["files"]:
                processed_file = root / "processed" / name
                if sha256(processed_file) != processed["files"][name]:
                    raise ValueError(f"{code}: processed prices changed")
                keys = ["Date", SEGMENT_COLUMN]
                pd.testing.assert_frame_equal(pd.read_parquet(processed_file, columns=keys),
                                              eligible[keys].reset_index(drop=True), check_dtype=False)
            elif not eligible.empty and not processed.get("allow_partial"):
                raise ValueError(f"{code}: eligible segments are missing from processed prices")
        applied = (pd.concat(checked_events, ignore_index=True) if checked_events
                   else pd.DataFrame(columns=ADJUSTMENT_COLUMNS))
        applied["ExDate"] = pd.to_datetime(applied.ExDate)
        pd.testing.assert_frame_equal(saved_events.loc[saved_events.Code.eq(code)].reset_index(drop=True),
                                      applied, check_dtype=False)
        checks.append({"code": code, "raw_rows": len(raw), "applied_events": len(applied), "spac_excluded_rows": spac_rows})
    if len(saved_events) != manifest["price_events"]["rows"] or len(saved_events) != sum(
        check["applied_events"] for check in checks
    ):
        raise ValueError("Applied event table includes unverified rows")
    return checks


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(verify(args.root), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
