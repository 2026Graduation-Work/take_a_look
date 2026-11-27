import time
from contextlib import contextmanager
from pathlib import Path

import numpy as np
import pandas as pd
from dotenv import load_dotenv

# pykrx는 import 시점에 로그인 세션을 만들므로 .env를 먼저 읽어야 합니다.
load_dotenv(Path(__file__).resolve().parents[2] / ".env")

class _KrxProvider:
    def __getattr__(self, name):
        import contextlib
        import io

        from .krx import install_request_timeout
        install_request_timeout()
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            from pykrx import stock
        return getattr(stock, name)


krx = _KrxProvider()


def get_krx_session():
    import contextlib
    import io

    from .krx import install_request_timeout
    install_request_timeout()
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        from pykrx.website.comm.webio import get_session
        return get_session()


_INVESTORS = {"Individual": "개인", "Institution": "기관합계", "Foreign": "외국인"}
_FLOW_SOURCE = {
    "매수거래량": "BuyVolume", "매도거래량": "SellVolume",
    "매수거래대금": "BuyAmount", "매도거래대금": "SellAmount",
}
_FLOW_COLUMNS = [f"{prefix}_{suffix}" for prefix in _INVESTORS for suffix in _FLOW_SOURCE.values()]


def _attach_actual_vwap(adjusted_df: pd.DataFrame, raw_df: pd.DataFrame) -> pd.DataFrame:
    """KRX 거래대금 기반 일별 VWAP을 수정주가 스케일로 변환합니다."""
    if adjusted_df.empty or raw_df.empty:
        return pd.DataFrame()

    adjusted = adjusted_df.copy()
    raw = raw_df.rename(
        columns={
            "시가": "RawOpen", "고가": "RawHigh", "저가": "RawLow",
            "종가": "RawClose",
            "거래량": "RawVolume",
            "거래대금": "Amount",
        }
    ).copy()
    required_raw_columns = {"RawOpen", "RawHigh", "RawLow", "RawClose", "RawVolume", "Amount"}
    missing_columns = required_raw_columns - set(raw.columns)
    if missing_columns:
        raise ValueError(f"실제 VWAP 계산용 KRX 컬럼 누락: {sorted(missing_columns)}")

    adjusted.index = pd.to_datetime(adjusted.index).normalize()
    raw.index = pd.to_datetime(raw.index).normalize()
    if adjusted.index.has_duplicates or raw.index.has_duplicates:
        raise ValueError("Duplicate OHLC source dates")
    raw_fields = raw[sorted(required_raw_columns)].apply(
        pd.to_numeric, errors="coerce"
    )
    combined = adjusted.drop(columns=list(required_raw_columns), errors="ignore").join(raw_fields, how="left")
    combined["Volume"] = combined["RawVolume"]

    traded = pd.to_numeric(combined["Volume"], errors="coerce").fillna(0) > 0
    invalid = traded & (
        combined["RawClose"].isna()
        | combined["RawClose"].le(0)
        | combined["RawVolume"].isna()
        | combined["RawVolume"].le(0)
        | combined["Amount"].isna()
        | combined["Amount"].le(0)
    )
    if invalid.any():
        invalid_dates = ", ".join(
            timestamp.strftime("%Y-%m-%d") for timestamp in combined.index[invalid][:5]
        )
        raise ValueError(f"거래일의 KRX 거래대금/거래량이 유효하지 않습니다: {invalid_dates}")

    # KRX can report turnover without a regular-session OHLC bar. Preserve the
    # zero sentinel and actual VWAP; it is not evidence of a tradable daily bar.
    unavailable = combined[["RawOpen", "RawHigh", "RawLow"]].eq(0).all(axis=1)
    combined["RegularSessionUnavailable"] = unavailable
    raw_prices = combined.loc[traded & ~unavailable, ["RawOpen", "RawHigh", "RawLow", "RawClose"]]
    if (not np.isfinite(raw_prices.to_numpy()).all() or raw_prices.le(0).any().any()
            or raw_prices.RawLow.gt(raw_prices[["RawOpen", "RawClose"]].min(axis=1)).any()
            or raw_prices.RawHigh.lt(raw_prices[["RawOpen", "RawClose"]].max(axis=1)).any()):
        raise ValueError("KRX raw OHLC relationship invalid")
    valid_raw_close = combined["RawClose"].where(combined["RawClose"] > 0)
    combined["AdjustmentFactor"] = combined["Close"] / valid_raw_close
    factor = combined.loc[traded, "AdjustmentFactor"]
    if not np.isfinite(factor).all() or factor.le(0).any():
        raise ValueError("Invalid adjustment factor")
    # Preserve the supplier close as the factor anchor, then scale every KRX OHLC field.
    for column in ("Open", "High", "Low", "Close"):
        combined[column] = combined[f"Raw{column}"] * combined["AdjustmentFactor"]
    combined["PriceBasis"] = "krx_raw_ohlc_uniform_close_ratio_v1"
    # Aggregation scope is unverified: range departures are quality observations.
    combined["VWAPScope"] = "KRX_amount_volume_scope_unverified"
    raw_vwap = combined["Amount"] / combined["RawVolume"]
    combined["VWAP"] = raw_vwap * combined["AdjustmentFactor"]
    combined.loc[~traded, "VWAP"] = float("nan")
    return combined


