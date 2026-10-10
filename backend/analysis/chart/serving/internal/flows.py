"""Cached daily investor queries, shared with local research collection."""

import json

import pandas as pd
from shared.data.providers import _FLOW_COLUMNS, _fetch_investor_day
from shared.data.validation import validate_flow


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
