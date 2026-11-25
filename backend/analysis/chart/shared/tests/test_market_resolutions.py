import gzip
import hashlib
import json
from dataclasses import replace
from datetime import date
from fractions import Fraction
from pathlib import Path

import pandas as pd
import pytest
from shared.data.actions import Action, FieldEvidence, deal_table, tick_size
from shared.data.disclosures import DisclosureError, Evidence, Response, collect_pages
from shared.data.events import apply_events
from shared.data.kind_market import (
    DAILY_URL,
    KindBody,
    KindMarket,
    KindUnavailable,
    MarketFiling,
    daily_form,
    daily_page,
)
from shared.data.market_notices import SecurityKey, match_notice, normal_company, parse_notice
from shared.data.market_resolutions import (
    Resolution,
    adjustment_events,
    raw_window_fingerprint,
    resolve_events,
)

FIXTURES = Path(__file__).parent / "fixtures" / "market_actions"
SOURCES = json.loads((FIXTURES / "sources.json").read_text())
TEST_SOURCE = Evidence("a" * 64, "b" * 64)
SAMSUNG = SecurityKey("010140", "KR7010140002", "1994-01-28", None, "KOSPI", "common")
YELLOW = SecurityKey("104620", "KR7104620000", "2019-01-30", None, "KOSDAQ", "common")
KAON = SecurityKey("078890", "KR7078890001", "2005-07-12", None, "KOSDAQ", "common")
IBKS = SecurityKey("373200", "KR7373200005", "2021-02-26", None, "KOSDAQ", "common")
GMI = SecurityKey("019570", "KR7019570001", "1989-03-14", None, "KOSDAQ", "common")
UNICHEM = SecurityKey("011330", "KR7011330008", "1989-12-14", None, "KOSPI", "common")
CELLTRION = SecurityKey("068270", "KR7068270008", "2018-02-09", None, "KOSPI", "common")
DOBU = SecurityKey("227420", "KR7227420007", "2016-12-28", None, "KONEX", "common")


def actual_notices(security, *accessions, aliases=()):
    notices = []
    for accession in accessions:
        info = SOURCES[accession]
        body = gzip.decompress((FIXTURES / f"{accession}.html.gz").read_bytes())
        assert hashlib.sha256(body).hexdigest() == info["sha256"]
        published = date.fromisoformat(f"{accession[:4]}-{accession[4:6]}-{accession[6:8]}")
        source = Evidence(info["sha256"], "c" * 64)
        response = KindBody(body, info["charset"], source, info["document_no"], tuple(info["family"]), info["final"])
        filing = MarketFiling(accession, published, info["title"], TEST_SOURCE, company=info["company"])
        scope = {security: {normal_company(name) for name in (info["company"], *aliases)}}
        notices.extend(match_notice(filing, info["form"], facts, response, (source,), scope)
                       for facts in parse_notice(filing, info["form"], response))
    return notices


def bars(security, rows):
    raw = pd.DataFrame(rows, columns=["Date", "RawOpen", "RawHigh", "RawLow", "RawClose",
                                      "RawChange", "RawVolume", "Amount", "ListedShares"])
    raw["Date"] = pd.to_datetime(raw.Date)
    raw["Market"] = security.market
    raw["Code"] = security.code
    return raw


def resolve(security, raw, notices, **kwargs):
    return resolve_events(security, raw, pd.DatetimeIndex(raw.Date), notices, **kwargs)