def _fetch_delisted_list(start_date: str) -> pd.DataFrame:
    """로그인된 KRX 세션으로 상폐 이력을 2년 단위로 조회합니다."""
    session = get_krx_session()
    if session is None:
        raise RuntimeError("KRX_ID와 KRX_PW를 설정해야 상폐 이력과 수급을 수집할 수 있습니다")

    start = pd.Timestamp(start_date)
    end = pd.Timestamp.today().normalize()
    parts = []
    while start <= end:
        chunk_end = min(start + pd.DateOffset(years=2) - pd.Timedelta(1, unit="D"), end)
        response = session.post(
            "https://data.krx.co.kr/comm/bldAttendant/getJsonData.cmd",
            data={
                "bld": "dbms/MDC/STAT/issue/MDCSTAT23801",
                "mktId": "ALL", "isuCd": "ALL", "isuCd2": "ALL",
                "strtDd": start.strftime("%Y%m%d"),
                "endDd": chunk_end.strftime("%Y%m%d"),
                "share": "1", "csvxls_isNo": "true",
            },
            timeout=30,
        )
        response.raise_for_status()
        try:
            rows = response.json()["output"]
        except (ValueError, KeyError, TypeError) as exc:
            raise RuntimeError(f"KRX 상폐 목록 응답 오류: {start:%Y-%m-%d}~{chunk_end:%Y-%m-%d}") from exc
        parts.append(pd.DataFrame(rows))
        start = chunk_end + pd.Timedelta(1, unit="D")

    raw = pd.concat(parts, ignore_index=True)
    if raw.empty:
        raise RuntimeError("KRX 상폐 목록이 비어 있습니다. 로그인 상태와 KRX 응답을 확인하세요")
    return raw.rename(columns={
        "ISU_CD": "Symbol", "ISU_NM": "Name", "MKT_NM": "Market",
        "SECUGRP_NM": "SecuGroup", "LIST_DD": "ListingDate",
        "DELIST_DD": "DelistingDate",
    })


# krx -> 한국 거래소 정보데이터 시스템에서 직접 post 요청 날려서 긁어옴.
class KrxResponseError(RuntimeError):
    """Preserve transport/auth failures that pykrx otherwise converts to empty data."""

    def __init__(self, message, **details):
        super().__init__(message)
        self.details = details


