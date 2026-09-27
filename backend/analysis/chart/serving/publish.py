"""Service-role-only Supabase REST publisher; RPC controls public visibility."""

import json
import os
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import Request, urlopen

from serving.contracts import validate_snapshot
from serving.hashing import canonical_hash


def _pack_releases(manifest):
    if not isinstance(manifest, dict) or not manifest.get("pack_id"):
        raise ValueError("Pack manifest requires pack_id")
    horizons = manifest.get("horizons", {})
    if set(horizons) != {"h5", "h20"}:
        raise ValueError("Pack must contain H5 and H20")
    releases = []
    for key, horizon in (("h5", 5), ("h20", 20)):
        item = horizons[key]
        if item["horizon"] != horizon:
            raise ValueError("Pack horizon mismatch")
        releases.append({"release_id": f"{manifest['pack_id']}:{key}",
                         "horizon": horizon, "profile": item["profile"],
                         "policy_id": "multi_stock_up_sigma_001_005_v1",
                         "model_sha256": item["model_sha256"],
                         "features_sha256": canonical_hash({
                             "builder": manifest["feature_builder_id"],
                             "names": item["feature_names"]}),
                         "cases_sha256": item["samples_sha256"],
                         "config_sha256": canonical_hash(manifest),
                         "pack_id": manifest["pack_id"]})
    return releases


def _request(method, path, body=None, *, prefer=None):
    base = os.environ.get("SUPABASE_URL", "").rstrip("/")
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
    if not base or not key:
        raise ValueError("SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY are required")
    headers = {"apikey": key, "Authorization": f"Bearer {key}",
               "Content-Type": "application/json"}
    if prefer:
        headers["Prefer"] = prefer
    request = Request(base + "/rest/v1/" + path,
                      data=None if body is None else json.dumps(body, allow_nan=False).encode(),
                      headers=headers, method=method)
    try:
        with urlopen(request, timeout=60) as response:
            data = response.read()
            return json.loads(data) if data else None
    except HTTPError as exc:
        # Never print request headers: they carry the service key.
        raise RuntimeError(f"Supabase {method} {path.split('?')[0]} failed: HTTP {exc.code}") from None


def _existing_batch(batch_id):
    rows = _request("GET", "chart_batches?id=eq." + quote(batch_id, safe="") +
                    "&select=id,status,result,as_of,release_h5,release_h20")
    return rows[0] if rows else None


def publish(batch, snapshots, releases):
    if isinstance(releases, dict):
        releases = _pack_releases(releases)
    if len(releases) != 2 or {r["horizon"] for r in releases} != {5, 20}:
        raise ValueError("Exactly H5/H20 releases required")
    if len(snapshots) != 2 * len(batch["expected_stock_codes"]):
        raise ValueError("Incomplete local snapshot set")
    expected = {(code, h) for code in batch["expected_stock_codes"] for h in (5, 20)}
    if {(s["stock_code"], s["horizon"]) for s in snapshots} != expected:
        raise ValueError("Snapshot keys differ from expected universe")
    for snapshot in snapshots:
        validate_snapshot(snapshot)
        if snapshot["batch_id"] != batch["id"] or snapshot["data_asof"] != batch["as_of"]:
            raise ValueError("Snapshot batch/date mismatch")
        if snapshot["release_id"] != next(r["release_id"] for r in releases
                                          if r["horizon"] == snapshot["horizon"]):
            raise ValueError("Snapshot release mismatch")
        if batch.get("pack_id") and snapshot.get("pack_id") != batch["pack_id"]:
            raise ValueError("Snapshot pack mismatch")
    if batch["release_h5"] != next(r["release_id"] for r in releases if r["horizon"] == 5) or (
            batch["release_h20"] != next(r["release_id"] for r in releases if r["horizon"] == 20)):
        raise ValueError("Batch release mismatch")
    payload_hash = canonical_hash(snapshots)
    result = dict(batch["result"], payload_sha256=payload_hash)
    existing = _existing_batch(batch["id"])
    if existing and existing["status"] == "published":
        if existing["result"].get("payload_sha256") != payload_hash:
            raise ValueError("Published batch ID has different payload")
        return
    if existing and existing["status"] == "withdrawn":
        raise ValueError("Withdrawn batch cannot be republished")
    if existing and (existing["as_of"] != batch["as_of"] or
                     existing["release_h5"] != batch["release_h5"] or
                     existing["release_h20"] != batch["release_h20"] or
                     (existing["result"].get("payload_sha256") not in (None, payload_hash))):
        raise ValueError("Existing batch ID refers to different inputs")
    release_rows = [{"id": r["release_id"], "horizon": r["horizon"],
                     "profile": r["profile"], "policy_id": r["policy_id"],
                     "model_sha256": r["model_sha256"],
                     "features_sha256": r["features_sha256"],
                     "cases_sha256": r["cases_sha256"],
                     "config_sha256": r["config_sha256"], "manifest": r}
                    for r in releases]
    for row in release_rows:
        found = _request("GET", "chart_releases?id=eq." + quote(row["id"], safe="") +
                         "&select=id,model_sha256,features_sha256,cases_sha256,config_sha256")
        if found:
            if any(found[0][key] != row[key] for key in
                   ("model_sha256", "features_sha256", "cases_sha256", "config_sha256")):
                raise ValueError("Existing release ID has different artifact hashes")
        else:
            _request("POST", "chart_releases", [row], prefer="return=minimal")
    _request("POST", "chart_batches?on_conflict=id", [dict(batch, result=result)],
             prefer="resolution=merge-duplicates,return=minimal")
    rows = [{"batch_id": batch["id"], "stock_code": s["stock_code"],
             "horizon": s["horizon"], "payload": s,
             "payload_sha256": canonical_hash(s)} for s in snapshots]
    # Staging is invisible to anon/authenticated users until the RPC commits.
    try:
        for offset in range(0, len(rows), 100):
            _request("POST", "chart_signal_snapshots?on_conflict=batch_id,stock_code,horizon",
                     rows[offset:offset + 100], prefer="resolution=merge-duplicates,return=minimal")
    except Exception as exc:
        try:
            _request("PATCH", "chart_batches?id=eq." + quote(batch["id"], safe=""),
                     {"status": "failed", "result": dict(result, failed_stage="snapshot_upload",
                                                       failure_type=type(exc).__name__)})
        except Exception:
            pass  # Original upload error remains the actionable failure.
        raise
    _request("POST", "rpc/publish_chart_batch", {"p_batch_id": batch["id"]})


def withdraw(batch_id):
    _request("POST", "rpc/withdraw_chart_batch", {"p_batch_id": batch_id})
