from dataclasses import replace
from datetime import date
from fractions import Fraction

import pandas as pd
import pytest
from shared.data.actions import FieldEvidence, reconcile
from shared.data.kind_market import KindBody, MarketFiling
from shared.data.market_notices import (
    Notice,
    NoticeSection,
    SecurityKey,
    match_notice,
    normal_company,
    parse_notice,
)
from shared.data.market_resolutions import NoticeFailure, Resolution
from shared.tests.test_market_resolutions import TEST_SOURCE, actual_notices, bars, resolve
from shared.tests.test_official_actions import FIXTURES, action_case, response


@pytest.fixture
def moa_data():
    security = SecurityKey("288980", "KR7288980006", "2022-03-10", None, "KOSDAQ", "common")
    raw = bars(security, [
        ("2026-11-10", 0, 0, 0, 204, 0, 0, 0, 37_523_583),
        ("2026-11-11", 880, 890, 714, 714, -306, 1_311_203, 977_894_432, 7_504_716),
    ])
    accession = "20261110000803"
    listing = Notice(
        security, accession, "70764", "2026-11-10", "28898", "변경상장(액면변경)",
        NoticeSection(1, "listing", "모아데이타", "보통주", "2026-11-11", "액면병합",
                      par_before=500, par_after=2500, shares_after=7_504_716),
        (TEST_SOURCE,), accession, (), True,
    )
    return security, raw, listing


def test_fractional_share_consolidation_keeps_only_whole_shares(moa_data):
    security, raw, listing = moa_data
    event, = resolve(security, raw, [listing], coverage_complete=True).resolutions
    assert (event.kind, event.price_factor, event.volume_factor, event.review, event.failed_check) == (
        Resolution.UNIT_CHANGE, 5, Fraction(1, 5), False, "",
    )
    raw.loc[0, "ListedShares"] += 5
    mismatch, = resolve(security, raw, [listing], coverage_complete=True).resolutions
    assert (mismatch.kind, mismatch.review, mismatch.failed_check) == (
        Resolution.SEGMENT_BREAK, True, "par_shares_mismatch",
    )


def test_compound_reference_reports_the_price_conflict_before_missing_listing():
    security = SecurityKey("123420", "KR7123420002", "2010-11-10", None, "KOSDAQ", "common")
    raw = bars(security, [
        ("2016-05-13", 0, 0, 0, 11_850, 0, 0, 0, 32_253_838),
        ("2016-05-16", 42_150, 44_400, 39_100, 39_100, -850, 237_283, 9_866_855_050, 6_450_767),
    ])
    pricing = actual_notices(security, "20160513000766")
    event, = resolve(security, raw, pricing, coverage_complete=True).resolutions
    assert (event.kind, event.review, event.failed_check) == (
        Resolution.SEGMENT_BREAK, True, "par_combined_reference",
    )


def test_differential_reduction_reports_the_krx_share_mismatch():
    security = SecurityKey("000040", "KR7000040006", "2016-01-01", None, "KOSPI", "common")
    raw = bars(security, [
        ("2018-01-11", 0, 0, 0, 325, 0, 0, 0, 188_265_520),
        ("2018-01-12", 489, 635, 489, 635, 146, 20_035_740, 12_451_534_414, 119_759_667),
    ])
    auction = Notice(
        security, "20180111000001", "99328", "2018-01-11", "00004", "자본감소에 따른 기준가격결정방법 안내",
        NoticeSection(1, "auction", "KR모터스", "보통주", "2018-01-12", "자본감소",
                      evaluation=487, low=244, high=730),
        (TEST_SOURCE,), "20180111000001", (), True,
    )
    listing = replace(
        auction, accession="20180111000002", form="68155", title="변경상장(자본감소)", document_no="20180111000002",
        facts=NoticeSection(1, "listing", "KR모터스", "보통주", "2018-01-12", "감자(주식병합)",
                            shares_before=188_265_520, shares_after=119_759_667),
    )
    event, = resolve(security, raw, [auction, listing], coverage_complete=True).resolutions
    assert (event.kind, event.reason, event.review, event.failed_check) == (
        Resolution.SEGMENT_BREAK, "official_facts_conflict_or_lack_terms", True, "reduction_shares_mismatch",
    )
    assert event.price_factor is None and event.volume_factor is None


