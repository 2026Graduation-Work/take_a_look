"""Daily and cached-preview chart serving flow."""

import hashlib
import io
import json
import os
import re
import time
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

import lightgbm as lgb
import pandas as pd
import yaml

from .calendar import refresh_krx_trading_days
from .distribution import SampleIndex
from .features import build_feature_frame
from .hashing import canonical_hash
from .inference import infer_batch
from .pack import load_pack
from .prices import fetch_prices, price_snapshot
from .snapshot import build_snapshot, unavailable_snapshot
from .storage import SupabaseStore

KST = ZoneInfo("Asia/Seoul")


def official_day(requested=None):
    now = datetime.now(KST)
    day = pd.Timestamp(requested).date() if requested else (now.date() if now.hour >= 18 else now.date() - timedelta(days=1))
    if day > now.date() or (day == now.date() and now.hour < 18):
        raise ValueError("Requested daily data is not confirmed yet")
    return day.isoformat()


def fetch_universe(as_of, code=None):
    from pykrx import stock

    if code:
        if not re.fullmatch(r"[0-9]{6}", code):
            raise ValueError("Stock code must be six digits")
        codes = [code]
    else:
        codes = stock.get_market_ticker_list(as_of.replace("-", ""), market="KOSPI")
        if not 500 <= len(codes) <= 1200:
            raise ValueError("Invalid KOSPI universe size")
    rows = pd.DataFrame({"Code": codes, "Name": [stock.get_market_ticker_name(item) for item in codes]})
    if (rows.Code.duplicated().any() or not rows.Code.str.fullmatch(r"[0-9]{6}").all()
            or rows.Name.isna().any() or not rows.Name.astype(str).str.strip().all()):
        raise ValueError("Invalid KOSPI universe")
    return rows.sort_values("Code").reset_index(drop=True)


def frame_hash(frame):
    buffer = io.BytesIO()
    frame.to_parquet(buffer, index=False)
    return hashlib.sha256(buffer.getvalue()).hexdigest()


def _retry_fetch(code, start, as_of):
    for attempt in range(3):
        try:
            return fetch_prices(code, start, as_of)
        except (OSError, TimeoutError, ConnectionError):
            if attempt == 2:
                raise
            time.sleep(2 * (attempt + 1))


def collect(as_of, store, *, replay=False, code=None, historical_test=False):
    start = (pd.Timestamp(as_of) - pd.Timedelta(days=240)).date().isoformat()
    days = refresh_krx_trading_days(start, as_of)
    if pd.Timestamp(as_of).date() not in days:
        return None
    if replay:
        universe = store.load_universe(as_of)
        if universe.empty:
            raise ValueError("Historical date lacks an archived universe")
    else:
        universe = fetch_universe(as_of, code=code)
        if not historical_test:
            store.save_universe(as_of, universe)
    if universe.Code.duplicated().any():
        raise ValueError("Duplicate archived universe")
    frames, unavailable, raw_hashes = {}, {}, {}
    for row in universe.itertuples():
        code = row.Code
        try:
            stored = pd.DataFrame() if historical_test else store.load_prices(code, start, as_of)
            if replay:
                if stored.empty or stored.Date.max().date().isoformat() != as_of:
                    raise ValueError(f"Historical inputs absent for {code}/{as_of}")
                raw = stored
            else:
                fresh = _retry_fetch(code, start, as_of)
                if fresh.Date.max().date().isoformat() != as_of:
                    unavailable[code] = "price_not_confirmed_for_session"
                    continue
                # Requery the entire feature window: adjusted past prices can change.
                store.upsert_prices(code, fresh)
                raw = pd.concat([stored, fresh], ignore_index=True).drop_duplicates("Date", keep="last")
            raw = raw.sort_values("Date").reset_index(drop=True)
            if raw.empty or raw.Date.max().date().isoformat() != as_of:
                unavailable[code] = "price_not_confirmed_for_session"
                continue
            features = build_feature_frame(raw, days)
            current = features.loc[pd.to_datetime(features.Date).eq(pd.Timestamp(as_of))]
            if len(current) != 1 or not pd.notna(current.iloc[0].Sigma):
                unavailable[code] = "feature_row_missing"
                continue
            digest = frame_hash(raw)
            store.upload_features(code, as_of, "alpha158_actual_vwap_v1", digest, features)
            frames[code] = (raw, current.iloc[0].to_dict())
            raw_hashes[code] = digest
        except ValueError as exc:
            if replay:
                raise
            if "KRX prices unavailable" not in str(exc):
                raise
            unavailable[code] = "price_source_unavailable"
    if not frames:
        raise ValueError("No confirmed stock inputs; previous batch retained")
    return universe, frames, unavailable, raw_hashes


