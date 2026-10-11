"""Verify active flow models using fresh confirmed inputs without database access."""

import json
from types import SimpleNamespace

from shared.features.columns import BASE_FEATURES, FLOW_FEATURES

from .internal.pipeline import (
    active_pack,
    build_batch,
    collect,
    data_root,
    official_day,
    refresh_krx_trading_days,
    write_batch,
)


def main():
    pack, paths = active_pack()
    expected = list(BASE_FEATURES) + list(FLOW_FEATURES)
    for horizon in (5, 20):
        if pack["horizons"][f"h{horizon}"]["feature_names"] != expected:
            raise ValueError(f"H{horizon} is not the expected flow model")
    days = refresh_krx_trading_days("2016-01-01", official_day())
    if not days:
        raise ValueError("No confirmed trading sessions")
    as_of = max(days).isoformat()
    # The collector can only read providers and write its local cache here.
    store = SimpleNamespace(
        load_flow_day=lambda _: None,
        save_flow_day=lambda *_: None,
        upsert_prices=lambda *_: None,
        upload_feature_panel=lambda *_: None,
    )
    collected = collect(as_of, store, code="005930", historical_test=True)
    if collected is None:
        raise ValueError("Confirmed session missing from collector calendar")
    batch, snapshots = build_batch(as_of, pack, paths, *collected)
    write_batch(data_root(), batch, snapshots)
    if len(snapshots) != 2 or {s["horizon"] for s in snapshots} != {5, 20}:
        raise ValueError("H5/H20 validation snapshots missing")
    failures = [f'H{s["horizon"]}: {s["inference"].get("reason")}'
                for s in snapshots if s["inference"]["status"] != "available"]
    if failures:
        raise ValueError("Active model check failed: " + "; ".join(failures))
    print(json.dumps({"event": "active_models_verified", "as_of": as_of,
                      "pack_id": pack["pack_id"], "features_per_model": len(expected),
                      "flow_features": len(FLOW_FEATURES), "batch_id": batch["id"],
                      "horizons": sorted(s["horizon"] for s in snapshots),
                      "published": False}), flush=True)


if __name__ == "__main__":
    main()
