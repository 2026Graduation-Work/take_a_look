"""Legacy serving adapters. Learning collection uses training_prices."""
import json
import time
from pathlib import Path

import numpy as np
import pandas as pd

from shared.io import atomic_json, atomic_parquet, sha256

from . import providers
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
        end = min(current + pd.DateOffset(years=2) - pd.Timedelta(1, unit="D"), days[-1])
        path = root / "raw_ohlc_cache" / f"{code}_{current:%Y%m%d}_{end:%Y%m%d}.parquet"
        sidecar = path.with_suffix(".json")
        if path.exists() and sidecar.exists():
            meta = json.loads(sidecar.read_text())
            if meta.get("sha256") == sha256(path):
                parts.append(pd.read_parquet(path).set_index("Date"))
        current = end + pd.Timedelta(1, unit="D")
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
    adapters = ([("pykrx", getattr(source, "_fetch_delisted_pykrx", _fetch_delisted_pykrx))] if is_delisted else
                [("fdr", _fetch_ohlcv_fdr), ("pykrx", _fetch_ohlcv_pykrx)])
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


def _fetch_ohlcv_pykrx(code: str, start_date: str, end_date: str, *, raw_df=None) -> pd.DataFrame:
    """
    pykrx로 수정주가(adjusted=True) 기준 일봉 OHLCV를 가져옵니다.
    등락률(Change)은 % 단위를 유지합니다.
    """
    start_yyyymmdd = start_date.replace("-", "")
    end_yyyymmdd = end_date.replace("-", "")

    adjusted_df = providers.krx.get_market_ohlcv_by_date(
        start_yyyymmdd,
        end_yyyymmdd,
        code,
        adjusted=True,
    )
    if raw_df is None:
        raw_df = providers.krx.get_market_ohlcv_by_date(
            start_yyyymmdd, end_yyyymmdd, code, adjusted=False,
        )
    if adjusted_df.empty or raw_df.empty:
        return pd.DataFrame()

    adjusted_df = adjusted_df.rename(
        columns={
            "시가": "Open",
            "고가": "High",
            "저가": "Low",
            "종가": "Close",
            "거래량": "Volume",
            "등락률": "Change",
        }
    )
    required_adjusted_columns = ["Open", "High", "Low", "Close", "Volume", "Change"]
    missing_columns = set(required_adjusted_columns) - set(adjusted_df.columns)
    if missing_columns:
        raise ValueError(f"수정주가 필수 컬럼 누락: {sorted(missing_columns)}")
    adjusted_df = adjusted_df[required_adjusted_columns].copy()
    adjusted_df.index.name = "Date"
    # 등락률의 NaN 값 보정 -> 이거 첫날 상장때는 등락률 계산이 불가능해서 0으로 처리
    if "Change" in adjusted_df.columns:
        adjusted_df["Change"] = adjusted_df["Change"].fillna(0.0)
    return providers._attach_actual_vwap(adjusted_df, raw_df)



def _fetch_ohlcv_fdr(code: str, start_date: str, end_date: str, *, raw_df=None) -> pd.DataFrame:
    """
    FinanceDataReader로 수정주가 기준 일봉 OHLCV를 가져옵니다.
    FDR의 Change(소수점 단위)를 퍼센트(%) 단위로 변환하여 pykrx와 스케일을 통일합니다.
    """
    import FinanceDataReader as fdr

    t = time.time()
    try:
        adjusted_df = fdr.DataReader(code, start_date, end_date)
        print(code, "FDR:", time.time() - t)
        t = time.time()
        if raw_df is None:
            raw_df = providers.krx.get_market_ohlcv_by_date(
                start_date.replace("-", ""), end_date.replace("-", ""), code, adjusted=False,
            )
            print(code, "KRX raw:", time.time() - t)
        if adjusted_df.empty or raw_df.empty:
            return pd.DataFrame()

        # 필요한 컬럼만 추출 및 리네임
        adjusted_df = adjusted_df[
            ["Open", "High", "Low", "Close", "Volume", "Change"]
        ].copy()
        # 등락률 단위를 %로 변환 (FDR은 0.0132 형태, pykrx는 1.32 형태)
        adjusted_df["Change"] = adjusted_df["Change"].fillna(0.0) * 100.0
        adjusted_df.index.name = "Date"
        return providers._attach_actual_vwap(adjusted_df, raw_df)
    except Exception:
        # print(f"  [FDR Fetch Error] {code}: {e}")
        return pd.DataFrame()



def _fetch_delisted_pykrx(code: str, start_date: str, end_date: str, *, raw_df=None) -> pd.DataFrame:
    """상폐 종목의 KRX 원가격·거래대금과 수정가격을 날짜별로 결합합니다."""
    start, end = start_date.replace("-", ""), end_date.replace("-", "")
    raw = raw_df if raw_df is not None else providers.krx.get_market_ohlcv_by_date(start, end, code, adjusted=False)
    if raw.empty:
        raise ValueError(f"{code}: 상폐 종목 KRX 원가격/거래대금을 확인할 수 없습니다")
    adjusted = providers.krx.get_market_ohlcv_by_date(
        start, end, code, adjusted=True
    )
    if adjusted.empty:
        raise ValueError(f"{code}: 상폐 종목 수정주가를 확인할 수 없습니다")
    adjusted = adjusted.rename(columns={
        "시가": "Open", "고가": "High", "저가": "Low", "종가": "Close",
        "거래량": "Volume", "등락률": "Change",
    })
    columns = ["Open", "High", "Low", "Close", "Volume", "Change"]
    if missing := set(columns) - set(adjusted.columns):
        raise ValueError(f"{code}: 상폐 수정주가 필수 컬럼 누락: {sorted(missing)}")
    adjusted = adjusted[columns].copy()
    adjusted["Change"] = adjusted["Change"].fillna(0.0)
    adjusted.index.name = "Date"
    return providers._attach_actual_vwap(adjusted, raw)
