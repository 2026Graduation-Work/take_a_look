"""Verified security listing intervals shared by research and daily collection."""
import html
import json
import re
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import pandas as pd

from shared.io import atomic_json, atomic_parquet, sha256
from shared.settings import processing_contract


def fetch_active_listing_intervals(market):
    """Use each security's own KRX listing date, including preferred shares."""
    from shared.data.providers import get_krx_session

    session = get_krx_session()
    if session is None:
        raise ValueError("KRX authenticated session required for listing metadata")
    response = session.post(
        "https://data.krx.co.kr/comm/bldAttendant/getJsonData.cmd",
        data={"bld": "dbms/MDC/STAT/standard/MDCSTAT01901", "mktId": "ALL",
              "share": "1", "csvxls_isNo": "false"},
        timeout=(10, 30),
    )
    response.raise_for_status()
    frame = pd.DataFrame(response.json()["OutBlock_1"]).rename(columns={
        "ISU_SRT_CD": "Code", "ISU_ABBRV": "Name", "MKT_TP_NM": "Market",
        "LIST_DD": "ListingDate", "SECUGRP_NM": "SecurityGroup",
    })
    required = {"Code", "Name", "Market", "ListingDate", "SecurityGroup"}
    if required - set(frame):
        raise ValueError("KRX individual-security metadata lacks required fields")
    # KOSDAQ GLOBAL is a segment of KOSDAQ, not a separate exchange universe.
    frame["Market"] = frame.Market.replace({"KOSDAQ GLOBAL": "KOSDAQ"})
    frame = frame.loc[frame.Market.eq(market) & frame.SecurityGroup.eq("주권")].copy()
    frame["Code"] = frame.Code.astype(str).str.zfill(6)
    frame["ListingDate"] = pd.to_datetime(frame.ListingDate, errors="coerce")
    if frame.empty or frame.Code.duplicated().any() or frame.ListingDate.isna().any():
        raise ValueError(f"{market}: invalid KRX individual-security listing metadata")
    return frame[["Code", "Name", "Market", "ListingDate"]]


def load_metadata(collection, end):
    from shared.data import providers as source

    parts = []
    for market in collection["markets"]:
        active_source = f"{market}-DESC"
        try:
            frame = source.fdr.StockListing(f"{market}-DESC").copy()
            if {"Code", "Name", "ListingDate"} - set(frame) or pd.to_datetime(
                frame.ListingDate, errors="coerce"
            ).isna().any():
                raise ValueError("FDR listing dates incomplete; use KRX individual securities")
        except Exception:
            active_source = "KRX individual securities MDCSTAT01901"
            frame = fetch_active_listing_intervals(market)
        required = {"Code", "Name", "ListingDate"}
        if required - set(frame):
            raise ValueError(f"{market}-DESC lacks verified listing dates")
        frame = frame.assign(
            Market=market, DelistingDate=pd.NaT, IsDelisted=False, Source=active_source
        )
        parts.append(frame)
    if collection["include_delisted"]:
        frame = source._fetch_delisted_list(collection["start_date"])
        frame = frame.loc[frame.Market.isin(collection["markets"]) & frame.SecuGroup.eq("주권")]
        parts.append(
            frame.rename(columns={"Symbol": "Code"}).assign(IsDelisted=True, Source="KRX-DELISTING")
        )
    columns = ["Code", "Name", "Market", "ListingDate", "DelistingDate", "IsDelisted", "Source"]
    metadata = pd.concat([part[columns] for part in parts], ignore_index=True)
    metadata["Code"] = metadata.Code.astype(str).str.zfill(6)
    if collection.get("tickers"):
        metadata = metadata.loc[
            metadata.Code.isin([str(code).zfill(6) for code in collection["tickers"]])
        ].copy()
    metadata["ListingDate"] = pd.to_datetime(metadata.ListingDate, errors="coerce")
    metadata["DelistingDate"] = pd.to_datetime(metadata.DelistingDate, errors="coerce")
    if (
        metadata.ListingDate.isna().any()
        or metadata.loc[metadata.IsDelisted, "DelistingDate"].isna().any()
    ):
        bad = metadata.ListingDate.isna() | (metadata.IsDelisted & metadata.DelistingDate.isna())
        details = metadata.loc[bad, ["Code", "Name", "Market", "Source"]].head(20).to_dict("records")
        raise ValueError(f"Unknown listing interval for {int(bad.sum())} securities: {details}")
    metadata = metadata.loc[
        (metadata.ListingDate <= pd.Timestamp(end))
        & (
            metadata.DelistingDate.isna()
            | (metadata.DelistingDate > pd.Timestamp(collection["start_date"]))
        )
    ]
    if tickers := collection.get("tickers"):
        metadata = metadata.loc[metadata.Code.isin([str(code).zfill(6) for code in tickers])]
        if set(str(code).zfill(6) for code in tickers) - set(metadata.Code):
            raise ValueError("Requested ticker lacks verified metadata")
    metadata = metadata.drop_duplicates(["Code", "ListingDate", "DelistingDate"]).sort_values(
        ["Code", "ListingDate"]
    )
    for code, intervals in metadata.groupby("Code"):
        previous_end = None
        for i, row in enumerate(intervals.itertuples()):
            if i and (pd.isna(previous_end) or row.ListingDate < previous_end):
                raise ValueError(f"Overlapping listing intervals: {code}")
            previous_end = row.DelistingDate
    if metadata.empty:
        raise ValueError("Empty metadata")
    metadata["MarketHistoryVerified"] = False
    return metadata



