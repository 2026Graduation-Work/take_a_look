import gzip
import hashlib
import json
from collections import defaultdict
from datetime import date, timedelta
from fractions import Fraction
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
    for accession in (accession for rows in filings.values() for accession in rows):
        source = sources[accession]
        viewer, document, url = kind_document_url(accession), source["document_no"], source["body_url"]
        documents[viewer] = (
            f'<input name="acptNo" id="acptNo" value="{accession}">'
            f'<select id="mainDoc"><option value="{document}|Y" selected></option></select>'
        ).encode()
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


def freeze_kind_case(tmp_path, raw, *, active, delisted=()):
    days, cache, output = (tmp_path / name for name in ("days", "kind", "output"))
    days.mkdir()
    columns = ["Date", "Code", "ISU_ABBRV", "MKT_NM", "RawOpen", "RawHigh", "RawLow", "RawClose", "RawChange",
               "RawVolume", "Amount", "ListedShares"]
    bars = pd.DataFrame(raw, columns=columns).assign(SECT_TP_NM="")
    bars["Date"] = pd.DatetimeIndex(bars.Date, dtype="datetime64[ns]")
    for day, rows in bars.groupby("Date"):
        rows.to_parquet(days / f"{day:%Y-%m-%d}.parquet", index=False)
    active_path, delisted_path = tmp_path / "active.parquet", tmp_path / "delisted.parquet"
    pd.DataFrame(active, columns=["ISU_SRT_CD", "ISU_CD", "ISU_NM", "ISU_ABBRV", "MKT_TP_NM", "SECUGRP_NM", "LIST_DD",
                                  "KIND_STKCERT_TP_NM"]).to_parquet(active_path, index=False)
    pd.DataFrame(delisted, columns=["Symbol", "ISIN", "Name", "Market", "SecuGroup", "ListingDate", "DelistingDate",
                                    "KIND_STKCERT_TP_NM"]).to_parquet(delisted_path, index=False)
    start, end = bars.Date.min().date(), bars.Date.max().date()
    main(["--start", str(start), "--end", str(end), "--published-start", str(start - timedelta(days=7)),
          "--published-end", str(end + timedelta(days=3)), "--krx-days", str(days), "--active-master", str(active_path),
          "--delisted-master", str(delisted_path), "--kind-root", str(cache), "--output", str(output)])
    path = freeze_resolution_snapshot(output, tmp_path / "official_actions", krx_days=days,
                                       active_master=active_path, delisted_master=delisted_path, evidence_archives=[cache])
    notices = pd.read_csv(output / "notices.csv", dtype={"Code": str, "AcptNo": str}).set_index("AcptNo")
    return read_resolution_snapshot(path, verify_archive=True), notices


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
