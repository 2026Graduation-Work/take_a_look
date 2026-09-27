"""Assemble and validate the public chart detail v2 payload."""

from ..contracts import validate_snapshot
from .distribution import POLICY_ID, TOLERANCES


def build_snapshot(*, code, stock_name, as_of, horizon, pack_id, batch_id,
                   inference, distribution, prices, sources):
    if horizon not in (5, 20):
        raise ValueError("Horizon must be 5 or 20")
    return validate_snapshot({
        "contract": "chart_signal_detail_v2",
        "stock_code": code, "stock_name": stock_name,
        "data_asof": as_of, "horizon": horizon,
        "profile": "aggressive" if horizon == 5 else "stable",
        "pack_id": pack_id, "release_id": f"{pack_id}:h{horizon}",
        "batch_id": batch_id, "inference": inference,
        "distribution": distribution, "prices": prices, "sources": sources,
    })


def unavailable_snapshot(*, code, stock_name, as_of, horizon, pack_id, batch_id,
                         reason, model_sha256=None, samples_sha256=None,
                         config_sha256=None):
    return build_snapshot(
        code=code, stock_name=stock_name, as_of=as_of, horizon=horizon,
        pack_id=pack_id, batch_id=batch_id,
        inference={"status": "unavailable", "reason": reason, "scores": None,
                   "score_event": "class_2_upper_barrier_first", "close": None,
                   "sigma": None, "barriers": None,
                   "contribution_space": "class_2_raw_margin", "features": []},
        distribution={"status": "unavailable", "reason": "inference_unavailable",
                      "policy_id": POLICY_ID, "current": None,
                      "tolerances": TOLERANCES, "sample_count": 0, "stock_count": 0,
                      "period_start": None, "period_end": None,
                      "observed_through": None, "by_fold": {},
                      "histogram": {"bins": [], "central_68": None}},
        prices={"basis": "adjusted_close", "source": "unavailable", "history": []},
        sources={"model_sha256": model_sha256, "features_sha256": None,
                 "prices_sha256": None, "cases_sha256": samples_sha256,
                 "config_sha256": config_sha256},
    )