def build_batch(as_of, pack, paths, universe, frames, unavailable, raw_hashes):
    names = dict(zip(universe.Code, universe.Name))
    codes = sorted(names)
    batch_id = canonical_hash({"as_of": as_of, "pack_id": pack["pack_id"],
                               "builder": pack["feature_builder_id"], "names": names,
                               "raw_hashes": raw_hashes, "unavailable": unavailable})
    snapshots = []
    for horizon in (5, 20):
        item = pack["horizons"][f"h{horizon}"]
        model_path, samples_path = paths[horizon]
        model = lgb.Booster(model_file=str(model_path))
        selected = list(frames)
        current = pd.DataFrame([frames[code][1] for code in selected])
        predictions = infer_batch(model, current)
        by_code = dict(zip(selected, predictions))
        history = SampleIndex(pd.read_parquet(samples_path))
        for code in codes:
            if code in unavailable:
                snapshots.append(unavailable_snapshot(
                    code=code, stock_name=names[code], as_of=as_of, horizon=horizon,
                    pack_id=pack["pack_id"], batch_id=batch_id,
                    reason=unavailable[code], model_sha256=item["model_sha256"],
                    samples_sha256=item["samples_sha256"], config_sha256=canonical_hash(pack)))
                continue
            raw, row = frames[code]
            scores, contributions, features_hash = by_code[code]
            sigma, close = float(row["Sigma"]), float(row["Close"])
            up, down = (item["label_barriers"][key] for key in ("up_mult", "down_mult"))
            inference = {"status": "available", "reason": None, "scores": scores,
                         "score_event": "class_2_upper_barrier_first", "close": close,
                         "sigma": sigma, "barriers": {"up": close * (1 + up * sigma),
                                                       "down": close * (1 - down * sigma)},
                         "contribution_space": "class_2_raw_margin", "features": contributions}
            price = price_snapshot(raw, code, as_of, "KRX adjusted daily OHLCV")
            if price["status"] != "available":
                raise ValueError(f"Stale price in batch: {code}")
            distribution = history.distribution(horizon=horizon, score=scores["up"], sigma=sigma, as_of=as_of)
            snapshots.append(build_snapshot(
                code=code, stock_name=names[code], as_of=as_of, horizon=horizon,
                pack_id=pack["pack_id"], batch_id=batch_id, inference=inference,
                distribution=distribution,
                prices={"basis": "adjusted_close", "source": price["source"], "history": price["history"]},
                sources={"model_sha256": item["model_sha256"], "features_sha256": features_hash,
                         "prices_sha256": raw_hashes[code], "cases_sha256": item["samples_sha256"],
                         "config_sha256": canonical_hash(pack)}))
    batch = {"id": batch_id, "as_of": as_of, "pack_id": pack["pack_id"],
             "release_h5": pack["pack_id"] + ":h5", "release_h20": pack["pack_id"] + ":h20",
             "expected_stock_codes": codes, "status": "staging",
             "result": {"snapshot_count": len(snapshots), "unavailable_count": len(unavailable) * 2}}
    return batch, snapshots


def data_root():
    return Path(os.environ.get("CHART_SERVING_DATA_DIR", Path(__file__).parents[1] / "data"))


def active_pack(root=None):
    config = yaml.safe_load((Path(__file__).parents[1] / "config.yaml").read_text())["active_pack"]
    return load_pack((root or data_root()) / "packs" / config["pack_id"])


def write_batch(root, batch, snapshots):
    out = root / "batches" / batch["id"]
    out.mkdir(parents=True, exist_ok=True)
    (out / "batch.json").write_text(json.dumps(batch, ensure_ascii=False, indent=2))
    (out / "snapshots.json").write_text(json.dumps(snapshots, ensure_ascii=False))


def run(args):
    root = data_root()
    as_of = official_day(args.as_of)
    historical_test = getattr(args, "historical_test", False)
    if historical_test:
        require_local_url(os.environ.get("SUPABASE_URL", ""))
        if as_of == datetime.now(KST).date().isoformat():
            raise ValueError("--historical-test requires a past date")
    pack, paths = active_pack(root)
    store = SupabaseStore()
    replay = pd.Timestamp(as_of).date() != datetime.now(KST).date() and not historical_test
    collected = collect(as_of, store, replay=replay, code=args.code if historical_test else None,
                        historical_test=historical_test)
    if collected is None:
        print(json.dumps({"event": "holiday", "as_of": as_of, "pack_id": pack["pack_id"]}))
        return
    batch, snapshots = build_batch(as_of, pack, paths, *collected)
    if historical_test:
        batch["result"]["historical_test"] = True
    write_batch(root, batch, snapshots)
    if args.publish:
        store.publish(batch, snapshots, pack)
    print(json.dumps({"event": "published" if args.publish else ("historical_test" if historical_test else "dry_run"), "as_of": as_of,
                      "pack_id": pack["pack_id"], "stock_count": len(batch["expected_stock_codes"]),
                      "batch_id": batch["id"], **batch["result"]}))


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


def run_preview(args):
    if not args.compute_only:
        require_local_url(os.environ.get("SUPABASE_URL", ""))
    root = data_root()
    as_of, name, raw, current = load_cached_input(root, args.code, args.as_of)
    pack, paths = active_pack(root)
    # Give legacy input a separate release identity so this local preview can
    # never be mistaken for the production alpha158_actual_vwap_v1 builder.
    pack = dict(pack, pack_id=pack["pack_id"] + "_legacy_preview",
                feature_builder_id="legacy_processed_unverified_preview")
    digest = frame_hash(raw)
    universe = pd.DataFrame({"Code": [args.code], "Name": [name]})
    store = None if args.compute_only else SupabaseStore()
    if store:
        store.save_universe(as_of, universe)
        store.upsert_prices(args.code, raw)
        store.upload_features(args.code, as_of, pack["feature_builder_id"], digest, current)
    frames = {args.code: (raw, current.iloc[0].to_dict())}
    batch, snapshots = build_batch(as_of, pack, paths, universe, frames, {}, {args.code: digest})
    write_batch(root, batch, snapshots)
    if args.publish:
        store.publish(batch, snapshots, pack)
    event = "local_preview_published" if args.publish else (
        "local_preview_computed" if args.compute_only else "local_preview_staged")
    print(json.dumps({"event": event,
                      "as_of": as_of, "stock_code": args.code, "batch_id": batch["id"],
                      "sample_counts": {str(item["horizon"]): item["distribution"]["sample_count"]
                                        for item in snapshots}}))
