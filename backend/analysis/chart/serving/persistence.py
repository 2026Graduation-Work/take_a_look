"""Private Supabase price and feature storage for daily serving."""

import hashlib
import io
import json
import os
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import Request, urlopen

import pandas as pd

PRICE_COLUMNS = {
    "Date": "trade_date", "Open": "open", "High": "high", "Low": "low",
    "Close": "close", "Volume": "volume", "VWAP": "vwap", "Change": "change_percent",
    "RawClose": "raw_close", "RawVolume": "raw_volume", "Amount": "amount",
    "AdjustmentFactor": "adjustment_factor",
}


class SupabaseStore:
    def __init__(self, url=None, key=None):
        self.url = (url or os.environ.get("SUPABASE_URL", "")).rstrip("/")
        self.key = key or os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
        if not self.url or not self.key:
            raise ValueError("SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY are required")

    def _request(self, method, path, body=None, *, content_type="application/json", prefer=None,
                 extra_headers=None):
        headers = {"apikey": self.key, "Authorization": f"Bearer {self.key}"}
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