@contextmanager
def _krx_request_timeout(timeout=(10, 30)):
    """Bound pykrx's HTTP calls without altering the shared session permanently."""
    authenticated = get_krx_session()
    if authenticated is None:
        raise RuntimeError("Authenticated KRX session required for bounded flow requests")
    session = authenticated.session
    original = session.request
    previous = session.__dict__.get("request")

    def request(*args, **kwargs):
        kwargs.setdefault("timeout", timeout)
        response = original(*args, **kwargs)
        url = str(kwargs.get("url", args[1] if len(args) > 1 else ""))
        if "data.krx.co.kr/comm/bldAttendant/getJsonData.cmd" in url:
            response.raise_for_status()
            try:
                response.json()
            except ValueError as exc:
                body = response.text.strip()
                auth_failed = body.upper() == "LOGOUT" or "login.jsp" in body or "MDCCOMS001" in body
                if auth_failed:
                    # Refresh on the next retry, even if the library's one-hour
                    # estimate says valid. Never include raw HTML/cookies in logs.
                    authenticated.expiry_time = 0
                kind = "authentication lost; session marked for refresh" if auth_failed else "non-JSON response (service error or access restriction)"
                raise KrxResponseError(
                    f"KRX {kind}; HTTP {response.status_code}, "
                    f"content-type={response.headers.get('Content-Type', 'unknown')}, "
                    f"bytes={len(response.content)}",
                    http_status=response.status_code,
                    content_type=response.headers.get("Content-Type", "unknown"),
                    response_bytes=len(response.content),
                    response_kind="auth_expired" if auth_failed else "non_json",
                ) from exc
        return response

    session.request = request
    try:
        yield
    finally:
        if previous is None:
            del session.request
        else:
            session.request = previous


def _fetch_investor_day(day: pd.Timestamp, *, progress=None) -> pd.DataFrame:
    """Fetch three investor responses with bounded HTTP calls and transient retries."""
    date_str = day.strftime("%Y%m%d")
    parts = []
    for prefix, investor in _INVESTORS.items():
        for attempt in range(1, 4):
            event = {"investor": prefix, "attempt": attempt, "state": "requesting"}
            if progress:
                progress(event)
            try:
                with _krx_request_timeout():
                    source = krx.get_market_net_purchases_of_equities_by_ticker(
                        date_str, date_str, market="ALL", investor=investor
                    )
                if source is None or source.empty:
                    raise RuntimeError("Empty flow response")
                break
            except Exception as exc:
                if progress:
                    progress({**event, "state": "request_failed", "reason": str(exc),
                              "exception_type": type(exc).__name__, **getattr(exc, "details", {})})
                if attempt == 3:
                    raise RuntimeError(
                        f"{date_str} {investor}: flow request failed after {attempt} attempts"
                    ) from exc
                time.sleep(attempt)
        required = set(_FLOW_SOURCE) | {"순매수거래량", "순매수거래대금"}
        if source is None or source.empty or not required.issubset(source.columns):
            raise RuntimeError(f"{date_str} {investor}: 수급 응답이 비었거나 필수 열이 없습니다")
        source = source.copy()
        source[list(required)] = source[list(required)].apply(pd.to_numeric, errors="coerce")
        if source[list(required)].isna().any().any():
            raise ValueError(f"{date_str} {investor}: 수급 값에 결측치가 있습니다")
        for kind in ("거래량", "거래대금"):
            if not (source[f"매수{kind}"] - source[f"매도{kind}"]).eq(
                source[f"순매수{kind}"]
            ).all():
                raise ValueError(f"{date_str} {investor}: 순매수 {kind} 정합성 오류")
        if source[list(_FLOW_SOURCE)].lt(0).any().any():
            raise ValueError(f"{date_str} {investor}: 음수 매수·매도 값")
        source.index = source.index.astype(str).str.zfill(6)
        source.index.name = "Code"
        part = source[list(_FLOW_SOURCE)].rename(
            columns={key: f"{prefix}_{value}" for key, value in _FLOW_SOURCE.items()}
        )
        parts.append(part)
        time.sleep(0.3)
    flow = pd.concat(parts, axis=1).astype("Int64").reset_index()
    flow["Date"] = day
    return flow[["Date", "Code", *_FLOW_COLUMNS]]
