import os
import time
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path

import FinanceDataReader as fdr
import numpy as np
import pandas as pd
from dotenv import load_dotenv
from tqdm import tqdm

# pykrx는 import 시점에 로그인 세션을 만들므로 .env를 먼저 읽어야 합니다.
load_dotenv(Path(__file__).resolve().parents[2] / ".env")

class _KrxProvider:
    def __getattr__(self, name):
        from pykrx import stock
        return getattr(stock, name)


krx = _KrxProvider()


def get_krx_session():
    from pykrx.website.comm.webio import get_session
    return get_session()


try:
    from .trading_calendar import get_krx_trading_days
except ImportError:  # 직접 스크립트 실행: python data_collectors/price_collector.py
    from trading_calendar import get_krx_trading_days


# 데이터 저장 경로 설정
DATA_DIR = str(Path(__file__).resolve().parents[2] / "workspace/archive/data/raw")

# 기본 전체 수집 시작일 (최근 10년 기준, 실행 연도 자동 반영)
_DEFAULT_START_DATE = f"{datetime.now().year - 10}-01-01"
_VWAP_COLUMNS = {"Amount", "RawOpen", "RawHigh", "RawLow", "RawClose", "RawVolume", "AdjustmentFactor", "VWAP"}
_INVESTORS = {"Individual": "개인", "Institution": "기관합계", "Foreign": "외국인"}
_FLOW_SOURCE = {
    "매수거래량": "BuyVolume", "매도거래량": "SellVolume",
    "매수거래대금": "BuyAmount", "매도거래대금": "SellAmount",
}
_FLOW_COLUMNS = [f"{prefix}_{suffix}" for prefix in _INVESTORS for suffix in _FLOW_SOURCE.values()]
FLOW_CACHE_DIR = str(Path(__file__).resolve().parents[2] / "workspace/archive/data/investor_flow_cache")


def _has_complete_actual_vwap(df: pd.DataFrame) -> bool:
    """거래량이 있는 모든 행에 실제 VWAP 산출 필드가 유효한지 확인합니다."""
    if not _VWAP_COLUMNS.issubset(df.columns) or "Volume" not in df.columns:
        return False
    traded = pd.to_numeric(df["Volume"], errors="coerce").fillna(0) > 0
    if not traded.any():
        return True
    numeric = df.loc[traded, sorted(_VWAP_COLUMNS)].apply(pd.to_numeric, errors="coerce")
    ohl = ["RawOpen", "RawHigh", "RawLow"]
    unavailable = numeric[ohl].eq(0).all(axis=1)
    return bool(np.isfinite(numeric.to_numpy(dtype=float, na_value=np.nan)).all()
                and numeric.drop(columns=ohl).gt(0).all().all()
                and numeric.loc[~unavailable, ohl].gt(0).all().all())


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
        chunk_end = min(start + pd.DateOffset(years=2) - pd.Timedelta(days=1), end)
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
        start = chunk_end + pd.Timedelta(days=1)

    raw = pd.concat(parts, ignore_index=True)
    if raw.empty:
        raise RuntimeError("KRX 상폐 목록이 비어 있습니다. 로그인 상태와 KRX 응답을 확인하세요")
    return raw.rename(columns={
        "ISU_CD": "Symbol", "ISU_NM": "Name", "MKT_NM": "Market",
        "SECUGRP_NM": "SecuGroup", "LIST_DD": "ListingDate",
        "DELIST_DD": "DelistingDate",
    })