def test_official_rights_keep_pre_event_volume_and_observed_amount():
    raw = bars(SAMSUNG, [
        ("2018-03-06", 8280, 8610, 7960, 8510, 270, 13_313_159, 111_274_387_450, 390_000_000),
        ("2018-03-07", 7750, 8180, 7500, 7620, 110, 14_231_075, 111_008_964_920, 390_000_000),
    ])
    notices = actual_notices(SAMSUNG, "20180306000596")
    result = resolve(SAMSUNG, raw, notices)
    row, = result.resolutions
    assert (row.kind, row.price_factor, row.volume_factor) == (Resolution.RIGHTS, Fraction(7510, 8510), 1)
    adjusted = apply_events(raw, adjustment_events(result.resolutions))
    assert list(adjusted.Close) == pytest.approx([7510, 7620])
    assert list(adjusted.Volume) == list(raw.RawVolume)
    assert list(adjusted.Amount) == list(raw.Amount)
    assert list(adjusted.RawClose) == [8510, 7620]

    blocked = resolve(SAMSUNG, raw, notices, coverage_complete=True, blocked_dates={"2018-03-07"})
    assert blocked.resolutions == ()
    assert blocked.incomplete == ("2018-03-07",)
    absent = resolve(SAMSUNG, raw, [])
    assert absent.incomplete == ("2018-03-07",)
    no_proof = resolve(SAMSUNG, raw, [], coverage_complete=True)
    assert no_proof.incomplete == ()
    missing, = no_proof.resolutions
    assert missing.kind == Resolution.SEGMENT_BREAK and missing.price_factor is None and missing.review
    unparsable = FieldEvidence("20180306000001", TEST_SOURCE, "unsupported official terms")
    conflict, = resolve(SAMSUNG, raw, notices, coverage_complete=True,
                        unparsed_dates={"2018-03-07": [unparsable]}).resolutions
    assert conflict.kind == Resolution.SEGMENT_BREAK and unparsable in conflict.evidence

    mixed = [replace(notices[0], facts=replace(notices[0].facts, reason="권배락(유상증자)"))]
    assert resolve(SAMSUNG, raw, mixed, coverage_complete=True).resolutions[0].kind == Resolution.SEGMENT_BREAK


def test_bonus_uses_official_ratio_and_checks_actual_later_listing_shares():
    raw = bars(YELLOW, [
        ("2021-07-21", 33700, 34950, 33700, 34700, 1100, 364491, 12_537_617_550, 4_765_650),
        ("2021-07-22", 14450, 15050, 14000, 15050, 3450, 994351, 14_569_726_470, 4_765_650),
        ("2021-08-13", 16250, 16250, 15300, 15550, -750, 302542, 4_769_676_650, 4_765_650),
        ("2021-08-17", 13600, 14650, 13000, 13400, -2150, 1_739_660, 23_559_826_700, 14_296_950),
    ])
    notices = actual_notices(YELLOW, "20210721000416", "20210707000126")
    result = resolve(YELLOW, raw, notices, coverage_complete=True)
    first = result.resolutions[0]
    assert (first.kind, first.price_factor, first.volume_factor) == (Resolution.BONUS, Fraction(1, 3), 3)
    adjusted = apply_events(raw, adjustment_events(result.resolutions))
    assert adjusted.Volume.iloc[0] == 3 * raw.RawVolume.iloc[0]
    raw.loc[3, "ListedShares"] += 1
    invalid = resolve(YELLOW, raw, notices, coverage_complete=True).resolutions[0]
    assert invalid.kind == Resolution.SEGMENT_BREAK and invalid.review


def test_stock_dividend_uses_per_share_terms_and_not_treasury_adjusted_share_count():
    raw = bars(KAON, [
        ("2022-12-27", 7200, 7400, 7180, 7400, 200, 122155, 893_210_560, 16_332_884),
        ("2022-12-28", 7210, 8160, 7170, 7550, 350, 2_780_448, 21_734_161_420, 16_332_884),
    ])
    notices = actual_notices(KAON, "20221227000896", "20221220000339", aliases=("가온미디어", "가온그룹"))
    row, = resolve(KAON, raw, notices).resolutions
    assert (row.kind, row.price_factor, row.volume_factor) == (Resolution.BONUS, Fraction(100, 103), Fraction(103, 100))
    no_ratio, = resolve(KAON, raw, notices[:1], coverage_complete=True).resolutions
    assert no_ratio.kind == Resolution.SEGMENT_BREAK
    stale = [notices[0], replace(notices[1], final=False)]
    assert resolve(KAON, raw, stale, coverage_complete=True).resolutions[0].kind == Resolution.SEGMENT_BREAK


def test_spac_merger_discovered_without_price_candidate_or_raw_sector_column():
    raw = bars(IBKS, [
        ("2022-01-19", 2550, 3270, 2540, 2995, 355, 4_948_758, 14_746_746_210, 3_520_000),
        ("2022-01-20", 2950, 3195, 2710, 3080, 85, 1_007_086, 2_937_947_170, 17_647_000),
    ])
    notices = actual_notices(IBKS, "20220119000510", "20220117000675")
    ledger = resolve(IBKS, raw, notices)
    assert ledger.candidates == ()
    row, = ledger.resolutions
    assert (row.date, row.kind, row.price_factor, row.volume_factor) == (
        "2022-01-20", Resolution.SPAC_PREMERGER, None, None)
    assert {proof.accession for proof in row.evidence} == {"20220119000510", "20220117000675"}


