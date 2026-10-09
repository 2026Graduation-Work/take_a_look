from pathlib import Path
from types import ModuleType
from urllib.error import HTTPError

import pandas as pd
import pytest
from experiments.handoff.build_kospi_universe import (
    build_kospi_history,
    build_kospi_snapshot,
    fetch_listing_inputs,
)
from experiments.handoff.package_processed import HandoffContractError


def _frames() -> tuple[pd.DataFrame, pd.DataFrame]:
    active = pd.DataFrame(
        [
            {"Code": "5930", "Name": "기존", "Market": "KOSPI", "ListingDate": "2000-01-01"},
            {"Code": "123456", "Name": "신규", "Market": "KOSPI", "ListingDate": "2025-01-02"},
            {"Code": "654321", "Name": "코스닥", "Market": "KOSDAQ", "ListingDate": "2000-01-01"},
        ]
    )
    delisted = pd.DataFrame(
        [
            {
                "Symbol": "45014k",
                "Name": "상폐예정",
                "Market": "KOSPI",
                "SecuGroup": "주권",
                "ListingDate": "2023-01-01",
                "DelistingDate": "2025-02-01",
            },
            {
                "Symbol": "777777",
                "Name": "펀드",
                "Market": "KOSPI",
                "SecuGroup": "수익증권",
                "ListingDate": "2020-01-01",
                "DelistingDate": "2025-02-01",
            },
        ]
    )
    return active, delisted


def test_build_snapshot_keeps_cutoff_equities_and_post_cutoff_delistings(
    tmp_path: Path,
) -> None:
    for code in ("005930", "45014K"):
        (tmp_path / f"{code}.parquet").touch()
    active, delisted = _frames()

    snapshot = build_kospi_snapshot(active, delisted, cutoff="2024-12-30", processed_dir=tmp_path)

    assert snapshot["Code"].tolist() == ["005930", "45014K"]
    assert snapshot["Source"].tolist() == ["KOSPI-DESC", "KRX-DELISTING"]


def test_build_snapshot_rejects_missing_processed_file(tmp_path: Path) -> None:
    active, delisted = _frames()
    with pytest.raises(HandoffContractError, match="processed 파일이 없습니다"):
        build_kospi_snapshot(active, delisted, cutoff="2024-12-30", processed_dir=tmp_path)


def test_build_history_keeps_active_intervals_and_excludes_other_markets(tmp_path: Path) -> None:
    for code in ("005930", "123456", "45014K"):
        (tmp_path / f"{code}.parquet").touch()
    active, delisted = _frames()
    history = build_kospi_history(
        active, delisted, start="2024-01-01", end="2025-12-31", processed_dir=tmp_path
    )
    assert history.Code.tolist() == ["005930", "123456", "45014K"]
    assert history.iloc[0].ListingDate == pd.Timestamp("2000-01-01")
    assert history.iloc[1].ListingDate == pd.Timestamp("2025-01-02")
    assert history.iloc[2].DelistingDate == pd.Timestamp("2025-02-01")


def test_listing_cache_404_falls_back_to_direct_krx_readers(monkeypatch: pytest.MonkeyPatch) -> None:
    fdr = ModuleType("FinanceDataReader")
    fdr.__path__ = []
    fdr.StockListing = lambda *args: (_ for _ in ()).throw(
        HTTPError("https://example.test/listing.csv", 404, "missing", None, None)
    )
    krx = ModuleType("FinanceDataReader.krx")
    krx.__path__ = []
    listing = ModuleType("FinanceDataReader.krx.listing")
    calls = []

    class DirectActive:
        def __init__(self, market):
            calls.append(("active_init", market))

        def read(self):
            calls.append(("active_read",))
            return "active"

    class DirectDelisted:
        def __init__(self, market, start, end):
            calls.append(("delisted_init", market, start, end))

        def read(self):
            calls.append(("delisted_read",))
            return "delisted"

    listing.KrxStockListing = DirectActive
    listing.KrxDelisting = DirectDelisted
    monkeypatch.setitem(__import__("sys").modules, "FinanceDataReader", fdr)
    monkeypatch.setitem(__import__("sys").modules, "FinanceDataReader.krx", krx)
    monkeypatch.setitem(__import__("sys").modules, "FinanceDataReader.krx.listing", listing)

    assert fetch_listing_inputs("2016-01-01") == ("active", "delisted")
    assert ("delisted_init", "KRX-DELISTING", "2016-01-01", calls[-2][3]) in calls
