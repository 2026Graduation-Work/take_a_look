import gzip
import json
from collections import defaultdict
from datetime import date
from pathlib import Path
from unittest.mock import Mock

import pandas as pd
import pytest
from experiments.dataset.census_actions import _collect_notices, main
from experiments.dataset.freeze_resolution_snapshot import freeze_resolution_snapshot
from experiments.dataset.pipeline import write_review_queue
from shared.data.disclosures import Evidence
from shared.data.kind_market import DAILY_URL, KindMarket, KindUnavailable, MarketFiling
from shared.data.market_notices import SecurityKey, kind_topic, normal_company
from shared.data.market_resolutions import Resolution
from shared.data.resolution_snapshot import kind_document_url, read_resolution_snapshot


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


def test_merger_title_requires_an_implementation_notice_to_select_without_a_candidate():
    security = SecurityKey("373200", "KR7373200005", "2021-02-26", None, "KOSDAQ", "common")
    source = Evidence("a" * 64, "b" * 64)
    filings = [MarketFiling(accession, date.fromisoformat(published), title, source,
                            stock_code=security.code, company="하인크코리아", submitter="코스닥시장본부")
               for accession, published, title in (
        ("20150904000307", "2015-09-04", "주권매매거래정지(SPAC합병(예비심사청구대상))"),
        ("20151019000033", "2015-10-19", "조회공시요구(풍문또는보도)(회사합병추진보도)"),
        ("20220119000510", "2022-01-19", "추가상장(타법인흡수합병)"),
    )]
    client = Mock()
    client.document.side_effect = KindUnavailable("stop after selecting the official implementation")
    *_, selected, _ = _collect_notices(
        client, filings, {security: {"하인크코리아"}}, defaultdict(tuple),
        anchors={}, spac_keys={security}, bounded=True,
    )
    assert selected == 1
    assert client.document.call_args.args[0].accession == "20220119000510"


def test_market_inventory_distinguishes_resumption_price_method_from_a_bare_halt():
    proof = Evidence("a" * 64, "b" * 64)
    titles = [
        ("20170706000452", "기준가산정 등에 관한 안내(장기간매매정지)", "candidate"),
        ("20170706000452", "매매거래재개 기준가격 결정방법 안내", "candidate"),
        ("20160302000333", "주권매매거래정지기간변경(액면분할 주권 변경상장)", None),
        ("20151120000302", "주권매매거래정지해제(합병철회)", None),
    ]
    for accession, title, expected in titles:
        filing = MarketFiling(accession, date(2017, 7, 6), title, proof, submitter="코스닥시장본부")
        assert kind_topic(filing) == expected


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


def use_archived_kind_bodies(monkeypatch, filings, *, issuer, submitter):
    fixtures = Path(__file__).parents[2] / "shared/tests/fixtures/market_actions"
    sources = json.loads((fixtures / "sources.json").read_text())
    documents = {}
    for accession in filings.values():
        source = sources[accession]
        viewer, document, url = kind_document_url(accession), source["document_no"], source["body_url"]
        documents[viewer] = (
            f'<input name="acptNo" id="acptNo" value="{accession}">'
            f'<select id="mainDoc"><option value="{document}|Y" selected></option></select>'
        ).encode()
        documents[viewer.split("?")[0] + f"?method=searchContents&docNo={document}"] = (
            f"parent.setPath('', '{url}')"
        ).encode()
        documents[url] = gzip.decompress((fixtures / f"{accession}.html.gz").read_bytes())

    def archived_get(self, url, *, form=None, referer=None, parse=None, **kwargs):
        if url == DAILY_URL:
            accession = filings.get(form["selDate"])
            rows = (f"<tr><td>12:00</td><td><a onclick=\"companysummary_open('{issuer}')\">{sources[accession]['company']}</a></td>"
                    f"<td><a onclick=\"openDisclsViewer('{accession}','')\">{sources[accession]['title']}</a></td>"
                    f"<td>{submitter}</td><td></td></tr>" if accession else "조회된 결과값이 없습니다.")
            body = f"<table>{rows}</table>전체 <em>{int(bool(accession))}</em>건 : <strong>1</strong>/1".encode()
        else:
            body = documents[url]
        response = self._store({"url": url, "form": form, "referer": referer}, body, "utf-8", None, "fixture")
        return parse(response) if parse else response

    monkeypatch.setattr(KindMarket, "_get", archived_get)