def get_all_tickers(
    start_date: str = _DEFAULT_START_DATE, include_delisted: bool = True
) -> pd.DataFrame:
    """
    KOSPI, KOSDAQ 활성 종목과 KRX 상장폐지 이력을 병합합니다.
    """
    print("수집 대상 종목 리스트 구성 중...")

    # 1. 활성 상장 종목 (KOSPI & KOSDAQ)
    try:
        kospi = fdr.StockListing("KOSPI")
        kosdaq = fdr.StockListing("KOSDAQ")
        active = pd.concat([kospi, kosdaq], ignore_index=True)
        active = active[["Code", "Name"]].drop_duplicates()
        active["IsDelisted"] = False
        active["ListingDate"] = pd.NaT
        active["DelistingDate"] = pd.NaT
        print(f"  [활성] KOSPI/KOSDAQ 총 {len(active)}개")
    except Exception as e:
        raise RuntimeError(f"활성 종목 리스트 수집 실패: {e}") from e

    if not include_delisted:
        active["Code"] = active["Code"].astype(str).str.zfill(6)
        return active

    # 2. 상장폐지 종목 (KRX 이력 API)
    try:
        raw_delisted = _fetch_delisted_list(start_date)
        required = {"Symbol", "Name", "Market", "SecuGroup", "ListingDate", "DelistingDate"}
        if missing := required - set(raw_delisted.columns):
            raise ValueError(f"상폐 목록 필수 컬럼 누락: {sorted(missing)}")
        delisted = raw_delisted.loc[
            raw_delisted["Market"].isin(["KOSPI", "KOSDAQ"])
            & raw_delisted["SecuGroup"].eq("주권")
        ].rename(columns={"Symbol": "Code"})[
            ["Code", "Name", "ListingDate", "DelistingDate"]
        ].drop_duplicates()
        if delisted.empty:
            raise ValueError("KRX 응답에 KOSPI/KOSDAQ 상폐 주권이 없습니다")
        delisted[["ListingDate", "DelistingDate"]] = delisted[
            ["ListingDate", "DelistingDate"]
        ].apply(pd.to_datetime, errors="coerce")
        if delisted[["ListingDate", "DelistingDate"]].isna().any().any():
            raise ValueError("상폐 목록에 상장일/상장폐지일 누락")
        delisted["IsDelisted"] = True
        print(f"  [상폐] KRX 이력 총 {len(delisted)}개")
    except Exception as e:
        print(f"  [상폐] 리스트 수집 실패: {e}")
        raise RuntimeError("상장폐지 종목의 상장 기간을 확인할 수 없습니다") from e

    # 3. 병합
    all_stocks = pd.concat([active, delisted], ignore_index=True)
    # KRX 한국 증시 표준 규격이 6자리 문자열임
    # 파이썬, csv 에서 데이터 읽을 때 맨 앞에 0 잘라버려서 이거 신경써줘야함
    all_stocks["Code"] = all_stocks["Code"].str.zfill(6)
    all_stocks = all_stocks.drop_duplicates(
        subset=["Code", "ListingDate", "DelistingDate"], keep="first"
    )
    print(f"  [합계] 총 {len(all_stocks)}개 종목")

    all_stocks.to_csv("./data/ticker_metadata.csv", index=False, encoding="utf-8-sig")
    print("  종목 메타데이터 저장 완료 (./data/ticker_metadata.csv)")
    return all_stocks


