"""Uniform KRX raw OHLC adjustment and a single v3 provider fallback path."""
import json
import time
from pathlib import Path

import numpy as np
import pandas as pd

from shared.io import atomic_json, atomic_parquet, sha256

from .validation import validate_prices


def supplement_raw_ohlc(root, code, days, raw, source):
    """Preserve daily snapshots; cache missing KRX OHLC histories separately."""
    fields = ["RawOpen", "RawHigh", "RawLow", "RawClose", "RawVolume", "Amount"]
    if raw is not None and set(fields) <= set(raw):
        return raw
    started = time.monotonic()
    parts = []
    current = days[0]
    # Reuse complete legacy chunks before requesting a full history.
    while current <= days[-1]:
        end = min(current + pd.DateOffset(years=2) - pd.Timedelta(days=1), days[-1])
        path = root / "raw_ohlc_cache" / f"{code}_{current:%Y%m%d}_{end:%Y%m%d}.parquet"
        sidecar = path.with_suffix(".json")
        if path.exists() and sidecar.exists():
            meta = json.loads(sidecar.read_text())
            if meta.get("sha256") == sha256(path):
                parts.append(pd.read_parquet(path).set_index("Date"))
        current = end + pd.Timedelta(days=1)
    cached = pd.concat(parts).sort_index() if parts else pd.DataFrame(columns=fields)
    path = root / "raw_ohlc_cache" / f"{code}_{days[0]:%Y%m%d}_{days[-1]:%Y%m%d}.parquet"
    sidecar = path.with_suffix(".json")
    if path.exists() and sidecar.exists():
        meta = json.loads(sidecar.read_text())
        if meta.get("sha256") == sha256(path):
            cached = pd.read_parquet(path).set_index("Date")
    if not cached.empty and not cached.index.has_duplicates and days.difference(cached.index).empty:
        history = cached.reindex(days)
        provider = "cache"
    else:
        with source._krx_request_timeout():
            history = source.krx.get_market_ohlcv_by_date(
                days[0].strftime("%Y%m%d"), days[-1].strftime("%Y%m%d"), code, adjusted=False
            )
        history = history.rename(columns={
            "시가": "RawOpen", "고가": "RawHigh", "저가": "RawLow",
            "종가": "RawClose", "거래량": "RawVolume", "거래대금": "Amount",
        })
        if history.empty or set(fields) - set(history):
            raise ValueError("Missing KRX raw OHLC history")
        history = history[fields].apply(pd.to_numeric, errors="raise")
        history.index = pd.to_datetime(history.index).normalize()
        if history.index.has_duplicates or len(days.difference(history.index)):
            raise ValueError("Incomplete KRX raw OHLC history dates")
        history = history.reindex(days)
        overlap = cached.index.intersection(days)
        if len(overlap) and not np.allclose(history.loc[overlap, fields], cached.loc[overlap, fields],
                                           rtol=1e-10, atol=1e-12, equal_nan=True):
            raise ValueError("KRX full history disagrees with preserved OHLC chunks")
        provider = "full history"
    if raw is not None:
        for column in set(fields) & set(raw):
            if not np.allclose(history[column], raw[column], rtol=1e-10, atol=1e-12, equal_nan=True):
                raise ValueError(f"KRX OHLC supplement disagrees with preserved {column}")
    if provider != "cache":
        atomic_parquet(path, history.rename_axis("Date").reset_index())
        atomic_json(sidecar, {"sha256": sha256(path), "source": "pykrx KRX adjusted=False"})
    print(f"{code} KRX OHLC: {time.monotonic() - started:.2f}s ({provider}, {len(history)} rows)", flush=True)
    if raw is None:
        return history
    return raw.join(history[[column for column in fields if column not in raw]])



def fetch_price_window(code, days, *, root, raw=None, is_delisted=False, source=None, progress=None):
    from . import providers
    source = source or providers
    days = pd.DatetimeIndex(pd.to_datetime(days)).normalize().unique().sort_values()
    if days.empty:
        raise ValueError("No verified sessions for price request")
    root = Path(root)
    raw = supplement_raw_ohlc(root, code, days, raw, source)
    adapters = ([("pykrx", source._fetch_delisted_pykrx)] if is_delisted else
                [("fdr", source._fetch_ohlcv_fdr), ("pykrx", source._fetch_ohlcv_pykrx)])
    failures = []
    for provider, adapter in adapters:
        for attempt in range(1, 4):
            try:
                with source._krx_request_timeout():
                    candidate = adapter(code, str(days[0].date()), str(days[-1].date()), raw_df=raw)
                if candidate is None or candidate.empty:
                    raise ValueError("Empty provider response")
                candidate = candidate.rename_axis("Date").reset_index()
                candidate = candidate.loc[pd.to_datetime(candidate.Date).isin(days)]
                return validate_prices(candidate, days).assign(PriceProvider=provider)
            except Exception as exc:
                event = {"state": "request_failed", "stage": "prices", "code": code,
                         "provider": provider, "attempt": attempt,
                         "exception_type": type(exc).__name__, "reason": str(exc),
                         **getattr(exc, "details", {})}
                if progress:
                    progress(event)
                failures.append(f"{provider}: {exc}")
                if attempt < 3:
                    source.time.sleep(attempt)
    raise ValueError("Price providers exhausted: " + "; ".join(failures))
