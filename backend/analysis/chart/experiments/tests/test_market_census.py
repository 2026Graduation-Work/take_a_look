import json
from collections import defaultdict
from datetime import date
from unittest.mock import Mock

import pandas as pd
from experiments.dataset.census_actions import _collect_notices, main
from shared.data.disclosures import Evidence
from shared.data.kind_market import KindUnavailable, MarketFiling
from shared.data.market_notices import SecurityKey, normal_company


def test_fnf_holdings_disclosure_scope_excludes_spin_off_with_same_name():
    holding = SecurityKey("007700", "KR7007700008", "1984-10-04", None, "KOSPI", "common")
    aliases = {holding: {normal_company(name) for name in ("F&F", "F&F 홀딩스")}}
    source = Evidence("a" * 64, "b" * 64)
    filings = [MarketFiling(accession, date(2021, 5, day), title, source, company=name,
                            company_id=issuer, submitter="유가증권시장본부")
               for accession, day, name, issuer, title in (
        ("20210517001277", 17, "F&F 홀딩스", "00770", "상장안내(회사분할(존속)에 따른 자본감소 및 상호변경)"),
        ("20210518000357", 18, "F&F", "38322", "재상장(주식회사 에프앤에프, 상장일 2021.05.21)"),
        ("20210520000242", 20, "F&F", "38322", "회사분할로 인한 재상장 기준가격결정방법 안내(분할신설법인)"),
        ("20210520000243", 20, "F&F 홀딩스", "00770", "회사분할로 인한 변경상장 기준가격결정방법 안내(분할존속법인)"),
    )]
    client = Mock()
    client.document.side_effect = KindUnavailable("outside this test's document cache")

    _, _, _, gaps, unattributed, _, selected, _ = _collect_notices(
        client, filings, aliases, defaultdict(tuple), anchors={}, spac_keys=set(), bounded=False,
    )

    attempted = [call.args[0].accession for call in client.document.call_args_list]
    assert attempted == ["20210517001277", "20210520000243"]
    assert selected == 2 and gaps[holding] == set(attempted)
    assert not unattributed


def test_census_never_compares_across_a_missing_security_session(tmp_path, capsys):
    days = tmp_path / "days"
    days.mkdir()
    dates = pd.date_range("2021-07-20", "2021-07-22")
    for day, close in zip(dates, [33_600, None, 15_050], strict=True):
        prices = [{
            "Date": day, "Code": code, "RawOpen": price, "RawHigh": price,
            "RawLow": price, "RawClose": price, "RawChange": change, "RawVolume": 100, "Amount": price * 100,
            "ListedShares": 4_765_650, "ISU_ABBRV": name, "MKT_NM": market, "SECT_TP_NM": "",
        } for code, name, market, price, change in (
            ("010140", "삼성중공업", "KOSPI", 6300, 0),
            ("104620", "노랑풍선", "KOSDAQ", close, 3450 if day == dates[-1] else 0),
        ) if price is not None]
        pd.DataFrame(prices).to_parquet(days / f"{day:%Y-%m-%d}.parquet", index=False)

    active, delisted = tmp_path / "active.parquet", tmp_path / "delisted.parquet"
    pd.DataFrame([
        ("010140", "KR7010140002", "삼성중공업", "삼성중공업", "KOSPI", "주권", "1994/01/28", "보통주"),
        ("104620", "KR7104620000", "노랑풍선", "노랑풍선", "KOSDAQ", "주권", "2019/01/30", "보통주"),
    ], columns=["ISU_SRT_CD", "ISU_CD", "ISU_NM", "ISU_ABBRV", "MKT_TP_NM",
                "SECUGRP_NM", "LIST_DD", "KIND_STKCERT_TP_NM"]).to_parquet(active, index=False)
    pd.DataFrame(columns=[
        "Symbol", "ISIN", "Name", "Market", "SecuGroup", "ListingDate", "DelistingDate", "KIND_STKCERT_TP_NM",
    ]).to_parquet(delisted, index=False)

    output = tmp_path / "output"
    main(["--start", "2021-07-20", "--end", "2021-07-22",
          "--published-start", "2021-07-19", "--published-end", "2021-07-23",
          "--krx-days", str(days), "--active-master", str(active), "--delisted-master", str(delisted),
          "--kind-root", str(tmp_path / "kind"), "--output", str(output), "--preview"])
    report = json.loads(capsys.readouterr().out)
    coverage = json.loads((output / "coverage.json").read_text())
    assert report["failed_windows"] == report["failed_codes"] == 1
    assert report["kind_http_calls_this_run"] == 0
    assert pd.read_csv(output / "candidates.csv").empty
    assert coverage["unassigned_market_observations"][0]["Code"] == "104620"
    assert any(row["Code"] == "104620" and "2021-07-21" in row["Reason"] for row in coverage["failures"] if "Code" in row)
    missing, = [window for window in coverage["windows"] if window["Code"] == "104620"]
    assert missing["expected_sessions"] == 3 and missing["price_rows"] == 2
    assert not missing["complete"] and missing["raw_sha256"] is None
    intact, = [window for window in coverage["windows"] if window["Code"] == "010140"]
    assert intact["raw_sha256"] and intact["price_rows"] == intact["expected_sessions"] == 3