# krx -> 한국 거래소 정보데이터 시스템에서 직접 post 요청 날려서 긁어옴.
def _fetch_ohlcv_pykrx(code: str, start_date: str, end_date: str, *, raw_df=None) -> pd.DataFrame:
    """
    pykrx로 수정주가(adjusted=True) 기준 일봉 OHLCV를 가져옵니다.
    등락률(Change)은 % 단위를 유지합니다.
    """
    start_yyyymmdd = start_date.replace("-", "")
    end_yyyymmdd = end_date.replace("-", "")

    adjusted_df = krx.get_market_ohlcv_by_date(
        start_yyyymmdd,
        end_yyyymmdd,
        code,
        adjusted=True,
    )
    if raw_df is None:
        raw_df = krx.get_market_ohlcv_by_date(
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
    return _attach_actual_vwap(adjusted_df, raw_df)


def _fetch_ohlcv_fdr(code: str, start_date: str, end_date: str, *, raw_df=None) -> pd.DataFrame:
    """
    FinanceDataReader로 수정주가 기준 일봉 OHLCV를 가져옵니다.
    FDR의 Change(소수점 단위)를 퍼센트(%) 단위로 변환하여 pykrx와 스케일을 통일합니다.
    """
    t = time.time()
    try:
        adjusted_df = fdr.DataReader(code, start_date, end_date)
        print(code, "FDR:", time.time() - t)
        t = time.time()
        if raw_df is None:
            raw_df = krx.get_market_ohlcv_by_date(
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
        return _attach_actual_vwap(adjusted_df, raw_df)
    except Exception:
        # print(f"  [FDR Fetch Error] {code}: {e}")
        return pd.DataFrame()


def _fetch_delisted_pykrx(code: str, start_date: str, end_date: str, *, raw_df=None) -> pd.DataFrame:
    """상폐 종목의 KRX 원가격·거래대금과 수정가격을 날짜별로 결합합니다."""
    start, end = start_date.replace("-", ""), end_date.replace("-", "")
    raw = raw_df if raw_df is not None else krx.get_market_ohlcv_by_date(start, end, code, adjusted=False)
    if raw.empty:
        raise ValueError(f"{code}: 상폐 종목 KRX 원가격/거래대금을 확인할 수 없습니다")
    adjusted = krx.get_market_ohlcv_by_date(
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
    return _attach_actual_vwap(adjusted, raw)


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


def _cached_investor_day(day: pd.Timestamp) -> pd.DataFrame:
    cache = Path(FLOW_CACHE_DIR) / f"{day:%Y}" / f"{day:%Y-%m-%d}.parquet"
    if cache.exists():
        frame = pd.read_parquet(cache)
        if {"Date", "Code", *_FLOW_COLUMNS}.issubset(frame.columns):
            return frame
    frame = _fetch_investor_day(day)
    cache.parent.mkdir(parents=True, exist_ok=True)
    frame.to_parquet(cache, index=False)
    return frame


def _merge_investor_flows(flow: pd.DataFrame, codes: set[str] | None = None) -> None:
    """조회된 날짜만 raw에 병합하고, 이미 수집된 다른 날짜는 보존합니다."""
    flow = flow.copy()
    flow["Date"] = pd.to_datetime(flow["Date"]).dt.normalize()
    days = flow["Date"].unique()
    grouped = {code: part.set_index("Date") for code, part in flow.groupby("Code")}
    paths = [Path(DATA_DIR) / f"{code}.parquet" for code in codes] if codes else Path(DATA_DIR).glob("*.parquet")
    for path in paths:
        if not path.exists():
            continue
        raw = pd.read_parquet(path)
        raw["Date"] = pd.to_datetime(raw["Date"]).dt.normalize()
        mask = raw["Date"].isin(days)
        if not mask.any():
            continue
        if not set(_FLOW_COLUMNS).issubset(raw.columns):
            for col in _FLOW_COLUMNS:
                if col not in raw:
                    raw[col] = pd.NA
        rows = raw.loc[mask, "Date"]
        values = grouped.get(path.stem)
        if values is None:
            raw.loc[mask, _FLOW_COLUMNS] = pd.NA
        else:
            raw.loc[mask, _FLOW_COLUMNS] = values.reindex(rows)[_FLOW_COLUMNS].to_numpy()
        for col in _FLOW_COLUMNS:
            raw[col] = pd.to_numeric(raw[col], errors="coerce").astype("Int64")
        raw.to_parquet(path, index=False)


def _backfill_investor_flows(start_date: str, end_date: str) -> None:
    """거래일별 체크포인트를 재사용하며 전체 raw의 수급 열을 채웁니다."""
    days = sorted(get_krx_trading_days(start_date, end_date))
    current_year = None
    parts = []
    for day in tqdm(days, desc="수급 이력 수집"):
        stamp = pd.Timestamp(day)
        if current_year is not None and stamp.year != current_year:
            _merge_investor_flows(pd.concat(parts, ignore_index=True))
            print(f"  {current_year}년 수급 raw 병합 완료")
            parts = []
        current_year = stamp.year
        parts.append(_cached_investor_day(stamp))
    if parts:
        _merge_investor_flows(pd.concat(parts, ignore_index=True))
        print(f"  {current_year}년 수급 raw 병합 완료")


def _update_ohlcv_bulk_fdr(all_stocks: pd.DataFrame) -> tuple[set[str], pd.Timestamp]:
    """
    KOSPI 지수로 확정한 최신 거래일의 FDR 전 종목 시세를 일괄 업데이트합니다.

    날짜가 없는 StockListing 값을 실행일로 간주하지 않고, 동일 공급자의 KOSPI
    지수에 존재하는 최신 거래일을 기준일로 사용합니다.
    """
    print("\n⚡ [FDR 벌크 업데이트] 최신 거래일 시세 일괄 수집 진행...")

    try:
        today = datetime.now().date()
        calendar_start = today - timedelta(days=14)
        trading_days = get_krx_trading_days(calendar_start.isoformat(), today.isoformat())
        actual_date = pd.Timestamp(max(trading_days))
        actual_date_str = actual_date.strftime("%Y-%m-%d")

        kospi = fdr.StockListing("KOSPI")
        kosdaq = fdr.StockListing("KOSDAQ")
        market_snapshot = pd.concat([kospi, kosdaq], ignore_index=True).rename(
            columns={
                "ChagesRatio": "Change",
            }
        )
        required_columns = {
            "Code",
            "Open",
            "High",
            "Low",
            "Close",
            "Volume",
            "Amount",
            "Change",
        }
        missing_columns = required_columns - set(market_snapshot.columns)
        if missing_columns:
            raise RuntimeError(f"FDR 전 종목 시세 필수 컬럼 누락: {sorted(missing_columns)}")
        market_snapshot = market_snapshot[market_snapshot["Volume"] > 0].copy()
        if market_snapshot["Amount"].isna().any() or market_snapshot["Amount"].le(0).any():
            raise RuntimeError("FDR 전 종목 시세에 유효하지 않은 거래대금이 있습니다.")
        market_snapshot["Code"] = market_snapshot["Code"].astype(str).str.zfill(6)
        print(f"  📅 수집된 실제 영업일 기준일: {actual_date_str}")

        current_stocks = all_stocks.drop_duplicates("Code", keep="first")
        ticker_to_name = dict(zip(current_stocks["Code"], current_stocks["Name"]))
        ticker_to_delisted = dict(zip(current_stocks["Code"], current_stocks["IsDelisted"]))

        updated_tickers = set()

        for _, row in market_snapshot.iterrows():
            code = row["Code"]
            file_path = os.path.join(DATA_DIR, f"{code}.parquet")

            name = ticker_to_name.get(code, "")
            is_delisted = ticker_to_delisted.get(code, False)

            # FDR StockListing의 ChagesRatio는 퍼센트(%) 단위입니다.
            change_val = float(row["Change"]) if not pd.isna(row["Change"]) else 0.0
            volume = float(row["Volume"])
            amount = float(row["Amount"])
            close = float(row["Close"])
            vwap = amount / volume

            new_row = pd.DataFrame(
                [
                    {
                        "Date": actual_date,
                        "Open": float(row["Open"]),
                        "High": float(row["High"]),
                        "Low": float(row["Low"]),
                        "Close": close,
                        "Volume": volume,
                        "Amount": amount,
                        "RawClose": close,
                        "RawVolume": volume,
                        "AdjustmentFactor": 1.0,
                        "VWAP": vwap,
                        "Change": change_val,
                        "Code": code,
                        "Name": name,
                        "IsDelisted": is_delisted,
                    }
                ]
            )

            if os.path.exists(file_path):
                try:
                    existing = pd.read_parquet(file_path)
                    existing["Date"] = pd.to_datetime(existing["Date"])

                    actual_rows = existing.loc[existing["Date"].eq(actual_date)]
                    has_actual_vwap = _has_complete_actual_vwap(actual_rows)
                    if actual_date in existing["Date"].values and has_actual_vwap:
                        updated_tickers.add(code)
                        continue

                    # 가격만 보정할 때 기존 수급 원천값을 보존한다.
                    if not actual_rows.empty:
                        for col in actual_rows.columns.difference(new_row.columns):
                            new_row[col] = actual_rows.iloc[-1][col]

                    merged = pd.concat([existing, new_row], ignore_index=True)
                    merged = (
                        merged.drop_duplicates(subset=["Date"], keep="last")
                        .sort_values(by="Date")
                        .reset_index(drop=True)
                    )
                    merged.to_parquet(file_path, index=False)
                    updated_tickers.add(code)
                except Exception as exc:
                    raise RuntimeError(f"{code} 기존 raw 병합 실패: {exc}") from exc
            else:
                new_row.to_parquet(file_path, index=False)
                updated_tickers.add(code)

        print(f"  ✅ FDR 벌크 반영 성공: {len(updated_tickers)}개 활성 종목 최신 시세 주입 완료.")
        return updated_tickers, actual_date
    except Exception as e:
        raise RuntimeError(f"FDR 벌크 업데이트 실패: {e}") from e


def update_ohlcv_daily():
    """
    [데일리 증분 업데이트 함수]
    최신 거래일의 가격과 개인/기관합계/외국인 수급 원천값을 갱신합니다.
    """
    all_stocks = get_all_tickers(include_delisted=False)
    updated_tickers, actual_date = _update_ohlcv_bulk_fdr(all_stocks)
    if not updated_tickers:
        raise RuntimeError("KRX 일일 가격 업데이트에 실패했습니다.")
    _merge_investor_flows(_cached_investor_day(actual_date), codes=updated_tickers)
    print("\n✅ 일일 가격·수급 업데이트 완료.")


def download_ohlcv_full(start_date: str = _DEFAULT_START_DATE, repair_only: bool = False):
    """
    [전체 이력 수집 및 정밀 보정 함수]
    지정된 start_date부터 오늘까지 전체 종목의 과거 가격 이력을 다운로드하여 구축합니다.
    또한, 이미 구축된 파일 중 중간 영업일(Gap) 누락을 감지하고 메워줍니다.
    속도와 안정성을 위해 FDR DataReader를 기본으로 사용하고 pykrx를 백업으로 사용합니다.
    """
    all_stocks = get_all_tickers(start_date)
    today_str = datetime.now().strftime("%Y-%m-%d")

    # 개별 종목이 아닌 KRX 시장 메타데이터로 실제 개장일을 확정합니다.
    actual_business_days = get_krx_trading_days(start_date, today_str)

    print(f"\n[*] OHLCV 전체 이력 수집/보정 가동 | 시작일: {start_date} | 종료일: {today_str}")
    failed = []

    for _, row in tqdm(all_stocks.iterrows(), total=len(all_stocks), desc="전체 수집 및 갭 복구"):
        code = row["Code"]
        name = row["Name"]
        is_delisted = row["IsDelisted"]
        listing_date = pd.to_datetime(row["ListingDate"])
        delisting_date = pd.to_datetime(row["DelistingDate"])
        fetch_start = (
            max(pd.Timestamp(start_date), listing_date)
            if pd.notna(listing_date) else pd.Timestamp(start_date)
        )
        # KRX DelistingDate는 종목이 더 이상 상장되지 않은 첫날이다.
        fetch_end = (
            min(pd.Timestamp(today_str), delisting_date - pd.Timedelta(days=1))
            if pd.notna(delisting_date) else pd.Timestamp(today_str)
        )
        if fetch_start > fetch_end:
            continue
        stock_start_str = fetch_start.strftime("%Y-%m-%d")
        stock_end_str = fetch_end.strftime("%Y-%m-%d")

        file_path = os.path.join(DATA_DIR, f"{code}.parquet")

        try:
            existing_df = None
            needs_download = True
            fetch_start_str = stock_start_str

            if os.path.exists(file_path):
                existing_df = pd.read_parquet(file_path)
                if not existing_df.empty:
                    existing_df["Date"] = pd.to_datetime(existing_df["Date"])
                    period_existing = existing_df.loc[
                        existing_df["Date"].between(fetch_start, fetch_end)
                    ]
                else:
                    period_existing = existing_df
                if not period_existing.empty:

                    # 1. 중간 누락(Gap) 탐지
                    first_date = period_existing["Date"].min()
                    check_start = max(first_date, fetch_start)
                    vwap_incomplete = not _has_complete_actual_vwap(
                        period_existing.loc[period_existing["Date"] >= check_start]
                    )
                    check_days = {
                        d for d in actual_business_days
                        if check_start.date() <= d <= fetch_end.date()
                    }
                    existing_dates = set(period_existing["Date"].dt.date)
                    missing_days = check_days - existing_dates

                    last_date = period_existing["Date"].max()
                    fetch_start_str = (last_date + pd.Timedelta(days=1)).strftime("%Y-%m-%d")

                    # 2. 업데이트 및 보정 필요성 판단
                    if fetch_start_str <= stock_end_str or missing_days or vwap_incomplete:
                        needs_download = True
                        # 누락이 많거나 업데이트 범위가 넓으면 해당 종목만 start_date부터 전체를 다시 받아 머지
                        fetch_start_str = stock_start_str
                    else:
                        if repair_only:
                            continue
                        needs_download = False

            if not needs_download:
                continue

            if is_delisted:
                df = _fetch_delisted_pykrx(code, fetch_start_str, stock_end_str)
            else:
                df = _fetch_ohlcv_fdr(code, fetch_start_str, stock_end_str)
                if df.empty:
                    df = _fetch_ohlcv_pykrx(code, fetch_start_str, stock_end_str)

            if df.empty:
                failed.append((code, name, is_delisted, "No data fetched"))
                continue

            df = df.loc[(df.index >= fetch_start) & (df.index <= fetch_end)]
            if df.empty:
                failed.append((code, name, is_delisted, "No data within listing interval"))
                continue
            df = df.reset_index()
            df["Code"] = code
            df["Name"] = name
            df["IsDelisted"] = is_delisted

            if existing_df is not None:
                # 재수집한 가격 행에 이미 확보한 수급 열을 날짜 기준으로 복원한다.
                flow_columns = [
                    c for c in existing_df
                    if c.endswith(("BuyVolume", "SellVolume", "BuyAmount", "SellAmount"))
                ]
                if flow_columns:
                    previous_flows = existing_df[["Date", *flow_columns]].drop_duplicates(
                        "Date", keep="last"
                    )
                    df = df.merge(previous_flows, on="Date", how="left")
                combined_df = pd.concat([existing_df, df], ignore_index=True)
                combined_df["Date"] = pd.to_datetime(combined_df["Date"])
                combined_df = (
                    combined_df.drop_duplicates(subset=["Date"], keep="last")
                    .sort_values(by="Date")
                    .reset_index(drop=True)
                )
            else:
                combined_df = df

            combined_df.to_parquet(file_path, index=False)
            time.sleep(0.05)  # FDR 중심이라 슬립 시간을 줄여 고속 처리 가능

        except Exception as e:
            failed.append((code, name, is_delisted, str(e)))
            time.sleep(0.1)

    if failed:
        pd.DataFrame(failed, columns=["Code", "Name", "IsDelisted", "Error"]).to_csv(
            "./data/failed_downloads.csv", index=False, encoding="utf-8-sig"
        )
        print(f"\n⚠️ 수집/보정 중 실패: {len(failed)}개 → ./data/failed_downloads.csv 참고")

        raise RuntimeError(f"가격 수집 실패 {len(failed)}개: ./data/failed_downloads.csv 확인")

    _backfill_investor_flows(start_date=start_date, end_date=today_str)
    print("\n✅ 전체 가격·수급 데이터 다운로드 및 갭 보정 완료.")