def test_notice_failure_reports_check_and_keeps_evidence(moa_data):
    security, raw, listing = moa_data
    evidence = FieldEvidence("20261110000803", TEST_SOURCE, "KIND notice awaiting review")
    failure = NoticeFailure((evidence,), "unsupported_form:70768")
    event, = resolve(security, raw, [listing], coverage_complete=True,
                     unparsed_dates={"2026-11-11": [failure]}).resolutions
    assert (event.kind, event.reason, event.review, event.failed_check) == (
        Resolution.SEGMENT_BREAK, "official_notice_format_requires_review", True, "unsupported_form:70768",
    )
    assert evidence in event.evidence


@pytest.mark.parametrize("after", [7, 8])
def test_fractional_share_split_cannot_round_the_issued_share_count(moa_data, after):
    security, _, listing = moa_data
    raw = bars(security, [
        ("2026-11-10", 0, 0, 0, 100, 0, 0, 0, 3),
        ("2026-11-11", 40, 50, 35, 40, 0, 100, 4000, after),
    ])
    listing = replace(listing, facts=replace(listing.facts, reason="액면분할", par_before=500,
                                            par_after=200, shares_after=after))
    event, = resolve(security, raw, [listing], coverage_complete=True).resolutions
    assert (event.kind, event.review, event.failed_check) == (Resolution.SEGMENT_BREAK, True, "par_shares_mismatch")


@pytest.mark.parametrize("code, day, listing, form, auction, expected_kind, factor", [
    ("004920", "2020-03-20", "20200317000810", "68155", "20200319001024", Resolution.UNIT_CHANGE, Fraction(3)),
    ("003410", "2020-12-04", "20201201000101", "68151", "20201203000329", Resolution.REFERENCE_RESET, Fraction(1)),
])
def test_kind_only_reduction_matches_the_dart_factors(code, day, listing, form, auction, expected_kind, factor):
    official_security, decisions, implementation, sessions, auctions = action_case(code)
    security = SecurityKey(code, official_security.isin, official_security.listing, None, "KOSPI", "common")
    raw = pd.read_csv(FIXTURES / f"{code}_2020.csv", comment="#", parse_dates=["Date"])
    raw = raw.loc[raw.Date.le(day)].tail(2).reset_index(drop=True)
    notices = []
    for accession, notice_form, title in (
        (listing, form, "변경상장(감자)"),
        (auction, "99328", "자본감소에 따른 기준가격결정방법 안내"),
    ):
        capture = response(f"{accession}.notice.html")
        body = KindBody(capture.body, capture.charset, capture.evidence, accession, (accession,), True)
        source = MarketFiling(accession, date.fromisoformat(accession[:8]), title, TEST_SOURCE)
        facts, = parse_notice(source, notice_form, body)
        notices.append(match_notice(source, notice_form, facts, body, (capture.evidence,),
                                    {security: {normal_company(facts.company)}}))

    row, = resolve(security, raw, notices, coverage_complete=True).resolutions
    expected = expected_kind, factor, 1 / factor, False, ""
    assert (row.kind, row.price_factor, row.volume_factor, row.review, row.failed_check) == expected
    actions, pending = reconcile(official_security, decisions, [implementation], "2020-01-01", "2020-12-31",
                                 sessions, auctions)
    assert not pending
    dart, = resolve(security, raw, notices, actions=actions, coverage_complete=True).resolutions
    assert dart.reason == "verified_dart_and_kind_action"
    assert (dart.kind, dart.price_factor, dart.volume_factor, dart.review, dart.failed_check) == expected

    raw.loc[1, "RawOpen"] += 1
    mismatch, = resolve(security, raw, notices, coverage_complete=True).resolutions
    assert (mismatch.kind, mismatch.review, mismatch.failed_check) == (
        Resolution.SEGMENT_BREAK, True, "reduction_opening_auction_mismatch",
    )
