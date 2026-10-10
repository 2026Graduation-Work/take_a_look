"""Private Supabase price and feature storage for daily serving."""

import hashlib
import io
import json
import os
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import Request, urlopen

import pandas as pd

from ..contracts import validate_snapshot
from .hashing import canonical_hash


def service_headers(key):
    headers = {"apikey": key}
    # The local CLI exposes a legacy service_role JWT. PostgREST needs this
    # bearer token to apply the service role; hosted sb_secret_ keys do not.
    if key.startswith("eyJ") and key.count(".") == 2:
        headers["Authorization"] = f"Bearer {key}"
    return headers


PRICE_COLUMNS = {
    "Date": "trade_date", "Open": "open", "High": "high", "Low": "low",
    "Close": "close", "Volume": "volume", "VWAP": "vwap", "Change": "change_percent",
    "RawClose": "raw_close", "RawVolume": "raw_volume", "Amount": "amount",
    "AdjustmentFactor": "adjustment_factor",
}


class SupabaseStore:
    def __init__(self, url=None, key=None):
        self.url = (url or os.environ.get("SUPABASE_URL", "")).rstrip("/")
        self.key = key or os.environ.get("SUPABASE_SECRET_KEY")
        if not self.url or not self.key:
            raise ValueError("SUPABASE_URL and SUPABASE_SECRET_KEY are required")

    def _request(self, method, path, body=None, *, content_type="application/json", prefer=None,
                 extra_headers=None):
        headers = service_headers(self.key)
        if body is not None:
            headers["Content-Type"] = content_type
        if prefer:
            headers["Prefer"] = prefer
        if extra_headers:
            headers.update(extra_headers)
        if body is not None and not isinstance(body, bytes):
            body = json.dumps(body, allow_nan=False).encode()
        request = Request(self.url + path, data=body, headers=headers, method=method)
        try:
            with urlopen(request, timeout=60) as response:
                data = response.read()
                return json.loads(data) if data and "json" in response.headers.get("Content-Type", "") else data
        except HTTPError as exc:
            if path.startswith("/storage/v1/object/authenticated/"):
                try:
                    error = json.loads(exc.read())
                except (ValueError, OSError):
                    error = {}
                if exc.code == 404 or str(error.get("statusCode")) == "404" or error.get("code") == "NoSuchKey":
                    raise FileNotFoundError("Private storage object absent") from None
            raise RuntimeError(f"Supabase {method} {path.split('?')[0]} failed: HTTP {exc.code}") from None

    def save_universe(self, as_of, rows):
        values = [{"as_of": as_of, "stock_code": str(row["Code"]).zfill(6),
                   "stock_name": str(row["Name"])} for row in rows.to_dict("records")]
        if not values or len({row["stock_code"] for row in values}) != len(values):
            raise ValueError("Empty or duplicate stock universe")
        self._request("DELETE", "/rest/v1/chart_universe?as_of=eq." + quote(as_of))
        self._request("POST", "/rest/v1/chart_universe?on_conflict=as_of,stock_code", values,
                      prefer="resolution=merge-duplicates,return=minimal")

    def load_universe(self, as_of):
        rows = self._request("GET", "/rest/v1/chart_universe?as_of=eq." + quote(as_of) +
                             "&select=stock_code,stock_name&order=stock_code")
        return pd.DataFrame([{"Code": row["stock_code"], "Name": row["stock_name"],
                              "AsOf": as_of} for row in rows])

    def upsert_prices(self, code, frame):
        missing = set(PRICE_COLUMNS) - set(frame)
        if missing:
            raise ValueError(f"Raw prices missing: {sorted(missing)}")
        dates = pd.to_datetime(frame["Date"], errors="raise")
        if dates.isna().any() or dates.duplicated().any():
            raise ValueError("Invalid or duplicate price dates")
        values = []
        for row in frame.to_dict("records"):
            item = {"stock_code": code}
            for source, target in PRICE_COLUMNS.items():
                value = row[source]
                item[target] = pd.Timestamp(value).date().isoformat() if source == "Date" else (
                    None if pd.isna(value) else float(value))
            values.append(item)
        for offset in range(0, len(values), 500):
            self._request("POST", "/rest/v1/chart_prices?on_conflict=stock_code,trade_date",
                          values[offset:offset + 500], prefer="resolution=merge-duplicates,return=minimal")

    def load_prices(self, code, start, end):
        rows = []
        offset = 0
        while True:
            path = ("/rest/v1/chart_prices?stock_code=eq." + quote(code) +
                    "&trade_date=gte." + quote(start) + "&trade_date=lte." + quote(end) +
                    "&select=*&order=trade_date&limit=1000&offset=" + str(offset))
            page = self._request("GET", path)
            rows.extend(page)
            if len(page) < 1000:
                break
            offset += 1000
        frame = pd.DataFrame([{source: row[target] for source, target in PRICE_COLUMNS.items()}
                              for row in rows], columns=PRICE_COLUMNS)
        if not frame.empty:
            frame["Date"] = pd.to_datetime(frame["Date"])
        return frame

    def _load_private_frame(self, key):
        try:
            data = self._request("GET", "/storage/v1/object/authenticated/chart-features/" + quote(key, safe="/"))
        except FileNotFoundError:
            return None
        return pd.read_parquet(io.BytesIO(data))

    def _save_private_frame(self, key, frame):
        data = io.BytesIO()
        frame.to_parquet(data, index=False)
        self._request("POST", "/storage/v1/object/chart-features/" + quote(key, safe="/"),
                      data.getvalue(), content_type="application/octet-stream",
                      extra_headers={"x-upsert": "true"})

    def save_calendar(self, as_of, days):
        self._save_private_frame(f"calendars-v3/{as_of}.parquet",
            pd.DataFrame({"Date": pd.to_datetime(sorted(days))}))

    def load_calendar(self, as_of):
        frame = self._load_private_frame(f"calendars-v3/{as_of}.parquet")
        if frame is None or frame.empty or frame.Date.duplicated().any():
            raise ValueError("Archived operational calendar absent or invalid")
        from shared.data.calendar import scheduled_sessions
        observed = pd.DatetimeIndex(pd.to_datetime(frame.Date)).normalize().sort_values()
        expected = scheduled_sessions(observed.min(), pd.Timestamp(as_of))
        if not observed.equals(expected):
            raise ValueError("Archived operational calendar has missing or unexpected sessions")
        return set(observed.date)

    def load_flow_day(self, day):
        return self._load_private_frame(f"investor-flows-v3/{day}.parquet")

    def save_flow_day(self, day, frame):
        self._save_private_frame(f"investor-flows-v3/{day}.parquet", frame)

    def load_price_history(self, code):
        return self._load_private_frame(f"raw-history-v3/{code}.parquet")

    def save_price_history(self, code, frame):
        self._save_private_frame(f"raw-history-v3/{code}.parquet", frame)

    def load_raw_prices(self, code, as_of):
        return self._load_private_frame(f"raw-prices-v3/{as_of}/{code}.parquet")

    def save_raw_prices(self, code, as_of, frame):
        self._save_private_frame(f"raw-prices-v3/{as_of}/{code}.parquet", frame)

    def upload_features(self, code, as_of, builder_id, input_hash, frame):
        if not code or not builder_id or len(input_hash) != 64:
            raise ValueError("Invalid feature storage identity")
        key = f"{builder_id}/{as_of}/{input_hash}/{code}.parquet"
        data = io.BytesIO()
        frame.to_parquet(data, index=False)
        # Upload first. Metadata is written only after Storage confirms the file.
        self._request("POST", "/storage/v1/object/chart-features/" +
                      quote(key, safe="/"), data.getvalue(),
                      content_type="application/octet-stream", extra_headers={"x-upsert": "true"})
        record = {"stock_code": code, "as_of": as_of, "builder_id": builder_id,
                  "input_sha256": input_hash, "storage_path": key,
                  "feature_sha256": hashlib.sha256(data.getvalue()).hexdigest()}
        self._request("POST", "/rest/v1/chart_feature_snapshots?on_conflict=stock_code,as_of,builder_id,input_sha256",
                      [record], prefer="resolution=merge-duplicates,return=minimal")
        return record

    def load_features(self, code, as_of, builder_id, input_hash):
        path = ("/rest/v1/chart_feature_snapshots?stock_code=eq." + quote(code) +
                "&as_of=eq." + quote(as_of) + "&builder_id=eq." + quote(builder_id) +
                "&input_sha256=eq." + quote(input_hash) +
                "&select=storage_path,feature_sha256")
        rows = self._request("GET", path)
        if not rows:
            return None
        item = rows[0]
        data = self._request("GET", "/storage/v1/object/authenticated/chart-features/" +
                             quote(item["storage_path"], safe="/"))
        if hashlib.sha256(data).hexdigest() != item["feature_sha256"]:
            raise ValueError("Stored feature checksum mismatch")
        return pd.read_parquet(io.BytesIO(data))


    def _existing_batch(self, batch_id):
        rows = self._request("GET", "/rest/v1/chart_batches?id=eq." + quote(batch_id, safe="") +
                        "&select=id,status,result,as_of,release_h5,release_h20")
        return rows[0] if rows else None


    def publish(self, batch, snapshots, releases):
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
        existing = self._existing_batch(batch["id"])
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
            found = self._request("GET", "/rest/v1/chart_releases?id=eq." + quote(row["id"], safe="") +
                             "&select=id,model_sha256,features_sha256,cases_sha256,config_sha256")
            if found:
                if any(found[0][key] != row[key] for key in
                       ("model_sha256", "features_sha256", "cases_sha256", "config_sha256")):
                    raise ValueError("Existing release ID has different artifact hashes")
            else:
                self._request("POST", "/rest/v1/chart_releases", [row], prefer="return=minimal")
        self._request("POST", "/rest/v1/chart_batches?on_conflict=id", [dict(batch, result=result)],
                 prefer="resolution=merge-duplicates,return=minimal")
        rows = [{"batch_id": batch["id"], "stock_code": s["stock_code"],
                 "horizon": s["horizon"], "payload": s,
                 "payload_sha256": canonical_hash(s)} for s in snapshots]
        # Staging is invisible to anon/authenticated users until the RPC commits.
        try:
            for offset in range(0, len(rows), 100):
                self._request("POST", "/rest/v1/chart_signal_snapshots?on_conflict=batch_id,stock_code,horizon",
                         rows[offset:offset + 100], prefer="resolution=merge-duplicates,return=minimal")
        except Exception as exc:
            try:
                self._request("PATCH", "/rest/v1/chart_batches?id=eq." + quote(batch["id"], safe=""),
                         {"status": "failed", "result": dict(result, failed_stage="snapshot_upload",
                                                           failure_type=type(exc).__name__)})
            except Exception:
                pass  # Original upload error remains the actionable failure.
            raise
        self._request("POST", "/rest/v1/rpc/publish_chart_batch", {"p_batch_id": batch["id"]})


    def withdraw(self, batch_id):
        self._request("POST", "/rest/v1/rpc/withdraw_chart_batch", {"p_batch_id": batch_id})


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
