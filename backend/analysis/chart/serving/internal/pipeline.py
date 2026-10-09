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
import numpy as np
import pandas as pd
import yaml

from .calendar import refresh_krx_trading_days
from .distribution import SampleIndex
from .features import BUILDER_ID, build_feature_frame
from .flows import collect_flows
from .hashing import canonical_hash
from .inference import infer_batch
from .pack import load_pack
from .prices import fetch_prices, price_snapshot
from .progress import report, stage
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
        if not re.fullmatch(r"[0-9A-Z]{6}", code):
            raise ValueError("Stock code must be six uppercase alphanumeric characters")
        codes = [code]
    else:
        codes = stock.get_market_ticker_list(as_of.replace("-", ""), market="KOSPI")
        if not 500 <= len(codes) <= 1200:
            raise ValueError("Invalid KOSPI universe size")
    rows = pd.DataFrame({"Code": codes, "Name": [stock.get_market_ticker_name(item) for item in codes]})
    if (rows.Code.duplicated().any() or not rows.Code.str.fullmatch(r"[0-9A-Z]{6}").all()
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
        except ValueError:
            raise
        except (OSError, TimeoutError, ConnectionError):
            if attempt == 2:
                raise
            time.sleep(2 * (attempt + 1))


def collect(as_of, store, *, replay=False, code=None, historical_test=False):
    start = "2016-01-01"
    recent_start = (pd.Timestamp(as_of) - pd.Timedelta(days=240)).date().isoformat()
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
        universe = fetch_universe(as_of, code=code)
        if not historical_test:
            store.save_universe(as_of, universe)
    if universe.Code.duplicated().any():
        raise ValueError("Duplicate archived universe")
    flow, flow_report = (pd.DataFrame(), {"mode": "archived_inputs"}) if replay else collect_flows(days, store)
    frames, unavailable, raw_hashes = {}, {}, {}
    for index, row in enumerate(universe.itertuples(), 1):
        code = row.Code
        report("stock_start", stock_code=code, index=index, total=len(universe))
        try:
            if replay:
                archived = store.load_raw_prices(code, as_of)
                if archived is None:
                    raise ValueError(f"Corrected raw input archive absent for {code}/{as_of}")
                stored = archived
                if stored.empty or stored.Date.max().date().isoformat() != as_of:
                    raise ValueError(f"Historical inputs absent for {code}/{as_of}")
                raw = stored
            else:
                previous = None if historical_test else store.load_price_history(code)
                request_start = start if previous is None else recent_start
                fresh = _retry_fetch(code, request_start, as_of)
                if previous is not None:
                    previous = previous.loc[pd.to_datetime(previous.Date).le(pd.Timestamp(as_of))]
                    overlap = previous[["Date", "Close", "RawClose", "RawVolume", "Amount"]].merge(
                        fresh[["Date", "Close", "RawClose", "RawVolume", "Amount"]], on="Date", suffixes=("_old", "_new"))
                    revised = overlap.empty or any(
                        not np.allclose(overlap[f"{col}_old"], overlap[f"{col}_new"],
                                                      rtol=1e-10, atol=1e-10, equal_nan=True)
                        for col in ("Close", "RawClose", "RawVolume", "Amount"))
                    if revised:
                        fresh = _retry_fetch(code, start, as_of)
                    else:
                        fresh = pd.concat([previous, fresh], ignore_index=True).drop_duplicates("Date", keep="last")
                if fresh.Date.max().date().isoformat() != as_of:
                    unavailable[code] = "price_not_confirmed_for_session"
                    continue
                # Requery the entire feature window: adjusted past prices can change.
                store.upsert_prices(code, fresh.loc[pd.to_datetime(fresh.Date).ge(pd.Timestamp(recent_start))])
                raw = fresh
                raw["Code"] = code
                raw = raw.drop(columns=[c for c in raw if c.startswith(("Individual_", "Institution_", "Foreign_"))], errors="ignore")
                if not flow.empty:
                    raw = raw.merge(flow.loc[flow.Code.eq(code)].drop(columns="Code"),
                                    on="Date", how="left", validate="one_to_one")
                if not historical_test:
                    store.save_price_history(code, raw)

            raw = raw.sort_values("Date").reset_index(drop=True)
            if raw.empty or raw.Date.max().date().isoformat() != as_of:
                unavailable[code] = "price_not_confirmed_for_session"
                continue
            digest = raw.attrs.get("input_sha256") if replay else None
            if digest:
                current = store.load_features(code, as_of, BUILDER_ID, digest)
                if current is None:
                    raise ValueError(f"Archived corrected feature input absent for {code}/{as_of}")
            else:
                features = build_feature_frame(raw, days)
                current = features.loc[pd.to_datetime(features.Date).eq(pd.Timestamp(as_of))]
            if len(current) != 1 or not pd.notna(current.iloc[0].Sigma):
                unavailable[code] = "feature_row_missing"
                continue
            digest = digest or frame_hash(raw)
            if not replay and not historical_test:
                archive = raw.tail(60).copy()
                archive.attrs["input_sha256"] = digest
                store.save_raw_prices(code, as_of, archive)
            store.upload_features(code, as_of, BUILDER_ID, digest, current)
            frames[code] = (raw, current.iloc[0].to_dict(), current)
            raw_hashes[code] = digest
        except ValueError as exc:
            if replay:
                raise
            if "KRX prices unavailable" not in str(exc):
                raise
            unavailable[code] = "price_source_unavailable"
        finally:
            report("stock_complete", stock_code=code, index=index, total=len(universe),
                   status="available" if code in frames else unavailable.get(code, "failed"))
    if not frames:
        raise ValueError("No confirmed stock inputs; previous batch retained")
    flow_report["complete_current_rows"] = sum(
        all(pd.notna(row.get(f"flow_{investor}_{window}"))
            for investor in ("individual", "institution", "foreign") for window in (1, 5, 20))
        for _, row, _ in frames.values())
    return universe, frames, unavailable, raw_hashes, flow_report


def build_batch(as_of, pack, paths, universe, frames, unavailable, raw_hashes, flow_report=None):
    names = dict(zip(universe.Code, universe.Name))
    codes = sorted(names)
    batch_id = canonical_hash({"as_of": as_of, "pack_id": pack["pack_id"],
                               "output_policy": "winning_class_contribution_hist2_v2",
                               "builder": pack["feature_builder_id"], "names": names,
                               "raw_hashes": raw_hashes, "unavailable": unavailable})
    snapshots = []
    for horizon in (5, 20):
        item = pack["horizons"][f"h{horizon}"]
        model_path, samples_path = paths[horizon]
        model = lgb.Booster(model_file=str(model_path))
        flow_names = [name for name in model.feature_name() if name.startswith("flow_")]
        incomplete = {code for code, (_, row, _) in frames.items()
                      if any(pd.isna(row.get(name)) for name in flow_names)}
        selected = [code for code in frames if code not in incomplete]
        current = pd.DataFrame([frames[code][1] for code in selected])
        predictions = infer_batch(model, current) if selected else []
        by_code = dict(zip(selected, predictions))
        history = SampleIndex(pd.read_parquet(samples_path))
        for code in codes:
            if code in unavailable or code in incomplete:
                snapshots.append(unavailable_snapshot(
                    code=code, stock_name=names[code], as_of=as_of, horizon=horizon,
                    pack_id=pack["pack_id"], batch_id=batch_id,
                    reason=unavailable.get(code, "flow_window_incomplete"), model_sha256=item["model_sha256"],
                    samples_sha256=item["samples_sha256"], config_sha256=canonical_hash(pack)))
                continue
            raw, row, _ = frames[code]
            scores, contributions, features_hash, contribution_total = by_code[code]
            target = max(range(3), key=lambda i: scores[("down", "neutral", "up")[i]])
            sigma, close = float(row["Sigma"]), float(row["Close"])
            up, down = (item["label_barriers"][key] for key in ("up_mult", "down_mult"))
            inference = {"status": "available", "reason": None, "scores": scores,
                         "score_event": "class_2_upper_barrier_first", "close": close,
                         "sigma": sigma, "barriers": {"up": close * (1 + up * sigma),
                                                       "down": close * (1 - down * sigma)},
                         "contribution_space": f"class_{target}_raw_margin", "features": contributions,
                         "contribution_abs_sum": contribution_total}
            price = price_snapshot(raw, code, as_of, "KRX 비수정 OHLC·거래대금, 동일 수정계수 적용")
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
             "result": {"snapshot_count": len(snapshots), "unavailable_count": sum(s["inference"]["status"] == "unavailable" for s in snapshots),
                        "flows": flow_report or {}}}
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
    root = Path(os.environ.get("CHART_SERVING_DATA_DIR", Path(__file__).parents[1] / "data"))
    root.mkdir(parents=True, exist_ok=True)
    as_of = official_day(args.as_of)
    historical_test = getattr(args, "historical_test", False)
    if historical_test:
        require_local_url(os.environ.get("SUPABASE_URL", ""))
        if not args.dry_run or args.publish:
            raise ValueError("--historical-test is dry-run only")
        if as_of == datetime.now(KST).date().isoformat():
            raise ValueError("--historical-test requires a past date")
    pack, paths = active_pack(root)
    if pack["feature_builder_id"] != BUILDER_ID:
        raise ValueError("Daily inference requires a pack matching the corrected feature builder")
    store = SupabaseStore()
    replay = getattr(args, "replay", False)
    from .krx import install_request_timeout
    install_request_timeout()
    collected = collect(as_of, store, replay=replay, code=args.code if historical_test else None,
                        historical_test=historical_test)
    if collected is None:
        print(json.dumps({"event": "holiday", "as_of": as_of, "pack_id": pack["pack_id"]}))
        return
    batch, snapshots = build_batch(as_of, pack, paths, *collected)
    if historical_test:
        batch["result"]["historical_test"] = True
    out = root / "batches" / batch["id"]
    out.mkdir(parents=True, exist_ok=True)
    (out / "batch.json").write_text(json.dumps(batch, ensure_ascii=False, indent=2))
    (out / "snapshots.json").write_text(json.dumps(snapshots, ensure_ascii=False))
    batch["result"]["validation_status"] = pack.get("validation_status", "unverified")
    if args.publish:
        with stage("publish_batch", batch_id=batch["id"], snapshots=len(snapshots)):
            store.publish(batch, snapshots, pack)
        try:
            from .krx import authenticated_stock
            from .market import market_status_row
            store.upsert_market_status(market_status_row(authenticated_stock(), as_of))
            report("market_status", as_of=as_of, status="ok")
        except Exception as exc:
            report("market_status", as_of=as_of, status="failed", error_type=type(exc).__name__)
    print(json.dumps({"event": "published" if args.publish else ("historical_test" if historical_test else "dry_run"), "as_of": as_of,
                      "pack_id": pack["pack_id"], "stock_count": len(batch["expected_stock_codes"]),
                      "batch_id": batch["id"], **batch["result"]}))