def test_absorption_merger_marks_boundary_even_when_reference_and_both_bars_are_halted():
    raw = bars(DOBU, [
        ("2024-11-19", 0, 0, 0, 1808, 0, 0, 0, 16_444_510),
        ("2024-11-20", 0, 0, 0, 1808, 0, 0, 0, 38_044_510),
    ])
    row, = resolve(DOBU, raw, actual_notices(DOBU, "20241115000546")).resolutions
    assert row.kind == Resolution.SEGMENT_BREAK and row.reason == "official_merger" and not row.review


def test_resumption_keeps_actual_return_and_halted_share_change_has_no_factors():
    raw = bars(GMI, [
        ("2017-07-06", 0, 0, 0, 713, 0, 0, 0, 40_000_000),
        ("2017-07-07", 1200, 1200, 870, 918, -282, 24_316_677, 23_586_189_676, 40_000_000),
    ])
    notices = actual_notices(GMI, "20170706000452", aliases=("제미니투자",))
    row, = resolve(GMI, raw, notices).resolutions
    assert (row.kind, row.price_factor, row.volume_factor) == (Resolution.REFERENCE_RESET, 1, 1)
    assert list(apply_events(raw, adjustment_events([row])).Close) == [713, 918]

    raw = bars(UNICHEM, [
        ("2016-03-07", 0, 0, 0, 1780, 0, 0, 0, 46_359_262),
        ("2016-03-08", 0, 0, 0, 1780, 0, 0, 0, 47_138_062),
    ])
    row, = resolve(UNICHEM, raw, actual_notices(UNICHEM, "20160303000180")).resolutions
    assert row.kind == Resolution.SHARES_ONLY and row.price_factor is None and row.volume_factor is None


def test_auction_notice_with_unknown_price_column_requires_review():
    accession = "20170706000452"
    source = SOURCES[accession]
    body = gzip.decompress((FIXTURES / f"{accession}.html.gz").read_bytes()).decode(source["charset"])
    altered = body.replace("최고호가(원)", "기타호가(원)")
    assert altered != body
    filing = MarketFiling(accession, date(2017, 7, 6), source["title"], TEST_SOURCE, company=source["company"])
    response = Response(altered.encode(source["charset"]), source["charset"], TEST_SOURCE)
    with pytest.raises(DisclosureError):
        parse_notice(filing, source["form"], response)


def test_confirmed_market_transfer_uses_previous_session_as_observation_only():
    raw = bars(CELLTRION, [
        ("2018-02-08", 251300, 273000, 238500, 271400, 15400, 7_760_386, 2_017_164_537_000, 122_666_424),
        ("2018-02-09", 259000, 293000, 257500, 288000, 16500, 2_965_646, 832_262_058_000, 122_666_424),
    ])
    raw.loc[0, "Market"] = "KOSDAQ"
    raw["ISU_ABBRV"] = "셀트리온"
    former = SecurityKey("068270", CELLTRION.isin, "2005-07-19", "2018-02-09", "KOSDAQ", "common")
    before_proof = resolve(CELLTRION, raw.iloc[1:], [], transfer_anchor=raw.iloc[:1], transfer_source=former)
    assert before_proof.candidates[0].prev_date == "2018-02-08"
    assert not before_proof.resolutions and before_proof.incomplete == ("2018-02-09",)
    notices = actual_notices(CELLTRION, "20180208000785", "20180207000688")
    ledger = resolve(CELLTRION, raw.iloc[1:], notices, transfer_anchor=raw.iloc[:1])
    row, = ledger.resolutions
    assert (row.date, row.kind, row.price_factor, row.volume_factor) == ("2018-02-09", Resolution.REFERENCE_RESET, 1, 1)
    assert ledger.candidates[0].prev_date == "2018-02-08"


