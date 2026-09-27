"""Publish a cached real-price, legacy-feature preview to local Supabase.

This preview does not certify feature parity with the active production builder.
"""

import argparse
import json
import os
import re
from datetime import timedelta
from pathlib import Path
from urllib.parse import urlparse

import pandas as pd
import yaml

from .pack import load_pack
from .persistence import SupabaseStore
from .publish import publish
from .run_daily import build_batch, frame_hash


def require_local_url(url):
    parsed = urlparse(url)
    if parsed.scheme != "http" or parsed.hostname not in {"localhost", "127.0.0.1", "::1"}:
        raise ValueError("local_preview requires a loopback HTTP Supabase URL")


def load_cached_input(data_root, code, requested_date=None):
    if not re.fullmatch(r"[0-9]{6}", code):
        raise ValueError("Stock code must have six digits")
    path = data_root / "raw" / f"{code}.parquet"
    raw = pd.read_parquet(path)
    processed = pd.read_parquet(data_root / "processed" / f"{code}.parquet")
    raw["Date"] = pd.to_datetime(raw["Date"])
    processed["Date"] = pd.to_datetime(processed["Date"])
    if raw.Date.isna().any() or raw.Date.duplicated().any():
        raise ValueError("Cached dates are missing or duplicated")
    raw = raw.sort_values("Date")
    as_of = pd.Timestamp(requested_date if requested_date else processed.Date.max())
    if as_of > raw.Date.max() or as_of not in set(raw.Date) or as_of not in set(processed.Date):
        raise ValueError("Requested date is absent from cached prices or legacy features")
    start = pd.Timestamp(as_of.date() - timedelta(days=240))
    raw = raw.loc[raw.Date.between(start, as_of)].reset_index(drop=True)
    if len(raw) < 100:
        raise ValueError("Cached price window is too short")
    name = str(raw.iloc[-1]["Name"])
    current = processed.loc[processed.Date.eq(as_of)].copy()
    if len(current) != 1 or not pd.notna(current.iloc[0].Sigma):
        raise ValueError("No complete legacy feature row on cached date")
    return as_of.date().isoformat(), name, raw, current


def run(args):
    if not args.compute_only:
        require_local_url(os.environ.get("SUPABASE_URL", ""))
    root = Path(os.environ.get("CHART_SERVING_DATA_DIR", Path(__file__).parent / "data"))
    as_of, name, raw, current = load_cached_input(root, args.code, args.as_of)
    config = yaml.safe_load(Path(__file__).with_name("config.yaml").read_text())["active_pack"]
    pack, paths = load_pack(root / "packs" / config["pack_id"])
    # Give legacy input a separate release identity so this local preview can
    # never be mistaken for the production alpha158_actual_vwap_v1 builder.
    pack = dict(pack, pack_id=pack["pack_id"] + "_legacy_preview",
                feature_builder_id="legacy_processed_unverified_preview")
    digest = frame_hash(raw)
    universe = pd.DataFrame({"Code": [args.code], "Name": [name]})
    if not args.compute_only:
        store = SupabaseStore()
        store.save_universe(as_of, universe)
        store.upsert_prices(args.code, raw)
        store.upload_features(args.code, as_of, pack["feature_builder_id"], digest, current)
    frames = {args.code: (raw, current.iloc[0].to_dict(), current)}
    batch, snapshots = build_batch(as_of, pack, paths, universe, frames, {}, {args.code: digest})
    out = root / "batches" / batch["id"]
    out.mkdir(parents=True, exist_ok=True)
    (out / "batch.json").write_text(json.dumps(batch, ensure_ascii=False, indent=2))
    (out / "snapshots.json").write_text(json.dumps(snapshots, ensure_ascii=False))
    if args.publish:
        publish(batch, snapshots, pack)
    event = "local_preview_published" if args.publish else (
        "local_preview_computed" if args.compute_only else "local_preview_staged")
    print(json.dumps({"event": event,
                      "as_of": as_of, "stock_code": args.code, "batch_id": batch["id"],
                      "sample_counts": {str(item["horizon"]): item["distribution"]["sample_count"]
                                        for item in snapshots}}))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--code", default="005930", help="Cached six-digit stock code")
    parser.add_argument("--as-of", help="Cached actual price date; defaults to latest cached date")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--publish", action="store_true", help="Publish to local Supabase for the frontend")
    mode.add_argument("--compute-only", action="store_true", help="Compute snapshots without Supabase")
    run(parser.parse_args(argv))


if __name__ == "__main__":
    main()
