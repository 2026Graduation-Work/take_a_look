"""Cached daily investor queries, shared with local research collection."""

import json
from pathlib import Path

import pandas as pd
from core.local_dataset import VALIDATION_VERSION, sha256, validate_flow
from data_collectors.price_collector import _FLOW_COLUMNS, _fetch_investor_day

LOCAL_FLOW_CACHE = Path(__file__).parents[2] / "data" / "datasets" / "local_2016_kospi_v1" / "investor_flow_cache"

def collect_flows(trading_days, store):
    # Only the last 20 sessions are needed for today's 1/5/20-session inputs.
    days = pd.DatetimeIndex(pd.to_datetime(sorted(trading_days)))[-20:]
    parts, failures = [], []
    cached = 0
    for day in days:
        date = day.date().isoformat()
        try:
            frame = store.load_flow_day(date)
            archived = frame is not None
            if frame is None:
                path = LOCAL_FLOW_CACHE / f"{date}.parquet"
                metadata = path.with_suffix(".json")
                if path.is_file() and metadata.is_file():
                    meta = json.loads(metadata.read_text())
                    if meta.get("validation_version") == VALIDATION_VERSION and meta.get("sha256") == sha256(path):
                        frame = validate_flow(pd.read_parquet(path), day, _FLOW_COLUMNS)
            hit = frame is not None
            if not hit:
                frame = _fetch_investor_day(day)
            frame = validate_flow(frame, day, _FLOW_COLUMNS)
            # Local caches also need archiving for ephemeral Actions runners.
            if not archived:
                store.save_flow_day(date, frame)
            cached += int(hit)
            parts.append(frame)
        except Exception as exc:
            failures.append({"date": date, "error_type": type(exc).__name__})
    report = {"requested_days": len(days), "available_days": len(parts),
              "cached_days": cached, "failed_days": failures,
              "scope": "KRX daily final investor totals; missing ranking rows stay null"}
    print(json.dumps({"event": "flow_collection", **report}), flush=True)
    frame = pd.concat(parts, ignore_index=True) if parts else pd.DataFrame(columns=["Date", "Code", *_FLOW_COLUMNS])
    return frame, report
