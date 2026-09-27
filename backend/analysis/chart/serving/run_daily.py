"""Collect confirmed KRX prices, infer H5/H20, and publish one atomic batch."""

import argparse
import io
import json
import os
import time
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import lightgbm as lgb
import pandas as pd
import yaml

from .calendar import refresh_krx_trading_days
from .features import build_feature_frame
from .hashing import canonical_hash
from .inference import infer_batch
from .output import price_snapshot
from .pack import load_pack
from .persistence import SupabaseStore
from .prices import fetch_prices
from .sample_distribution import SampleIndex
from .snapshot import build_snapshot, unavailable_snapshot

KST = ZoneInfo("Asia/Seoul")


def official_day(requested=None):
    now = datetime.now(KST)
    day = pd.Timestamp(requested).date() if requested else (now.date() if now.hour >= 18 else now.date() - timedelta(days=1))
    if day > now.date() or (day == now.date() and now.hour < 18):
        raise ValueError("Requested daily data is not confirmed yet")
    return day.isoformat()


def fetch_universe(as_of):
    import FinanceDataReader as fdr

    listing = fdr.StockListing("KOSPI-DESC")
    required = {"Code", "Name", "Market", "ListingDate"}
    if required - set(listing):
        raise ValueError("KOSPI listing lacks required fields")
    rows = listing.loc[listing.Market.eq("KOSPI")].copy()
    rows["Code"] = rows.Code.astype(str).str.zfill(6)
    rows = rows.loc[pd.to_datetime(rows.ListingDate).le(as_of), ["Code", "Name"]]
    if rows.Code.duplicated().any() or not rows.Code.str.fullmatch(r"[0-9]{6}").all() or not 500 <= len(rows) <= 1200:
        raise ValueError("Invalid current KOSPI universe")
    return rows.sort_values("Code").reset_index(drop=True)


def frame_hash(frame):
    buffer = io.BytesIO()
    frame.to_parquet(buffer, index=False)
    import hashlib
    return hashlib.sha256(buffer.getvalue()).hexdigest()


def _retry_fetch(code, start, as_of):
    for attempt in range(3):
        try:
            return fetch_prices(code, start, as_of)
        except ValueError:
            raise
        except (OSError, TimeoutError, ConnectionError):
            if attempt == 2:
                raise
            time.sleep(2 * (attempt + 1))


def collect(as_of, store, *, replay=False):
    start = (pd.Timestamp(as_of) - pd.Timedelta(days=240)).date().isoformat()
    if replay:
        universe = store.load_universe(as_of)
        if universe.empty:
            raise ValueError("Historical date lacks an archived universe")
        days = refresh_krx_trading_days(start, as_of)
        if pd.Timestamp(as_of).date() not in days:
            return None
    else:
        days = refresh_krx_trading_days(start, as_of)
        if pd.Timestamp(as_of).date() not in days:
            return None
        universe = fetch_universe(as_of)
        store.save_universe(as_of, universe)
    if universe.Code.duplicated().any():
        raise ValueError("Duplicate archived universe")
    frames, unavailable, raw_hashes = {}, {}, {}
    for row in universe.itertuples():
        code = row.Code
        try:
            stored = store.load_prices(code, start, as_of)
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
            frames[code] = (raw, current.iloc[0].to_dict(), current)
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
            raw, row, _ = frames[code]
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


def run(args):
    root = Path(os.environ.get("CHART_SERVING_DATA_DIR", Path(__file__).parent / "data"))
    root.mkdir(parents=True, exist_ok=True)
    as_of = official_day(args.as_of)
    config = yaml.safe_load(Path(__file__).with_name("config.yaml").read_text())["active_pack"]
    pack, paths = load_pack(root / "packs" / config["pack_id"])
    store = SupabaseStore()
    replay = pd.Timestamp(as_of).date() != datetime.now(KST).date()
    collected = collect(as_of, store, replay=replay)
    if collected is None:
        print(json.dumps({"event": "holiday", "as_of": as_of, "pack_id": pack["pack_id"]}))
        return
    batch, snapshots = build_batch(as_of, pack, paths, *collected)
    out = root / "batches" / batch["id"]
    out.mkdir(parents=True, exist_ok=True)
    (out / "batch.json").write_text(json.dumps(batch, ensure_ascii=False, indent=2))
    (out / "snapshots.json").write_text(json.dumps(snapshots, ensure_ascii=False))
    if args.publish:
        from .publish import publish
        publish(batch, snapshots, pack)
    print(json.dumps({"event": "published" if args.publish else "dry_run", "as_of": as_of,
                      "pack_id": pack["pack_id"], "stock_count": len(batch["expected_stock_codes"]),
                      "batch_id": batch["id"], **batch["result"]}))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--as-of", help="Confirmed KRX date YYYY-MM-DD")
    parser.add_argument("--publish", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    if args.publish and args.dry_run:
        parser.error("Choose --publish or --dry-run")
    try:
        run(args)
    except Exception as exc:
        print(json.dumps({"event": "failed", "stage": "daily", "error_type": type(exc).__name__}))
        raise


if __name__ == "__main__":
    main()
