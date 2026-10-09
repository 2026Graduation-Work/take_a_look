"""학습 종료일 기준 KOSPI 주권 universe 스냅샷을 생성한다."""

from __future__ import annotations

import argparse
import ssl
from datetime import date
from pathlib import Path
from urllib.error import HTTPError

import pandas as pd

from .package_processed import HandoffContractError


def fetch_listing_inputs(history_start: str | None = None) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Use FDR's daily cache, falling back to its direct KRX readers on a cache 404."""
    import FinanceDataReader as fdr

    try:
        return fdr.StockListing("KOSPI-DESC"), fdr.StockListing("KRX-DELISTING")
    except HTTPError as exc:
        if exc.code != 404:
            raise
        print(
            "FinanceDataReader listing cache returned HTTP 404; "
            "retrying through its direct KRX readers.",
            flush=True,
        )

    from FinanceDataReader.krx.listing import KrxDelisting, KrxStockListing

    default_ssl_context = ssl._create_default_https_context
    try:
        active = KrxStockListing("KOSPI-DESC").read()
    finally:
        ssl._create_default_https_context = default_ssl_context
    delisted = KrxDelisting(
        "KRX-DELISTING", start=history_start or "1960-01-01", end=date.today().isoformat()
    ).read()
    return active, delisted


def _codes(values: pd.Series) -> pd.Series:
    codes = values.astype("string").str.strip().str.upper().str.zfill(6)
    invalid = ~codes.fillna("").str.fullmatch(r"[0-9A-Z]{6}")
    if invalid.any():
        raise HandoffContractError(f"유효하지 않은 KRX 단축코드: {codes[invalid].head().tolist()}")
    return codes


def build_kospi_snapshot(
    active: pd.DataFrame,
    delisted: pd.DataFrame,
    *,
    cutoff: str,
    processed_dir: str | Path,
) -> pd.DataFrame:
    """현재 활성 목록과 상폐 이력으로 cutoff 당시 KOSPI 주권을 복원한다."""
    cutoff_date = pd.Timestamp(cutoff).normalize()
    active_required = {"Code", "Name", "Market", "ListingDate"}
    delisted_required = {
        "Symbol",
        "Name",
        "Market",
        "SecuGroup",
        "ListingDate",
        "DelistingDate",
    }
    if missing := sorted(active_required - set(active.columns)):
        raise HandoffContractError(f"KOSPI-DESC 필수 컬럼 누락: {missing}")
    if missing := sorted(delisted_required - set(delisted.columns)):
        raise HandoffContractError(f"KRX-DELISTING 필수 컬럼 누락: {missing}")

    active = active.copy()
    active["ListingDate"] = pd.to_datetime(active["ListingDate"], errors="coerce")
    active = active[
        active["Market"].eq("KOSPI") & active["ListingDate"].le(cutoff_date)
    ].copy()
    active["Code"] = _codes(active["Code"])
    active = active[["Code", "Name", "ListingDate"]]
    active["DelistingDate"] = pd.NaT
    active["Source"] = "KOSPI-DESC"

    delisted = delisted.copy()
    delisted["ListingDate"] = pd.to_datetime(delisted["ListingDate"], errors="coerce")
    delisted["DelistingDate"] = pd.to_datetime(delisted["DelistingDate"], errors="coerce")
    delisted = delisted[
        delisted["Market"].eq("KOSPI")
        & delisted["SecuGroup"].eq("주권")
        & delisted["ListingDate"].le(cutoff_date)
        & delisted["DelistingDate"].gt(cutoff_date)
    ].copy()
    delisted["Code"] = _codes(delisted["Symbol"])
    delisted = delisted[["Code", "Name", "ListingDate", "DelistingDate"]]
    delisted["Source"] = "KRX-DELISTING"

    snapshot = pd.concat([active, delisted], ignore_index=True)
    snapshot = snapshot.sort_values(["Code", "Source"], kind="stable")
    snapshot = snapshot.drop_duplicates("Code", keep="first").reset_index(drop=True)
    processed_codes = {path.stem.upper() for path in Path(processed_dir).glob("*.parquet")}
    missing_processed = sorted(set(snapshot["Code"]) - processed_codes)
    if missing_processed:
        raise HandoffContractError(
            "KOSPI snapshot에 대응하는 processed 파일이 없습니다: "
            f"{missing_processed[:20]} (총 {len(missing_processed)}개)"
        )
    if snapshot.empty:
        raise HandoffContractError("KOSPI snapshot이 비어 있습니다.")
    return snapshot