def test_tick_rule_uses_applicable_schedule_and_cannot_preempt_official_facts():
    assert tick_size(1_997, "2023-01-24", "KOSDAQ") == 5
    assert tick_size(1_997, "2023-01-25", "KOSDAQ") == 1
    assert tick_size(280_000, "2023-01-24", "KOSDAQ") == 100
    assert tick_size(280_000, "2023-01-25", "KOSDAQ") == 500
    raw = bars(YELLOW, [
        ("2023-01-20", 1997, 1997, 1997, 1997, 0, 1, 1997, 100),
        ("2023-01-24", 2000, 2000, 2000, 2000, 0, 1, 2000, 100),
    ])
    row, = resolve(YELLOW, raw, [], coverage_complete=True).resolutions
    assert row.kind == Resolution.TICK_ROUNDING
    raw.loc[1, "Date"] = pd.Timestamp("2023-01-25")
    row, = resolve(YELLOW, raw, [], coverage_complete=True).resolutions
    assert row.kind == Resolution.SEGMENT_BREAK


def test_verified_action_retains_lineage_and_conflicts_block_factors():
    raw = bars(YELLOW, [
        ("2021-07-21", 33700, 34950, 33700, 34700, 1100, 364491, 12_537_617_550, 4_765_650),
        ("2021-07-22", 14450, 15050, 14000, 15050, 3450, 994351, 14_569_726_470, 4_765_650),
        ("2021-07-26", 15050, 16000, 14400, 15100, 50, 1000, 15_100_000, 4_765_650),
    ])
    ratio = FieldEvidence("20210707000126", TEST_SOURCE, "공식 배정비율")
    action = Action(f"{YELLOW.isin}:fixture", ratio.accession, "bonus", "2021-07-22", 3, 1, None, 11600, None,
                    ratio, ratio, ratio, market="KOSDAQ")
    rights, = actual_notices(YELLOW, "20210721000416")
    competing = replace(rights, facts=replace(rights.facts, kind="auction", evaluation=1234, low=1100, high=1560))
    row, = resolve(YELLOW, raw, [rights, competing], actions=[action]).resolutions
    assert row.kind == Resolution.SEGMENT_BREAK and ratio in row.evidence
    division = replace(rights, facts=replace(rights.facts, reason="인적분할", kind="listing"))
    row, = resolve(YELLOW, raw, [division], actions=[action]).resolutions
    assert row.reason == "official_division" and ratio in row.evidence
    displaced = resolve(YELLOW, raw, [], actions=[replace(action, ex_date="2021-07-24")])
    assert "2021-07-24" in displaced.incomplete
    with pytest.raises(ValueError, match="identities"):
        resolve(YELLOW, raw, [], actions=[replace(action, event_id="wrong:fixture")])


def test_daily_list_page_uses_display_date_and_requires_valid_cardinality():
    day = date(2016, 1, 4)
    row = """<tr><td>07:00</td><td><a onclick="companysummary_open('00954')">현대</a></td>
      <td><a onclick="openDisclsViewer('20151231000676','')" title="안내">안내</a></td><td>한국거래소</td><td></td></tr>"""

    def page(text, total=1):
        body = (text + f"전체 <em>{total}</em>건 : <strong>1</strong>/1").encode()
        return Response(body, "utf-8", TEST_SOURCE)

    filed, coverage = collect_pages("KIND", day, day, 3000, lambda _: daily_page(page(row), day, 1))
    assert coverage.rows == 1 and filed[0].company_id == "00954"
    assert filed[0].accession == "20151231000676"
    assert filed[0].published == filed[0].displayed == day
    with pytest.raises(DisclosureError, match="row count"):
        collect_pages("KIND", day, day, 3000, lambda _: daily_page(page(row, total=2), day, 1))


def test_daily_list_date_matches_official_filing_with_later_accession_prefix():
    def response(key):
        source = SOURCES[key]
        body = gzip.decompress((FIXTURES / f"{key}.html.gz").read_bytes())
        assert hashlib.sha256(body).hexdigest() == source["sha256"]
        return Response(body, source["charset"], TEST_SOURCE)

    day = date(2021, 1, 25)
    page = response("daily_2021-01-25")
    rows, coverage = collect_pages("KIND", day, day, 3000, lambda _: daily_page(page, day, 1))
    filing, = [row for row in rows if row.accession == "20210129001104"]
    assert coverage.rows == 435
    assert filing.published == filing.displayed == day
    assert ["금융감독원장 귀하", "2021년 01월 25일"] in deal_table(response(filing.accession).text())