@pytest.mark.parametrize("base_price", [100, 125])
def test_census_freezes_merger_review_with_or_without_a_raw_observation(tmp_path, monkeypatch, capsys, base_price):
    use_archived_kind_bodies(monkeypatch, {"2022-01-17": "20220117000675", "2022-01-19": "20220119000510"},
                            issuer="37320", submitter="코스닥시장본부")
    days, cache, output = (tmp_path / name for name in ("days", "kind", "output"))
    days.mkdir()
    for day in pd.date_range("2022-01-19", "2022-01-20"):
        change = 100 - base_price if day.day == 20 else 0
        pd.DataFrame([{"Date": day, "Code": "373200", "RawOpen": 100, "RawHigh": 100, "RawLow": 100,
                       "RawClose": 100, "RawChange": change, "RawVolume": 100, "Amount": 10_000,
                       "ListedShares": 3_520_000, "ISU_ABBRV": "하인크코리아", "MKT_NM": "KOSDAQ",
                       "SECT_TP_NM": "SPAC"}]).to_parquet(days / f"{day:%Y-%m-%d}.parquet", index=False)
    active, delisted = tmp_path / "active.parquet", tmp_path / "delisted.parquet"
    pd.DataFrame([("373200", "KR7373200005", "하인크코리아", "하인크코리아", "KOSDAQ", "주권", "2021/02/26", "보통주")],
                 columns=["ISU_SRT_CD", "ISU_CD", "ISU_NM", "ISU_ABBRV", "MKT_TP_NM",
                          "SECUGRP_NM", "LIST_DD", "KIND_STKCERT_TP_NM"]).to_parquet(active, index=False)
    pd.DataFrame(columns=["Symbol", "ISIN", "Name", "Market", "SecuGroup", "ListingDate",
                          "DelistingDate", "KIND_STKCERT_TP_NM"]).to_parquet(delisted, index=False)

    main(["--start", "2022-01-19", "--end", "2022-01-20", "--published-start", "2022-01-12",
          "--published-end", "2022-01-23", "--krx-days", str(days), "--active-master", str(active),
          "--delisted-master", str(delisted), "--kind-root", str(cache), "--output", str(output), "--code", "373200"])
    report = json.loads(capsys.readouterr().out)
    snapshot_path = freeze_resolution_snapshot(output, tmp_path / "official_actions", krx_days=days,
                                               active_master=active, delisted_master=delisted, evidence_archives=[cache])
    snapshot = read_resolution_snapshot(snapshot_path, verify_archive=True)
    queue = tmp_path / "review_queue.csv"
    assert write_review_queue(snapshot, queue, securities=snapshot.ledgers)["rows"] == 1
    row = pd.read_csv(queue, dtype={"Code": str}).iloc[0]
    assert (row.Code, row.Date, row.PrevClose, row.BasePrice, row.SharesBefore, row.SharesAfter) == (
        "373200", "2022-01-20", 100, base_price, 3_520_000, 3_520_000)
    assert kind_document_url("20220119000510") in row.NearbyNotices
    assert report["market_observations_before_identity"] == report["market_candidates_with_market_observation"] == int(base_price != 100)
    assert report["review_candidates_without_market_observation"] == int(base_price == 100)
    assert report["market_candidates"] == 1 and report["resolutions_without_price_observation"] == 0


def test_census_freezes_both_share_classes_from_one_official_merger_notice(tmp_path, monkeypatch):
    accession = "20170112000046"
    use_archived_kind_bodies(monkeypatch, {"2017-01-12": accession}, issuer="05191", submitter="유가증권시장본부")
    days, cache, output = (tmp_path / name for name in ("days", "kind", "output"))
    days.mkdir()
    columns = ["Code", "ISU_ABBRV", "RawOpen", "RawHigh", "RawLow", "RawClose", "RawChange", "RawVolume",
               "Amount", "ListedShares"]
    for day, rows in (
        ("2017-01-16", [("051910", "LG화학", 282_000, 283_500, 278_000, 278_500, -4_500, 198_568, 55_506_248_500, 66_271_100),
                        ("051915", "LG화학우", 190_000, 191_500, 187_000, 189_500, -500, 10_813, 2_038_075_500, 7_628_921)]),
        ("2017-01-17", [("051910", "LG화학", 278_000, 284_000, 276_000, 278_500, 0, 218_884, 61_049_828_500, 70_592_343),
                        ("051915", "LG화학우", 188_000, 190_000, 185_000, 187_000, -2_500, 7_501, 1_398_591_000, 7_688_800)]),
    ):
        dates = pd.DatetimeIndex([day] * len(rows), dtype="datetime64[ns]")
        pd.DataFrame(rows, columns=columns).assign(Date=dates, MKT_NM="KOSPI", SECT_TP_NM="").to_parquet(
            days / f"{day}.parquet", index=False)
    active, delisted = tmp_path / "active.parquet", tmp_path / "delisted.parquet"
    pd.DataFrame([
        ("051910", "KR7051910008", "LG화학", "LG화학", "KOSPI", "주권", "2001/04/25", "보통주"),
        ("051915", "KR7051911006", "LG화학1우선주", "LG화학우", "KOSPI", "주권", "2001/04/25", "1우선주"),
    ], columns=["ISU_SRT_CD", "ISU_CD", "ISU_NM", "ISU_ABBRV", "MKT_TP_NM", "SECUGRP_NM", "LIST_DD",
                "KIND_STKCERT_TP_NM"]).to_parquet(active, index=False)
    pd.DataFrame(columns=["Symbol", "ISIN", "Name", "Market", "SecuGroup", "ListingDate",
                          "DelistingDate", "KIND_STKCERT_TP_NM"]).to_parquet(delisted, index=False)

    main(["--start", "2017-01-16", "--end", "2017-01-17", "--published-start", "2017-01-09",
          "--published-end", "2017-01-20", "--krx-days", str(days), "--active-master", str(active),
          "--delisted-master", str(delisted), "--kind-root", str(cache), "--output", str(output)])
    path = freeze_resolution_snapshot(output, tmp_path / "official_actions", krx_days=days,
                                       active_master=active, delisted_master=delisted, evidence_archives=[cache])
    snapshot = read_resolution_snapshot(path, verify_archive=True)
    notices = pd.read_csv(output / "notices.csv", dtype={"Code": str, "AcptNo": str}).sort_values("Code")
    assert list(notices[["AcptNo", "Code", "Section", "AddedShares"]].itertuples(index=False, name=None)) == [
        (accession, "051910", 1, 4_321_243), (accession, "051915", 2, 59_879),
    ]
    assert {key.code for key in snapshot.ledgers} == {"051910", "051915"}
    for ledger in snapshot.ledgers.values():
        assert ledger.candidates == ()
        event, = ledger.resolutions
        assert (event.date, event.kind, event.reason, event.review) == (
            "2017-01-17", Resolution.SEGMENT_BREAK, "official_merger", False,
        )
        assert {proof.accession for proof in event.evidence} == {accession}
