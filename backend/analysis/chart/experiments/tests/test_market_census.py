import json

import pandas as pd
from experiments.dataset.census_actions import main


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