def test_kind_cache_import_preserves_receipt_time_and_skips_network(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    day = date(2016, 1, 1)
    response = "조회된 결과값이 없습니다. 전체 <em>0</em>건 : <strong>1</strong>/1".encode()
    digest = hashlib.sha256(response).hexdigest()
    received = "2026-11-25T03:15:47.724210+00:00"
    path = source / f"{day}_p1.html"
    path.write_bytes(response)
    path.with_suffix(".json").write_text(json.dumps({
        "url": DAILY_URL, "form": daily_form(day, 1), "charset": "utf-8",
        "sha256": digest, "received_at": received, "bytes": len(response),
    }))
    archive = tmp_path / "archive"
    client = KindMarket(archive, daily_cache=source)
    rows, span = client.day(day)
    assert not rows and span.rows == 0 and client.calls == 0
    receipt = archive / "receipts" / f"{span.pages[0].receipt}.json"
    assert json.loads(receipt.read_text())["received_at"] == received
    assert (archive / "objects" / digest).read_bytes() == response
    path.write_bytes(b"changed source copy")
    assert client.day(day)[1] == span
    (archive / "objects" / digest).write_bytes(b"changed archive copy")
    with pytest.raises(DisclosureError, match="changed"):
        client.day(day)


def test_kind_403_stops_further_live_requests(tmp_path):
    class Rejected:
        status_code = 403

        def __enter__(self):
            return self

        def __exit__(self, *_):
            pass

    class Session:
        def request(self, *_args, **_kwargs):
            return Rejected()

    client = KindMarket(tmp_path, budget=3, session=Session())
    with pytest.raises(KindUnavailable, match="403"):
        client.day(date(2016, 1, 1))
    with pytest.raises(KindUnavailable, match="stopped"):
        client.day(date(2016, 1, 2))
    assert client.calls == 1
    call = json.loads((tmp_path / "calls.jsonl").read_text())
    assert call["status"] == 403


def test_raw_window_fingerprint_checks_every_amount_and_expected_session():
    raw = bars(YELLOW, [
        ("2021-07-21", 33700, 34950, 33700, 34700, 1100, 364491, 12_537_617_550, 4_765_650),
        ("2021-07-22", 14450, 15050, 14000, 15050, 3450, 994351, 14_569_726_470, 4_765_650),
    ])
    expected = pd.DatetimeIndex(raw.Date)
    digest = raw_window_fingerprint(raw, expected)
    assert raw_window_fingerprint(raw.iloc[::-1], expected) == digest
    raw.loc[0, "Amount"] += 1
    assert raw_window_fingerprint(raw, expected) != digest
    with pytest.raises(ValueError, match="Price coverage mismatch"):
        raw_window_fingerprint(raw.iloc[1:], expected)


def test_historical_fixed_reference_notice_binds_a_compound_price_without_a_lone_split():
    from shared.data.market_notices import Notice, NoticeSection

    rows = [
        ["1. 회사명", "예시기업"],
        ["2. 기준가격", "주권종류", "단축코드", "기준가(원)"],
        ["보통주식", f"A{SAMSUNG.code}", "500"],
        ["3. 적용일", "2018-03-07"],
        ["4. 사유", "액면병합", "액면가 100원에서 500원으로 액면병합"],
        ["6. 기타", "기준가격은 액면병합 및 무상증자 권리락을 반영한 수치임"],
    ]
    table = "<table>" + "".join("<tr>" + "".join(f"<td>{cell}</td>" for cell in row) + "</tr>"
                              for row in rows) + "</table>"
    accession = "20180306000596"
    filing = MarketFiling(accession, date(2018, 3, 6), "변경상장 기준가격 안내", TEST_SOURCE, company="예시기업")
    body = KindBody(table.encode(), "utf-8", TEST_SOURCE, accession, (accession,), True)
    facts, = parse_notice(filing, "70795", body)
    assert (facts.kind, facts.base, facts.effective) == ("listing_price", 500, "2018-03-07")
    assert "무상증자 권리락" in facts.reason
    pricing = match_notice(filing, "70795", facts, body, (TEST_SOURCE,), {SAMSUNG: {"예시기업"}})
    listing = Notice(SAMSUNG, "20180306000595", "70764", "2018-03-06", "", "변경상장",
                     NoticeSection(1, "listing", "예시기업", "보통주식", "2018-03-07", "액면병합",
                                   shares_after=200, par_before=100, par_after=500),
                     (TEST_SOURCE,), "20180306000595", (), True)
    raw = bars(SAMSUNG, [
        ("2018-03-06", 100, 101, 99, 100, 0, 100, 10_000, 1000),
        ("2018-03-07", 500, 510, 495, 505, 5, 100, 50_500, 200),
    ])
    simple = replace(pricing, facts=replace(facts, reason="액면병합"))
    simple_event, = resolve(SAMSUNG, raw, [simple, listing], coverage_complete=True).resolutions
    assert simple_event.kind == Resolution.UNIT_CHANGE
    compound, = resolve(SAMSUNG, raw, [pricing, listing], coverage_complete=True).resolutions
    assert compound.kind == Resolution.SEGMENT_BREAK and compound.review


@pytest.mark.parametrize(
    "accession, security, shares",
    [
        ("20151021000366", SecurityKey("229000", "KR7229000005", "2015-10-27", "2020-06-25", "KONEX", "common"), 2_390_000),
        ("20150902000142", SecurityKey("225650", "KR7225650001", "2015-09-04", "2019-09-16", "KOSDAQ", "common"), 10_686_277),
        ("20151020000422", SecurityKey("227840", "KR7227840006", "2015-10-23", None, "KOSPI", "common"), 9_100_836),
    ],
)
def test_official_new_and_relisting_forms_keep_exact_identity_and_session(accession, security, shares):
    notice, = actual_notices(security, accession)
    facts = notice.facts
    assert (facts.kind, facts.isin, facts.code) == ("new_listing", security.isin, security.code)
    assert (facts.effective, facts.shares_after) == (security.listing, shares)


def test_official_fixed_reference_and_listing_agree_on_the_share_unit_change():
    security = SecurityKey("228180", "KR7228180006", "2015-10-22", "2020-08-07", "KONEX", "common")
    pricing, listing = actual_notices(security, "20160511000606", "20160509000281")
    assert (pricing.facts.kind, pricing.facts.share_label, pricing.facts.effective, pricing.facts.base) == (
        "listing_price", "보통주식", "2016-05-12", 14_500,
    )
    assert (listing.facts.par_before, listing.facts.par_after) == (5_000, 500)
    raw = bars(security, [
        ("2016-05-11", 0, 0, 0, 145_000, 0, 0, 0, 200_631),
        ("2016-05-12", 14_500, 14_500, 14_000, 14_300, -200, 3_350, 47_295_000, 2_006_310),
    ])
    event, = resolve(security, raw, [pricing, listing], coverage_complete=True).resolutions
    assert (event.kind, event.price_factor, event.volume_factor) == (Resolution.UNIT_CHANGE, Fraction(1, 10), 10)
    adjusted = apply_events(raw, adjustment_events([event]))
    assert adjusted.Close.tolist() == [14_500, 14_300]


def test_official_compound_fixed_reference_stays_unresolved():
    security = SecurityKey("123420", "KR7123420002", "2010-11-10", None, "KOSDAQ", "common")
    pricing, = actual_notices(security, "20160513000766")
    facts = pricing.facts
    assert (facts.kind, facts.share_label, facts.effective, facts.base) == (
        "listing_price", "보통주식", "2016-05-16", 39_950,
    )
    assert "무상증자 권리락" in facts.reason
    raw = bars(security, [
        ("2016-05-13", 0, 0, 0, 11_850, 0, 0, 0, 32_253_838),
        ("2016-05-16", 42_150, 44_400, 39_100, 39_100, -850, 237_283, 9_866_855_050, 6_450_767),
    ])
    event, = resolve(security, raw, [pricing], coverage_complete=True).resolutions
    assert event.kind == Resolution.SEGMENT_BREAK and event.review
    assert event.price_factor is None and event.volume_factor is None


def test_official_long_halt_auction_cannot_reset_on_a_zero_open_volume_bar():
    security = SecurityKey("224090", "KR7224090001", "2015-07-31", "2016-06-29", "KONEX", "common")
    notice, = actual_notices(security, "20160225000871")
    facts = notice.facts
    assert (facts.kind, facts.effective, facts.evaluation, facts.low, facts.high) == (
        "auction", "2016-02-26", 6_370, 3_185, 12_750,
    )
    raw = bars(security, [
        ("2016-02-25", 0, 0, 0, 6_370, 0, 0, 0, 4_390_000),
        ("2016-02-26", 0, 0, 0, 6_500, 0, 0, 0, 4_390_000),
    ])
    event, = resolve(security, raw, [notice], coverage_complete=True).resolutions
    assert event.kind == Resolution.SEGMENT_BREAK and event.review
    assert event.price_factor is None and event.volume_factor is None
