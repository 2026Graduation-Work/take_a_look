import gzip
import hashlib
import json
from collections import defaultdict
from datetime import date, timedelta
from fractions import Fraction
from pathlib import Path
from unittest.mock import MagicMock, Mock

import pandas as pd
import pytest
from experiments.dataset.census_actions import _collect_notices, main
from experiments.dataset.freeze_resolution_snapshot import freeze_resolution_snapshot
from experiments.dataset.pipeline import training_metadata, write_review_queue
from shared.data.disclosures import DisclosureError, Evidence
from shared.data.kind_market import (
    DAILY_URL,
    KIND_VIEWER,
    KindMarket,
    KindUnavailable,
    MarketFiling,
)
from shared.data.market_notices import SecurityKey, kind_topic, normal_company
from shared.data.market_resolutions import Resolution
from shared.data.resolution_snapshot import kind_document_url, read_resolution_snapshot
from shared.data.segmented_prices import adjust_training_window
from shared.io import sha256


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

    _, _, _, gaps, unattributed, _, _, _, selected, _ = _collect_notices(
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
    accessions = [accession for rows in filings.values() for accession in rows]
    flags = {sources[accession]["document_no"]: "Y" if sources[accession]["final"] else "N" for accession in accessions}
    for accession in accessions:
        source = sources[accession]
        viewer, document, url = kind_document_url(accession), source["document_no"], source["body_url"]
        options = "".join(f'<option value="{number}|{flags.get(number, "N")}"'
                          f'{" selected" if number == document else ""}></option>' for number in source["family"])
        documents[viewer] = (f'<input name="acptNo" id="acptNo" value="{accession}">'
                             f'<select id="mainDoc">{options}</select>').encode()
        documents[viewer.split("?")[0] + f"?method=searchContents&docNo={document}"] = (
            f"parent.setPath('', '{url}')"
        ).encode()
        body = gzip.decompress((fixtures / f"{accession}.html.gz").read_bytes())
        assert hashlib.sha256(body).hexdigest() == source["sha256"]
        documents[url] = body

    def archived_get(self, url, *, form=None, referer=None, parse=None, **kwargs):
        if url == DAILY_URL:
            accessions = filings.get(form["selDate"], ())
            rows = "".join(
                f"<tr><td>12:00</td><td><a onclick=\"companysummary_open('{issuer}')\">{sources[accession]['company']}</a></td>"
                f"<td><a onclick=\"openDisclsViewer('{accession}','')\">{sources[accession]['title']}</a></td>"
                f"<td>{submitter}</td><td></td></tr>" for accession in accessions
            ) or "조회된 결과값이 없습니다."
            body = f"<table>{rows}</table>전체 <em>{len(accessions)}</em>건 : <strong>1</strong>/1".encode()
        else:
            body = documents[url]
        response = self._store({"url": url, "form": form, "referer": referer}, body, "utf-8", None, "fixture")
        return parse(response) if parse else response

    monkeypatch.setattr(KindMarket, "_get", archived_get)


@pytest.mark.parametrize("base_price", [100, 125])
def test_census_freezes_merger_review_with_or_without_a_raw_observation(tmp_path, monkeypatch, capsys, base_price):
    use_archived_kind_bodies(monkeypatch, {"2022-01-17": ("20220117000675",), "2022-01-19": ("20220119000510",)},
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
    use_archived_kind_bodies(monkeypatch, {"2017-01-12": (accession,)}, issuer="05191", submitter="유가증권시장본부")
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


def test_census_keeps_lotte_survivor_and_preferred_auctions_bound_to_their_listings(tmp_path, monkeypatch):
    use_archived_kind_bodies(monkeypatch, {
        "2017-10-25": ("20171025000180", "20171025000484"),
        "2017-10-27": ("20171027000317", "20171027000382"),
    }, issuer="00499", submitter="유가증권시장본부")
    days, cache, output = (tmp_path / name for name in ("days", "kind", "output"))
    days.mkdir()
    columns = ["Code", "ISU_ABBRV", "RawOpen", "RawHigh", "RawLow", "RawClose", "RawChange", "RawVolume",
               "Amount", "ListedShares"]
    for day, rows in (
        ("2017-10-27", [("004990", "롯데제과", 0, 0, 0, 166_000, 0, 0, 0, 14_214_000)]),
        ("2017-10-30", [("004990", "롯데지주", 64_000, 82_000, 58_100, 70_400, 6400, 6_470_827, 451_025_934_200, 73_683_000),
                        ("00499K", "롯데지주우", 68_000, 88_400, 68_000, 88_400, 20_400, 268_264, 22_862_661_200, 987_623),
                        ("280360", "롯데제과", 225_500, 225_500, 185_500, 190_000, -35_500, 173_576, 33_853_710_000, 4_209_102)]),
    ):
        dates = pd.DatetimeIndex([day] * len(rows), dtype="datetime64[ns]")
        pd.DataFrame(rows, columns=columns).assign(Date=dates, MKT_NM="KOSPI", SECT_TP_NM="").to_parquet(
            days / f"{day}.parquet", index=False)
    active, delisted = tmp_path / "active.parquet", tmp_path / "delisted.parquet"
    pd.DataFrame([
        ("004990", "KR7004990008", "롯데지주보통주", "롯데지주", "KOSPI", "주권", "1974/02/16", "보통주"),
        ("00499K", "KR700499K014", "롯데지주1우선주", "롯데지주우", "KOSPI", "주권", "2017/10/30", "구형우선주"),
        ("280360", "KR7280360009", "롯데웰푸드보통주", "롯데웰푸드", "KOSPI", "주권", "2017/10/30", "보통주"),
    ], columns=["ISU_SRT_CD", "ISU_CD", "ISU_NM", "ISU_ABBRV", "MKT_TP_NM", "SECUGRP_NM", "LIST_DD",
                "KIND_STKCERT_TP_NM"]).to_parquet(active, index=False)
    pd.DataFrame(columns=["Symbol", "ISIN", "Name", "Market", "SecuGroup", "ListingDate",
                          "DelistingDate", "KIND_STKCERT_TP_NM"]).to_parquet(delisted, index=False)

    main(["--start", "2017-10-27", "--end", "2017-10-30", "--published-start", "2017-10-20",
          "--published-end", "2017-11-02", "--krx-days", str(days), "--active-master", str(active),
          "--delisted-master", str(delisted), "--kind-root", str(cache), "--output", str(output)])
    path = freeze_resolution_snapshot(output, tmp_path / "official_actions", krx_days=days,
                                       active_master=active, delisted_master=delisted, evidence_archives=[cache])
    snapshot = read_resolution_snapshot(path, verify_archive=True)
    notices = pd.read_csv(output / "notices.csv", dtype={"Code": str, "AcptNo": str}).set_index("AcptNo")
    survivor = notices.loc["20171027000382"]
    assert (survivor.Code, survivor.EvaluationPrice, survivor.Low, survivor.High) == ("004990", 47_100, 23_550, 94_200)
    preferred = notices.loc["20171027000317"]
    assert (preferred.Code, preferred.EvaluationPrice, preferred.Low, preferred.High) == ("00499K", 34_000, 17_000, 68_000)
    listing = notices.loc["20171025000484"]
    assert (listing.Code, listing.ShareClass, listing.SharesAfter) == ("00499K", "preferred", 987_623)
    ledgers = {key.code: ledger for key, ledger in snapshot.ledgers.items()}
    event, = ledgers["004990"].resolutions
    assert (event.date, event.kind, event.reason, event.price_factor, event.volume_factor) == (
        "2017-10-30", Resolution.SEGMENT_BREAK, "official_division", None, None,
    )
    assert ledgers["004990"].candidates[0].base_price == 64_000
    assert ledgers["00499K"].candidates == ledgers["280360"].resolutions == ()
    assert all(row.price_factor is None and row.volume_factor is None for row in ledgers["00499K"].resolutions)


def freeze_kind_case(tmp_path, raw, *, active, delisted=(), budget=0, preview=False, codes=(), published_start=None,
                     spac_before=None):
    days, cache, output = (tmp_path / name for name in ("days", "kind", "output"))
    days.mkdir()
    columns = ["Date", "Code", "ISU_ABBRV", "MKT_NM", "RawOpen", "RawHigh", "RawLow", "RawClose", "RawChange",
               "RawVolume", "Amount", "ListedShares"]
    bars = pd.DataFrame(raw, columns=columns).assign(SECT_TP_NM="")
    bars["Date"] = pd.DatetimeIndex(bars.Date, dtype="datetime64[ns]")
    if spac_before:
        bars.loc[bars.Date.lt(pd.Timestamp(spac_before)), "SECT_TP_NM"] = "기업인수목적회사"
    for day, rows in bars.groupby("Date"):
        rows.to_parquet(days / f"{day:%Y-%m-%d}.parquet", index=False)
    active_path, delisted_path = tmp_path / "active.parquet", tmp_path / "delisted.parquet"
    pd.DataFrame(active, columns=["ISU_SRT_CD", "ISU_CD", "ISU_NM", "ISU_ABBRV", "MKT_TP_NM", "SECUGRP_NM", "LIST_DD",
                                  "KIND_STKCERT_TP_NM"]).to_parquet(active_path, index=False)
    pd.DataFrame(delisted, columns=["Symbol", "ISIN", "Name", "Market", "SecuGroup", "ListingDate", "DelistingDate",
                                    "KIND_STKCERT_TP_NM"]).to_parquet(delisted_path, index=False)
    start, end = bars.Date.min().date(), bars.Date.max().date()
    main(["--start", str(start), "--end", str(end), "--published-start", str(published_start or start - timedelta(days=7)),
          "--published-end", str(end + timedelta(days=3)), "--krx-days", str(days), "--active-master", str(active_path),
          "--delisted-master", str(delisted_path), "--kind-root", str(cache), "--output", str(output),
          "--request-budget", str(budget), *(["--preview"] if preview else []),
          *(arg for code in codes for arg in ("--code", code))])
    path = freeze_resolution_snapshot(output, tmp_path / "official_actions", krx_days=days,
                                       active_master=active_path, delisted_master=delisted_path, evidence_archives=[cache])
    notices = pd.read_csv(output / "notices.csv", dtype={"Code": str, "AcptNo": str}).set_index("AcptNo")
    return read_resolution_snapshot(path, verify_archive=True), notices


@pytest.mark.parametrize("with_merger", [False, True])
def test_spac_rename_correction_closes_only_the_name_change(tmp_path, monkeypatch, with_merger):
    original, final, merger = "20210722000431", "20210722000497", "20210726000260"
    filings = {"2021-07-22": (original, final)}
    if with_merger:
        filings["2021-07-26"] = (merger,)
    use_archived_kind_bodies(monkeypatch, filings, issuer="35319", submitter="코스닥시장본부")
    snapshot, notices = freeze_kind_case(tmp_path, [
        ("2021-07-26", "353190", "엔에이치스팩16호", "KOSDAQ", 3070, 3070, 2955, 2995, -5, 129400, 386219735, 4310000),
        ("2021-07-27", "353190", "휴럼", "KOSDAQ", 2900, 2900, 2580, 2655, -340, 2218058, 5906731610, 27682521),
    ], active=[("353190", "KR7353190002", "휴럼", "휴럼", "KOSDAQ", "주권", "2020/06/17", "보통주")],
        spac_before="2021-07-27")
    assert notices.loc[final, "Kind"] == "rename"
    family, = snapshot.coverage["kind_final_families"]
    assert (family["AcptNo"], family["FinalAcptNo"]) == (original, final)
    assert {item["Code"] for item in family["ClosedWindows"]} == {"353190"}
    assert len(family["Evidence"]) == 7 and len(family["OriginalNoticeEvidence"]) == 2
    ledger, = snapshot.ledgers.values()
    if with_merger:
        event, = ledger.resolutions
        assert (event.date, event.kind, event.price_factor, event.volume_factor) == (
            "2021-07-27", Resolution.SPAC_PREMERGER, None, None)
        assert merger in {item.accession for item in event.evidence}
    else:
        assert not ledger.resolutions
        return

    output = tmp_path / "output"
    coverage_path, manifest_path = output / "coverage.json", output / "manifest.json"
    manifest = json.loads(manifest_path.read_bytes())
    for index, (rows, reason) in enumerate([
        ([], f"Missing official structural notice evidence: {original}"),
        ([{**family, "OriginalNoticeEvidence": family["Evidence"][5:]}], "body receipt differs|viewer differs"),
    ]):
        coverage_path.write_text(json.dumps({**snapshot.coverage, "kind_final_families": rows}))
        manifest["superseded_documents"] = len(rows)
        manifest["table_sha256"]["coverage"] = sha256(coverage_path)
        manifest_path.write_text(json.dumps(manifest))
        with pytest.raises(DisclosureError, match=reason):
            freeze_resolution_snapshot(output, tmp_path / f"tampered_role_{index}", krx_days=tmp_path / "days",
                                       active_master=tmp_path / "active.parquet", delisted_master=tmp_path / "delisted.parquet",
                                       evidence_archives=[tmp_path / "kind"])


@pytest.mark.parametrize("accession,code,isin,name,old_listing,day,base,raw", [
    ("20240610000605", "323350", "KR7323350009", "다원넥스뷰", "2019/05/21", "2024-06-11", 13_850, [
        ("2024-06-10", "323350", "다원넥스뷰", "KONEX", 15550, 15550, 14500, 14900, 410, 3685, 54452920, 6312500),
        ("2024-06-11", "323350", "다원넥스뷰", "KOSDAQ", 14850, 15490, 10850, 11000, -2850, 3183508, 39389431040, 7596111),
    ]),
    ("20251226000658", "012210", "KR7012210001", "삼미금속", "2023/05/16", "2025-12-29", 10_180, [
        ("2025-12-26", "012210", "삼미금속", "KONEX", 15980, 15980, 14610, 15980, 2080, 9667, 154272470, 19766609),
        ("2025-12-29", "012210", "삼미금속", "KOSDAQ", 13230, 13230, 13230, 13230, 3050, 1554328, 20563759440, 22192012),
    ]),
])
def test_fixed_new_listing_reference_keeps_same_code_old_and_new_markets_separate(
    tmp_path, monkeypatch, accession, code, isin, name, old_listing, day, base, raw,
):
    publication = f"{accession[:4]}-{accession[4:6]}-{accession[6:8]}"
    use_archived_kind_bodies(monkeypatch, {publication: (accession,)}, issuer=code[:5], submitter="코스닥시장본부")
    snapshot, notices = freeze_kind_case(
        tmp_path, raw, active=[(code, isin, name, name, "KOSDAQ", "주권", day.replace("-", "/"), "보통주")],
        delisted=[(code, isin, name, "KONEX", "주권", old_listing, day, "보통주")])
    reference = notices.loc[accession]
    assert (reference.Kind, reference.BasePrice, reference.Code) == ("listing_price", base, code)
    old, new = sorted(snapshot.ledgers, key=lambda key: key.listing)
    assert old.isin == new.isin == isin
    assert (old.market, old.delisting, new.market, new.listing) == ("KONEX", day, "KOSDAQ", day)
    assert (snapshot.segment_starts(old), snapshot.segment_starts(new)) == ([old.listing], [day])
    assert snapshot.ledgers[old].resolutions == ()
    event, = snapshot.ledgers[new].resolutions
    assert event.kind == Resolution.SEGMENT_BREAK and event.review and event.price_factor is event.volume_factor is None


def test_uncoded_auction_archive_checks_exact_companion_listing_and_rename(tmp_path, monkeypatch):
    auction, listing = "20180104000369", "20180102000170"
    use_archived_kind_bodies(monkeypatch, {"2018-01-02": (listing,), "2018-01-04": (auction,)},
                            issuer="00612", submitter="유가증권시장본부")
    snapshot, notices = freeze_kind_case(tmp_path, [
        ("2018-01-04", "006125", "SK케미칼우", "KOSPI", 0, 0, 0, 40500, 0, 0, 0, 2817125),
        ("2018-01-05", "006125", "SK디스커버리우", "KOSPI", 25000, 32500, 25000, 26250, 1250, 745279, 21803809600, 1358455),
    ], active=[("006125", "KR7006121008", "에스케이디스커버리1우선주", "SK디스커버리우", "KOSPI", "주권", "1989/11/24", "구형우선주")])
    assert (notices.loc[auction, "Code"], notices.loc[auction, "Section"]) == ("006125", 1)
    link = {"Auction": [auction, "99332", 1], "Witnesses": [[listing, "68151", 4], [listing, "68151", 2]]}
    assert snapshot.coverage["kind_auction_identity_links"] == [link]
    ledger, = snapshot.ledgers.values()
    assert ledger.resolutions[0].reason == "official_division"
    assert {item.accession for item in ledger.resolutions[0].evidence} == {auction, listing}

    output = tmp_path / "output"
    coverage_path, manifest_path = output / "coverage.json", output / "manifest.json"
    manifest = json.loads(manifest_path.read_bytes())
    for index, invalid in enumerate(([], [{**link, "Witnesses": [[listing, "68151", 4]]}])):
        coverage_path.write_text(json.dumps({**snapshot.coverage, "kind_auction_identity_links": invalid}))
        manifest["table_sha256"]["coverage"] = sha256(coverage_path)
        manifest_path.write_text(json.dumps(manifest))
        with pytest.raises(DisclosureError, match="auction identity links are missing or differ"):
            freeze_resolution_snapshot(output, tmp_path / f"invalid_identity_{index}", krx_days=tmp_path / "days",
                                       active_master=tmp_path / "active.parquet", delisted_master=tmp_path / "delisted.parquet",
                                       evidence_archives=[tmp_path / "kind"])


def test_uncoded_auction_before_price_capture_proves_only_identity(tmp_path, monkeypatch):
    auction, listing = "20151022000346", "20151020000053"
    use_archived_kind_bodies(monkeypatch, {"2015-10-20": (listing,), "2015-10-22": (auction,)},
                            issuer="01176", submitter="유가증권시장본부")
    snapshot, notices = freeze_kind_case(tmp_path, [
        ("2016-01-04", "011760", "현대상사", "KOSPI", 28950, 28950, 27450, 27500, -1100, 20875, 583572650, 13228966),
    ], active=[("011760", "KR7011760006", "현대코퍼레이션보통주", "현대코퍼레이션", "KOSPI", "주권", "1977/12/01", "보통주")],
        published_start="2015-10-20")
    assert notices.loc[auction, "AppliedDate"] == "2015-10-23"
    assert snapshot.coverage["kind_auction_identity_links"] == [
        {"Auction": [auction, "99332", 1], "Witnesses": [[listing, "68155", 1]]}]
    ledger, = snapshot.ledgers.values()
    assert ledger.candidates == ledger.resolutions == ()


def test_uncoded_new_listing_auction_uses_the_exact_preferred_section(tmp_path, monkeypatch):
    auction, listing = "20230130000673", "20230127000869"
    use_archived_kind_bodies(monkeypatch, {"2023-01-27": (listing,), "2023-01-30": (auction,)},
                            issuer="45014", submitter="유가증권시장본부")
    snapshot, notices = freeze_kind_case(tmp_path, [
        ("2023-01-31", "450140", "코오롱모빌리티그룹", "KOSPI", 3750, 4875, 3750, 4875, 1125, 12492132, 57562858300, 62777250),
        ("2023-01-31", "45014K", "코오롱모빌리티그룹우", "KOSPI", 7280, 9460, 7280, 9460, 2180, 98108, 907502860, 2456120),
    ], active=[], delisted=[
        ("450140", "KR7450140009", "코오롱모빌리티그룹", "KOSPI", "주권", "2023/01/31", "2026/01/07", "보통주"),
        ("45014K", "KR745014K018", "코오롱모빌리티그룹우", "KOSPI", "주권", "2023/01/31", "2026/01/07", "종류주권"),
    ])
    assert (notices.loc[auction, "Code"], notices.loc[auction, "ISIN"]) == ("45014K", "KR745014K018")
    assert snapshot.coverage["kind_auction_identity_links"] == [
        {"Auction": [auction, "99334", 1], "Witnesses": [[listing, "68156", 2]]}]


@pytest.mark.parametrize("original,final,common,preferred,active,raw", [
    ("20171121000053", "20171123000384", "005720", "005725", [
        ("005720", "KR7005720008", "넥센보통주", "넥센", "KOSPI", "주권", "1987/12/19", "보통주"),
        ("005725", "KR7005721006", "넥센1우선주", "넥센우", "KOSPI", "주권", "1989/09/23", "구형우선주"),
    ], [
        ("2017-11-23", "005720", "넥센", "KOSPI", 8090, 8090, 7990, 7990, -100, 23733, 190265690, 50880170),
        ("2017-11-24", "005720", "넥센", "KOSPI", 8050, 8050, 7800, 7830, -160, 74316, 585849820, 53543977),
        ("2017-11-23", "005725", "넥센우", "KOSPI", 5280, 5470, 5280, 5440, 90, 624, 3311410, 3600600),
        ("2017-11-24", "005725", "넥센우", "KOSPI", 5490, 5540, 5250, 5440, 0, 209, 1144440, 3600600),
    ]),
    ("20200413000258", "20200413000763", "145990", "145995", [
        ("145990", "KR7145990008", "삼양사보통주", "삼양사", "KOSPI", "주권", "2011/12/05", "보통주"),
        ("145995", "KR7145991006", "삼양사1우선주", "삼양사우", "KOSPI", "주권", "2011/12/05", "구형우선주"),
    ], [
        ("2020-04-13", "145990", "삼양사", "KOSPI", 35900, 36200, 35400, 35700, -50, 25832, 924849250, 10289803),
        ("2020-04-14", "145990", "삼양사", "KOSPI", 35700, 36150, 35300, 35950, 250, 25565, 916725800, 10313449),
        ("2020-04-13", "145995", "삼양사우", "KOSPI", 24000, 24700, 23900, 24000, -250, 1099, 26419200, 370070),
        ("2020-04-14", "145995", "삼양사우", "KOSPI", 24050, 25400, 24000, 24900, 900, 5568, 136678950, 370070),
    ]),
])
def test_census_freezes_issuer_merger_for_common_and_preferred(tmp_path, monkeypatch, capsys,
                                                       original, final, common, preferred, active, raw):
    filings = defaultdict(list)
    for accession in (original, final):
        day = f"{accession[:4]}-{accession[4:6]}-{accession[6:8]}"
        filings[day].append(accession)
    use_archived_kind_bodies(monkeypatch, filings, issuer=common[:5], submitter="유가증권시장본부")
    codes = (common, preferred) if common == "005720" else ()
    snapshot, notices = freeze_kind_case(tmp_path, raw, active=active, codes=codes)
    assert list(notices.index) == [final] and notices.loc[final, "Code"] == common
    family, = snapshot.coverage["kind_final_families"]
    assert (family["AcptNo"], family["FinalAcptNo"]) == (original, final)
    assert {item["Code"] for item in family["ClosedWindows"]} == {common, preferred}

    start, end = raw[0][0], raw[1][0]
    days = pd.DatetimeIndex([start, end])
    if not codes:
        selected = training_metadata(snapshot, {"tickers": [preferred], "markets": ["KOSPI"], "include_delisted": False},
                                     {"trading_days": [start, end]})
        assert selected.Code.tolist() == [preferred]
    for key, ledger in snapshot.ledgers.items():
        event, = ledger.resolutions
        reason = "official_merger" if key.code == common else "official_issuer_merger"
        assert not ledger.candidates
        assert (event.date, event.kind, event.reason, event.review, event.price_factor, event.volume_factor) == (
            end, Resolution.SEGMENT_BREAK, reason, False, None, None)
        assert {item.accession for item in event.evidence} == {final}
        bars = pd.concat([pd.read_parquet(tmp_path / "days" / f"{day}.parquet") for day in (start, end)])
        bars = bars.loc[bars.Code.eq(key.code)].reset_index(drop=True)
        adjusted, actions = adjust_training_window(key, bars, days, end, snapshot)
        assert actions.empty and adjusted.SegmentId.nunique() == 2 and adjusted.Change.isna().all()
        for column in ("Open", "High", "Low", "Close", "Volume"):
            assert adjusted[column].tolist() == bars[f"Raw{column}"].tolist()
        assert adjusted.Amount.tolist() == bars.Amount.tolist()

    active_path, delisted_path = tmp_path / "active.parquet", tmp_path / "delisted.parquet"
    with pytest.raises(SystemExit) as error:
        main(["--start", start, "--end", end, "--published-start", str(days[0].date() - timedelta(days=7)),
              "--published-end", str(days[-1].date() + timedelta(days=3)), "--krx-days", str(tmp_path / "days"),
              "--active-master", str(active_path), "--delisted-master", str(delisted_path),
              "--kind-root", str(tmp_path / "kind"), "--output", str(tmp_path / "preferred_only"), "--code", preferred])
    assert error.value.code == 1
    assert f"Issuer merger source is outside the bounded census; include --code for {common}" in capsys.readouterr().err

    output = tmp_path / "output"
    coverage_path, resolutions_path, manifest_path = (output / name for name in ("coverage.json", "resolutions.csv", "manifest.json"))
    original_coverage = coverage_path.read_bytes()
    manifest = json.loads(manifest_path.read_bytes())
    coverage = json.loads(original_coverage)
    coverage["kind_final_families"][0]["ClosedWindows"] = [item for item in family["ClosedWindows"] if item["Code"] == common]
    coverage_path.write_text(json.dumps(coverage))
    manifest["table_sha256"]["coverage"] = sha256(coverage_path)
    manifest_path.write_text(json.dumps(manifest))
    inputs = {"krx_days": tmp_path / "days", "active_master": active_path, "delisted_master": delisted_path,
              "evidence_archives": [tmp_path / "kind"]}
    with pytest.raises(DisclosureError, match="leaves an affected window unconfirmed"):
        freeze_resolution_snapshot(output, tmp_path / "invalid_closure", **inputs)

    coverage_path.write_bytes(original_coverage)
    manifest["table_sha256"]["coverage"] = sha256(coverage_path)
    resolutions = pd.read_csv(resolutions_path, dtype=str, keep_default_na=False)
    resolutions[resolutions.Code.eq(common)].to_csv(resolutions_path, index=False)
    manifest["resolutions_without_price_observation"] -= 1
    manifest["market_resolution_counts"][Resolution.SEGMENT_BREAK] -= 1
    manifest["table_sha256"]["resolutions"] = sha256(resolutions_path)
    manifest_path.write_text(json.dumps(manifest))
    with pytest.raises(DisclosureError, match=f"{preferred}: census omits a verified resolution"):
        freeze_resolution_snapshot(output, tmp_path / "missing_boundary", **inputs)

    manifest["resolutions_without_price_observation"] += 1
    manifest["market_resolution_counts"][Resolution.SEGMENT_BREAK] += 1
    changed = resolutions.copy()
    changed.loc[changed.Code.eq(preferred), "Reason"] = "official_merger"
    changed.to_csv(resolutions_path, index=False)
    manifest["table_sha256"]["resolutions"] = sha256(resolutions_path)
    manifest_path.write_text(json.dumps(manifest))
    with pytest.raises(DisclosureError, match="Resolution evidence refers to another notice or security"):
        freeze_resolution_snapshot(output, tmp_path / "false_direct_evidence", **inputs)


def test_census_freezes_headingless_listing_and_reference_for_actual_market_transfer(tmp_path, monkeypatch):
    listing, pricing = "20190308000743", "20190311000683"
    use_archived_kind_bodies(monkeypatch, {"2019-03-08": (listing,), "2019-03-11": (pricing,)},
                            issuer="19208", submitter="유가증권시장본부")
    snapshot, notices = freeze_kind_case(tmp_path, [
        ("2019-03-11", "192080", "더블유게임즈", "KOSDAQ", 61_500, 62_600, 59_500, 62_500, 1000, 479_859, 29_579_552_300, 18_260_502),
        ("2019-03-12", "192080", "더블유게임즈", "KOSPI", 63_500, 63_500, 61_500, 62_000, -500, 68_657, 4_295_510_100, 18_260_502),
    ], active=[("192080", "KR7192080000", "더블유게임즈보통주", "더블유게임즈", "KOSPI", "주권", "2019/03/12", "보통주")],
        delisted=[("192080", "KR7192080000", "더블유게임즈", "KOSDAQ", "주권", "2015/11/04", "2019/03/12", "보통주")])
    assert (notices.loc[listing].Code, notices.loc[listing].AppliedDate, notices.loc[listing].SharesAfter) == (
        "192080", "2019-03-12", 18_260_502,
    )
    source, target = sorted(snapshot.ledgers, key=lambda key: key.listing)
    assert source.isin == target.isin and (source.market, target.market) == ("KOSDAQ", "KOSPI")
    assert not snapshot.ledgers[source].resolutions and not snapshot.ledgers[target].candidates
    event, = snapshot.ledgers[target].resolutions
    assert (event.date, event.kind, event.price_factor, event.volume_factor, event.review) == (
        "2019-03-12", Resolution.REFERENCE_RESET, 1, 1, False,
    )
    assert {proof.accession for proof in event.evidence} == {listing, pricing}


def test_nearby_unchanged_quarterly_dividend_does_not_become_the_bonus_review_reason(tmp_path, monkeypatch):
    dividend, bonus = "20190327001145", "20190328000862"
    use_archived_kind_bodies(monkeypatch, {"2019-03-27": (dividend,), "2019-03-28": (bonus,)},
                            issuer="00284", submitter="유가증권시장본부")
    snapshot, notices = freeze_kind_case(tmp_path, [
        ("2019-03-27", "002840", "미원상사", "KOSPI", 393_000, 393_000, 383_000, 390_500, -3000, 1950, 754_539_500, 774_940),
        ("2019-03-28", "002840", "미원상사", "KOSPI", 388_000, 391_000, 376_000, 388_000, -2500, 3265, 1_258_945_000, 774_940),
        ("2019-03-29", "002840", "미원상사", "KOSPI", 77_700, 77_700, 55_000, 55_000, -4800, 104_550, 6_932_625_000, 774_940),
    ], active=[("002840", "KR7002840007", "미원상사보통주", "미원상사", "KOSPI", "주권", "1989/09/25", "보통주")])
    notice = notices.loc[dividend]
    assert (notice.AppliedDate, notice.BasePrice, notice.Reason) == (
        "2019-03-28", 390_500, "중간(분기)배당락(기준가격 변동없음)",
    )
    ledger, = snapshot.ledgers.values()
    candidate, = ledger.candidates
    assert (candidate.date, candidate.prev_close, candidate.base_price) == ("2019-03-29", 388_000, 59_800)
    event, = ledger.resolutions
    assert (event.date, event.kind, event.reason, event.review, event.price_factor, event.volume_factor) == (
        "2019-03-29", Resolution.SEGMENT_BREAK, "official_facts_conflict_or_lack_terms", True, None, None,
    )
    assert {proof.accession for proof in event.evidence} == {bonus}


def test_census_freezes_sambu_split_with_separate_same_day_english_name_change(tmp_path, monkeypatch):
    listing, pricing = "20190430000089", "20190430000477"
    use_archived_kind_bodies(monkeypatch, {"2019-04-30": (listing, pricing)}, issuer="00147", submitter="유가증권시장본부")
    snapshot, notices = freeze_kind_case(tmp_path, [
        ("2019-04-30", "001470", "삼부토건", "KOSPI", 0, 0, 0, 4685, 0, 0, 0, 24_803_131),
        ("2019-05-02", "001470", "삼부토건", "KOSPI", 910, 1060, 905, 976, 39, 3_500_464, 3_483_743_665, 124_015_655),
    ], active=[("001470", "KR7001470004", "삼부토건보통주", "삼부토건", "KOSPI", "주권", "1976/06/26", "보통주")])
    notice = notices.loc[listing]
    assert (notice.Code, notice.AppliedDate, notice.Reason, notice.ParBefore, notice.ParAfter) == (
        "001470", "2019-05-02", "액면분할", 5000, 1000,
    )
    ledger, = snapshot.ledgers.values()
    candidate, = ledger.candidates
    assert (candidate.prev_close, candidate.base_price, candidate.shares_before, candidate.shares_after) == (
        4685, 937, 24_803_131, 124_015_655,
    )
    event, = ledger.resolutions
    assert (event.date, event.kind, event.price_factor, event.volume_factor, event.review) == (
        "2019-05-02", Resolution.UNIT_CHANGE, Fraction(1, 5), 5, False,
    )
    assert {proof.accession for proof in event.evidence} == {listing, pricing}


def test_census_freezes_jcontentree_transfer_with_explicit_standard_code_and_share_class(tmp_path, monkeypatch):
    listing, pricing = "20191016000448", "20191017000221"
    use_archived_kind_bodies(monkeypatch, {"2019-10-16": (listing,), "2019-10-17": (pricing,)},
                            issuer="03642", submitter="유가증권시장본부")
    snapshot, notices = freeze_kind_case(tmp_path, [
        ("2019-10-17", "036420", "제이콘텐트리", "KOSDAQ", 34_650, 36_200, 33_250, 34_000, -550, 631_833, 21_770_879_900, 14_406_898),
        ("2019-10-18", "036420", "제이콘텐트리", "KOSPI", 34_700, 34_950, 33_900, 34_400, 400, 136_680, 4_702_076_250, 14_406_898),
    ], active=[("036420", "KR7036420008", "콘텐트리중앙보통주", "콘텐트리중앙", "KOSPI", "주권", "2019/10/18", "보통주")],
        delisted=[("036420", "KR7036420008", "한길무역", "KOSDAQ", "주권", "2000/03/23", "2019/10/18", "보통주")])
    row = notices.loc[listing]
    assert (row.Code, row.ISIN, row.ShareClass, row.AppliedDate, row.SharesAfter) == (
        "036420", "KR7036420008", "common", "2019-10-18", 14_406_898,
    )
    target, = [key for key in snapshot.ledgers if key.market == "KOSPI"]
    event, = snapshot.ledgers[target].resolutions
    assert (event.kind, event.reason, event.price_factor, event.volume_factor) == (
        Resolution.REFERENCE_RESET, "official_continuous_transfer", 1, 1,
    )
    assert {ref.accession for ref in event.evidence} == {listing, pricing}


@pytest.mark.parametrize("accession,original,current,stock_rows", [
    ("20191015000306", "두산솔루스", "솔루스첨단소재", [
        ("336370", "KR7336370002", 4240, 5510, 1270, 43_470, 225_493_820, 30_457_400),
        ("33637K", "KR733637K010", 3240, 4210, 970, 13_113, 54_767_290, 7_366_400),
        ("33637L", "KR733637K028", 3570, 4640, 1070, 433, 1_825_080, 1_646_050),
    ]),
    ("20191015000308", "두산퓨얼셀", "두산퓨얼셀", [
        ("336260", "KR7336260005", 4240, 5510, 1270, 370_645, 2_026_883_140, 55_255_950),
        ("33626K", "KR733626K013", 3240, 4210, 970, 27_177, 113_474_270, 13_364_200),
        ("33626L", "KR733626K021", 3570, 4640, 1070, 2385, 10_732_560, 2_986_300),
    ]),
])
def test_census_freezes_all_three_dated_classes_of_one_official_relisting(tmp_path, monkeypatch, accession, original,
                                                                 current, stock_rows):
    use_archived_kind_bodies(monkeypatch, {"2019-10-15": (accession,)}, issuer=stock_rows[0][0][:5],
                            submitter="유가증권시장본부")
    raw, active, expected = [], [], []
    for section, ((code, isin, opening, close, change, volume, amount, shares), label, short, class_name) in enumerate(
        zip(stock_rows, ("보통주", "1우선주", "2우선주(신형)"), ("", "1우", "2우B"), ("보통주", "구형우선주", "신형우선주")), 1,
    ):
        raw.append(("2019-10-18", code, original + short, "KOSPI", opening, close, opening, close, change, volume, amount, shares))
        active.append((code, isin, current + label, current + short, "KOSPI", "주권", "2019/10/18", class_name))
        expected.append((section, code, isin, "common" if section == 1 else "preferred", "2019-10-18", shares))
    snapshot, notices = freeze_kind_case(tmp_path, raw, active=active)
    assert list(notices.sort_values("Section")[["Section", "Code", "ISIN", "ShareClass", "AppliedDate", "SharesAfter"]]
                .itertuples(index=False, name=None)) == expected
    assert len(snapshot.ledgers) == 3 and all(not ledger.resolutions for ledger in snapshot.ledgers.values())
    assert all(key.listing == "2019-10-18" for key in snapshot.ledgers)


@pytest.mark.parametrize("tamper,reason", [
    ("stock", "warrant-only fields do not cover both instruments"),
    ("mixed", "warrant change mixes listing blocks"),
    ("partial", "warrant-only fields do not cover both instruments"),
    ("missing", "missing official non-stock notice evidence"),
    ("omitted", "Missing official structural notice evidence: 20210720000217"),
])
def test_warrant_only_disclosure_preserves_evidence_but_not_a_stock_coverage_gap(tmp_path, monkeypatch, tamper, reason):
    warrant, auction = "20210720000217", "20210720000265"
    use_archived_kind_bodies(monkeypatch, {"2021-07-20": (warrant, auction)}, issuer="04267", submitter="유가증권시장본부")
    snapshot, notices = freeze_kind_case(tmp_path, [
        ("2021-07-20", "042670", "두산인프라코어", "KOSPI", 0, 0, 0, 14_450, 0, 0, 0, 231_195_460),
        ("2021-07-21", "042670", "두산인프라코어", "KOSPI", 15_350, 19_350, 14_900, 16_950, 1600, 40_010_263,
         706_775_904_050, 78_309_228),
    ], active=[], delisted=[("042670", "KR7042670000", "HD현대인프라코어", "KOSPI", "주권", "2001/02/02",
                              "2026/01/26", "보통주")])
    assert list(notices.index) == [auction]
    price = notices.loc[auction]
    assert (price.EvaluationPrice, price.Low, price.High) == (13_250, 6630, 26_500)
    window, = snapshot.windows.values()
    assert window["complete"] and window["structural_documents_incomplete"] == []
    proof, = snapshot.coverage["nonstock_notices"]
    assert proof["AcptNo"] == warrant and len(proof["Evidence"]) == 4
    assert {Evidence(**ref) for ref in proof["Evidence"]} <= snapshot.archive_refs
    ledger, = snapshot.ledgers.values()
    candidate, = ledger.candidates
    assert candidate.base_price == 15_350
    event, = ledger.resolutions
    assert (event.date, event.kind, event.reason, event.review, event.price_factor, event.volume_factor) == (
        "2021-07-21", Resolution.SEGMENT_BREAK, "official_division", False, None, None,
    )
    assert {ref.accession for ref in event.evidence} == {auction}

    output, cache = tmp_path / "output", tmp_path / "kind"
    coverage_path = output / "coverage.json"
    coverage = json.loads(coverage_path.read_bytes())
    refs = coverage["nonstock_notices"][0]["Evidence"]
    old = Evidence(**refs.pop())
    if tamper == "omitted":
        coverage["nonstock_notices"].clear()
    elif tamper != "missing":
        receipt = json.loads((cache / "receipts" / f"{old.receipt}.json").read_bytes())
        body = (cache / "objects" / old.sha256).read_bytes()
        if tamper == "stock":
            encoded = body.replace(b"KRA0340221B1", b"KR7034021000").replace(b"J0340221B", b"A034020")
        elif tamper == "mixed":
            fixtures = Path(__file__).parents[2] / "shared/tests/fixtures/market_actions"
            encoded = body + gzip.decompress((fixtures / "20190430000089.html.gz").read_bytes())
        else:
            encoded = body.replace(b"KRA0340221B1 (", b"(", 1)
        assert encoded != body
        replaced = KindMarket(cache)._store(receipt["request"], encoded, receipt["charset"], None, "fixture")
        refs.append(vars(replaced.evidence))
    coverage_path.write_text(json.dumps(coverage))
    manifest_path = output / "manifest.json"
    manifest = json.loads(manifest_path.read_bytes())
    if tamper == "omitted":
        manifest["nonstock_notices"] = 0
    manifest["table_sha256"]["coverage"] = sha256(coverage_path)
    manifest_path.write_text(json.dumps(manifest))
    with pytest.raises(DisclosureError, match=reason):
        freeze_resolution_snapshot(output, tmp_path / "tampered_official_actions", krx_days=tmp_path / "days",
                                   active_master=tmp_path / "active.parquet", delisted_master=tmp_path / "delisted.parquet",
                                   evidence_archives=[cache])


@pytest.mark.parametrize("case,calls", [
    ("cold", 7), ("warm", 4), ("warm_target", 1), ("displayed_before_prefix", 4), ("wrong_issuer", 1),
    ("wrong_family", 2), ("family_flags", 2),
    ("unlisted", 1), ("wrong_route", 1), ("same_accession", 1), ("target_is_n", 2), ("budget", 3), ("rename_only", 4),
])
def test_correction_referral_uses_verified_route_daily_listing_and_final_viewer(tmp_path, monkeypatch, case, calls):
    from contextlib import nullcontext

    original, target = "20170112000045", "20170112000046"
    old_doc, new_doc = "20170112000099", "20170112000215"
    listing_day = date(2017, 1, 12)
    target_day = date(2017, 1, 11) if case == "displayed_before_prefix" else listing_day
    old_viewer, new_viewer = map(kind_document_url, (original, target))
    target_form = "70765" if case == "rename_only" else "68154"
    new_url = f"https://kind.krx.co.kr/external/2017/01/12/000046/{new_doc}/{target_form}.htm"
    old_url = f"https://kind.krx.co.kr/external/2017/01/12/000045/{old_doc}/68151.htm"
    fixture = Path(__file__).parents[2] / "shared/tests/fixtures/market_actions"
    final_body = gzip.decompress((fixture / f"{target}.html.gz").read_bytes())
    if case == "rename_only":
        final_body = ("<table><tr><td>1.변경전 상호</td><td>LG화학</td></tr>"
                      "<tr><td>2.변경후 상호</td><td>한글</td><td>LG케미칼</td></tr>"
                      "<tr><td>4.상장일</td><td>2017-01-17</td></tr></table>").encode()

    def listing(accession, issuer, title):
        return (f"<tr><td>12:00</td><td><a onclick=\"companysummary_open('{issuer}')\">LG화학</a></td>"
                f"<td><a onclick=\"openDisclsViewer('{accession}','')\">{title}</a></td><td>유가증권시장본부</td><td></td></tr>")

    def viewer(acpt, selected):
        prior = "20170112000098" if case == "wrong_family" and acpt == target else old_doc
        old_flag = "Y" if case == "family_flags" and acpt == target else "N"
        items = ''.join(f'<option value="{number}|{flag}"{" selected" if number == selected else ""}></option>'
                        for number, flag in ((prior, old_flag), (new_doc, 'Y')))
        return f'<input name="acptNo" id="acptNo" value="{acpt}"><select id="mainDoc">{items}</select>'.encode()

    detected_url = new_url.replace("kind.krx.co.kr", "not-kind.krx.co.kr") if case == "wrong_route" else new_url
    if case == "same_accession":
        detected_url = new_url.replace("/000046/", "/000045/")
    responses = {
        old_viewer: viewer(original, old_doc), new_viewer: viewer(target, old_doc if case == "target_is_n" else new_doc),
        f"{KIND_VIEWER}?method=searchContents&docNo={old_doc}": f"parent.setPath('', '{old_url}')".encode(),
        f"{KIND_VIEWER}?method=searchContents&docNo={new_doc}": f"parent.setPath('', '{detected_url}')".encode(),
        old_url: b"Obsolete body intentionally does not supply resolution facts.", new_url: final_body,
    }

    def respond(method, url, *, data, headers, **kwargs):
        if url == DAILY_URL:
            listed = []
            if data["selDate"] == str(listing_day):
                listed.append(listing(original, "05191", "추가상장(합병)"))
            if data["selDate"] == str(target_day) and case != "unlisted":
                listed.append(listing(target, "00001" if case == "wrong_issuer" else "05191", "변경상장(상호변경)"))
            rows = "".join(listed) or "조회된 결과값이 없습니다."
            payload = f"<table>{rows}</table>전체 <em>{len(listed)}</em>건 : <strong>1</strong>/1".encode()
        else:
            payload = responses[url]
        reply = MagicMock(status_code=200, headers={})
        reply.iter_content.return_value = [payload]
        return nullcontext(reply)

    session = Mock()
    session.request.side_effect = respond
    monkeypatch.setattr("shared.data.kind_market.requests.Session", lambda: session)
    monkeypatch.setattr("shared.data.kind_market.time.sleep", lambda _: None)
    cache = tmp_path / "kind"
    seeded = KindMarket(cache, budget=20)
    filings = []
    for day in pd.date_range("2017-01-09", "2017-01-20"):
        rows, _ = seeded.day(day.date())
        filings.extend(rows)
    if case != "cold":
        before = seeded.calls
        seeded.document(next(row for row in filings if row.accession == original))
        assert seeded.calls - before == 3
    if case == "warm_target":
        before = seeded.calls
        seeded.document(next(row for row in filings if row.accession == target))
        assert seeded.calls - before == 3
    session.request.reset_mock()
    actual_rows = [
        ("2017-01-16", "051910", "LG화학", "KOSPI", 282_000, 283_500, 278_000, 278_500, -4500, 198_568, 55_506_248_500, 66_271_100),
        ("2017-01-17", "051910", "LG화학", "KOSPI", 278_000, 284_000, 276_000, 278_500, 0, 218_884, 61_049_828_500, 70_592_343),
    ]
    master = [("051910", "KR7051910008", "LG화학", "LG화학", "KOSPI", "주권", "2001/04/25", "보통주")]
    if case not in {"cold", "warm", "warm_target", "displayed_before_prefix"}:
        with pytest.raises(DisclosureError, match="incomplete source or identity coverage"):
            freeze_kind_case(tmp_path, actual_rows, active=master, budget=3 if case == "budget" else 4, preview=True)
        coverage = json.loads((tmp_path / "output/coverage.json").read_bytes())
        window, = coverage["windows"]
        assert window["structural_documents_incomplete"] == [original]
        assert not coverage["kind_final_families"] and session.request.call_count == calls
        return
    snapshot, notices = freeze_kind_case(tmp_path, actual_rows, active=master, budget=calls)
    assert session.request.call_count == snapshot.manifest["kind_http_calls_this_run"] == calls
    assert snapshot.manifest["selected_documents"] == snapshot.manifest["retrieved_documents"] == 2
    assert snapshot.manifest["superseded_documents"] == 1 and list(notices.index) == [target]
    assert notices.loc[target, "Published"] == target_day.isoformat()
    family, = snapshot.coverage["kind_final_families"]
    assert (family["AcptNo"], family["DocNo"], family["FinalAcptNo"], family["FinalDocNo"]) == (
        original, old_doc, target, new_doc,
    )
    assert len(family["Evidence"]) == 7 and family["ClosedWindows"][0]["Code"] == "051910"
    assert {Evidence(**row) for row in family["Evidence"]} <= snapshot.archive_refs
    ledger, = snapshot.ledgers.values()
    resolution, = ledger.resolutions
    assert (resolution.date, resolution.reason, resolution.review) == ("2017-01-17", "official_merger", False)

    active, delisted, days = (tmp_path / item for item in ("active.parquet", "delisted.parquet", "days"))
    replay = tmp_path / "cached_census"
    session.request.reset_mock()
    main(["--start", "2017-01-16", "--end", "2017-01-17", "--published-start", "2017-01-09", "--published-end",
          "2017-01-20", "--krx-days", str(days), "--active-master", str(active), "--delisted-master", str(delisted),
          "--kind-root", str(cache), "--output", str(replay)])
    pinned = freeze_resolution_snapshot(replay, tmp_path / "cached_snapshot", krx_days=days, active_master=active,
                                        delisted_master=delisted, evidence_archives=[cache])
    reread = read_resolution_snapshot(pinned, verify_archive=True)
    assert session.request.call_count == reread.manifest["kind_http_calls_this_run"] == 0
    assert reread.ledgers == snapshot.ledgers and reread.archive_refs == snapshot.archive_refs

    coverage_path, manifest_path = replay / "coverage.json", replay / "manifest.json"
    coverage = json.loads(coverage_path.read_bytes())
    manifest = json.loads(manifest_path.read_bytes())
    if case == "cold":
        coverage["kind_final_families"] = []
        manifest["superseded_documents"] = 0
        error = f"Missing official structural notice evidence: {original}"
    elif case == "warm":
        refs = coverage["kind_final_families"][0]["Evidence"]
        refs[2] = refs[5]
        error = "KIND correction discovery receipt differs"
    else:
        refs = coverage["kind_final_families"][0]["Evidence"]
        prior = Evidence(**refs[-1])
        receipt = json.loads((cache / "receipts" / f"{prior.receipt}.json").read_bytes())
        altered = (cache / "objects" / prior.sha256).read_bytes() + b" "
        replacement = KindMarket(cache)._store(receipt["request"], altered, receipt["charset"], None, "fixture")
        refs[-1] = vars(replacement.evidence)
        error = "KIND correction target has no verified stock facts"
    coverage_path.write_text(json.dumps(coverage))
    manifest["table_sha256"]["coverage"] = sha256(coverage_path)
    manifest_path.write_text(json.dumps(manifest))
    with pytest.raises(DisclosureError, match=error):
        freeze_resolution_snapshot(replay, tmp_path / "tampered_snapshot", krx_days=days, active_master=active,
                                   delisted_master=delisted, evidence_archives=[cache])