def require_local_url(url):
    parsed = urlparse(url)
    if parsed.scheme != "http" or parsed.hostname not in {"localhost", "127.0.0.1", "::1"}:
        raise ValueError("local_preview requires a loopback HTTP Supabase URL")


def load_cached_input(data_root, code, requested_date=None):
    if not re.fullmatch(r"[0-9A-Z]{6}", code):
        raise ValueError("Stock code must have six uppercase alphanumeric characters")
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
    if not re.fullmatch(r"[0-9A-Z]{6}", args.code):
        raise ValueError("Invalid stock code")
    if not args.compute_only:
        require_local_url(os.environ.get("SUPABASE_URL", ""))
    root = Path(os.environ.get("CHART_SERVING_DATA_DIR", Path(__file__).parents[1] / "data"))
    config = yaml.safe_load((Path(__file__).parents[1] / "config.yaml").read_text())["active_pack"]
    pack_dir = root / "packs" / config["pack_id"]
    pack, paths = load_pack(pack_dir)
    if pack["feature_builder_id"] == BUILDER_ID:
        dataset = Path(getattr(args, "dataset_root", None) or Path(__file__).parents[2] / "data/datasets/local_2016_kospi_v1")
        raw = pd.read_parquet(dataset / "raw" / f"{args.code}.parquet")
        if "PriceBasis" not in raw or not raw.PriceBasis.eq("krx_raw_ohlc_uniform_close_ratio_v1").all():
            raise ValueError("Corrected pack requires verified corrected raw prices")
        raw["Date"] = pd.to_datetime(raw.Date)
        as_of = pd.Timestamp(args.as_of or raw.Date.max())
        raw = raw.loc[raw.Date.le(as_of)].sort_values("Date").reset_index(drop=True)
        if raw.empty or raw.Date.max() != as_of:
            raise ValueError("Requested date is absent from corrected inputs")
        name = str(raw.iloc[-1].Name)
        calendar = json.loads((pack_dir / "calendar.json").read_text())
        current = build_feature_frame(raw, set(pd.to_datetime(calendar["trading_days"]).date))
        current = current.loc[current.Date.eq(as_of)]
        if len(current) != 1 or not pd.notna(current.iloc[0].Sigma):
            raise ValueError("No complete corrected feature row")
        as_of = as_of.date().isoformat()
    else:
        as_of, name, raw, current = load_cached_input(root, args.code, args.as_of)
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
        SupabaseStore().publish(batch, snapshots, pack)
    event = "local_preview_published" if args.publish else (
        "local_preview_computed" if args.compute_only else "local_preview_staged")
    print(json.dumps({"event": event,
                      "as_of": as_of, "stock_code": args.code, "batch_id": batch["id"],
                      "sample_counts": {str(item["horizon"]): item["distribution"]["sample_count"]
                                        for item in snapshots}}))