def build_kospi_history(
    active: pd.DataFrame,
    delisted: pd.DataFrame,
    *,
    start: str,
    end: str,
    processed_dir: str | Path,
) -> pd.DataFrame:
    """Reconstruct each KOSPI common stock's listing interval over a period."""
    start_date, end_date = pd.Timestamp(start).normalize(), pd.Timestamp(end).normalize()
    if start_date > end_date:
        raise HandoffContractError("history start must not be after end")
    active_required = {"Code", "Name", "Market", "ListingDate"}
    delisted_required = {
        "Symbol", "Name", "Market", "SecuGroup", "ListingDate", "DelistingDate"
    }
    if missing := sorted(active_required - set(active.columns)):
        raise HandoffContractError(f"KOSPI-DESC 필수 컬럼 누락: {missing}")
    if missing := sorted(delisted_required - set(delisted.columns)):
        raise HandoffContractError(f"KRX-DELISTING 필수 컬럼 누락: {missing}")

    active = active.loc[active.Market.eq("KOSPI")].copy()
    active["ListingDate"] = pd.to_datetime(active.ListingDate, errors="coerce")
    if active.ListingDate.isna().any():
        raise HandoffContractError("KOSPI-DESC에 ListingDate가 없는 종목이 있습니다.")
    active["Code"] = _codes(active.Code)
    active["DelistingDate"] = pd.NaT
    active["Source"] = "KOSPI-DESC"

    delisted = delisted.loc[
        delisted.Market.eq("KOSPI") & delisted.SecuGroup.eq("주권")
    ].copy()
    delisted["ListingDate"] = pd.to_datetime(delisted.ListingDate, errors="coerce")
    delisted["DelistingDate"] = pd.to_datetime(delisted.DelistingDate, errors="coerce")
    if delisted[["ListingDate", "DelistingDate"]].isna().any().any():
        raise HandoffContractError("KRX-DELISTING에 ListingDate/DelistingDate가 없는 종목이 있습니다.")
    delisted["Code"] = _codes(delisted.Symbol)
    delisted["Source"] = "KRX-DELISTING"

    columns = ["Code", "Name", "ListingDate", "DelistingDate", "Source"]
    history = pd.concat([active[columns], delisted[columns]], ignore_index=True)
    history = history.loc[
        history.ListingDate.le(end_date)
        & (history.DelistingDate.isna() | history.DelistingDate.gt(start_date))
    ].drop_duplicates(["Code", "ListingDate", "DelistingDate"])
    history = history.sort_values(["Code", "ListingDate"], kind="stable").reset_index(drop=True)
    if history.empty:
        raise HandoffContractError("요청 기간에 해당하는 KOSPI 종목 이력이 없습니다.")

    previous_end = history.groupby("Code").DelistingDate.shift()
    previous_start = history.groupby("Code").ListingDate.shift()
    overlap = previous_start.notna() & (
        previous_end.isna() | history.ListingDate.lt(previous_end)
    )
    if overlap.any():
        raise HandoffContractError(
            f"종목코드 상장 이력이 겹칩니다: {history.loc[overlap, 'Code'].head().tolist()}"
        )

    processed_codes = {path.stem.upper() for path in Path(processed_dir).glob("*.parquet")}
    missing_processed = sorted(set(history.Code) - processed_codes)
    if missing_processed:
        raise HandoffContractError(
            "KOSPI 이력에 대응하는 processed 파일이 없습니다: "
            f"{missing_processed[:20]} (총 {len(missing_processed)}개)"
        )
    return history


def main() -> None:
    parser = argparse.ArgumentParser(
        description="학습 종료일 기준 KOSPI 전 주권 universe.csv를 생성합니다."
    )
    parser.add_argument("--cutoff", default="2024-12-30")
    parser.add_argument("--history-start")
    parser.add_argument("--history-end")
    parser.add_argument("--processed-dir", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    if bool(args.history_start) != bool(args.history_end):
        parser.error("--history-start and --history-end must be used together")
    active, delisted = fetch_listing_inputs(args.history_start)
    if args.history_start:
        snapshot = build_kospi_history(
            active, delisted, start=args.history_start, end=args.history_end,
            processed_dir=args.processed_dir,
        )
    else:
        snapshot = build_kospi_snapshot(
            active, delisted, cutoff=args.cutoff, processed_dir=args.processed_dir
        )
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists():
        raise FileExistsError(f"기존 universe를 덮어쓰지 않습니다: {output}")
    snapshot.to_csv(output, index=False, date_format="%Y-%m-%d", encoding="utf-8")
    print(f"KOSPI universe: {len(snapshot)}개 종목 이력 -> {output.resolve()}")


if __name__ == "__main__":
    main()