def fetch_current_universe(as_of, *, root, code=None):
    from . import providers
    if code:
        if not re.fullmatch(r"[0-9A-Z]{6}", code):
            raise ValueError("Stock code must be six uppercase alphanumeric characters")
        codes = [code]
    else:
        codes = providers.krx.get_market_ticker_list(as_of.replace("-", ""), market="KOSPI")
        if not 500 <= len(codes) <= 1200:
            raise ValueError("Invalid KOSPI universe size")
    path = Path(root) / f"{as_of}_{'single' if code else 'kospi'}.parquet"
    sidecar = path.with_suffix(".json")
    contract = processing_contract()["sha256"]
    metadata = None
    if path.exists() and sidecar.exists():
        saved = json.loads(sidecar.read_text())
        if saved.get("sha256") == sha256(path) and saved.get("processing_contract_sha256") == contract:
            metadata = pd.read_parquet(path)
    if metadata is None:
        metadata = load_metadata({"start_date": "1900-01-01", "markets": ["KOSPI", "KOSDAQ"] if code else ["KOSPI"],
                                  "include_delisted": False}, as_of)
        atomic_parquet(path, metadata)
        atomic_json(sidecar, {"sha256": sha256(path), "as_of": as_of,
                              "processing_contract_sha256": contract, "source": "shared v3 listing adapters"})
    rows = metadata.loc[metadata.Code.isin(codes), ["Code", "ListingDate"]].copy()
    if set(codes) != set(rows.Code) or rows.Code.duplicated().any() or rows.ListingDate.isna().any():
        raise ValueError("Current universe lacks verified individual listing intervals")
    rows["ListingDate"] = pd.to_datetime(rows.ListingDate, errors="coerce")
    if rows.ListingDate.isna().any() or rows.ListingDate.gt(pd.Timestamp(as_of)).any():
        raise ValueError("Current universe has invalid or future listing intervals")
    rows["Name"] = [providers.krx.get_market_ticker_name(item) for item in rows.Code]
    if not rows.Code.str.fullmatch(r"[0-9A-Z]{6}").all() or rows.Name.isna().any() or not rows.Name.astype(str).str.strip().all():
        raise ValueError("Invalid KOSPI universe")
    return rows[["Code", "Name", "ListingDate"]].sort_values("Code").reset_index(drop=True)


def fetch_security_listing(market):
    from .providers import fdr
    return fdr.StockListing(market)


def fetch_index_prices(symbol, start, end):
    from .providers import fdr
    return fdr.DataReader(symbol, start, end)


def parse_managed_names(page):
    names = re.findall(r'<td class="first">(.*?)</td>', page, re.S)
    return {html.unescape(re.sub(r"<[^>]+>", " ", cell)).strip() for cell in names} - {""}


def fetch_managed_names():
    body = urlencode({"method": "searchAdminIssueSub", "currentPageSize": 3000, "pageIndex": 1,
                      "orderMode": 1, "orderStat": "D", "marketType": "", "forward": "adminissue_sub"})
    request = Request("https://kind.krx.co.kr/investwarn/adminissue.do", data=body.encode(),
                      headers={"User-Agent": "Mozilla/5.0"})
    with urlopen(request, timeout=30) as response:
        names = parse_managed_names(response.read().decode("utf-8"))
    if not names:
        raise RuntimeError("KIND 관리종목 목록이 비어 있습니다")
    return names
