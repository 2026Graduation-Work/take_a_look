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


@pytest.mark.parametrize("reason", ["감자(주식병합)", "감자(무상)"])
def test_differential_reduction_reports_the_krx_share_mismatch(reason):
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
        facts=NoticeSection(1, "listing", "KR모터스", "보통주", "2018-01-12", reason,
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


@pytest.fixture
def jnk_bonus():
    security = SecurityKey("126880", "KR7126880004", "2016-01-01", None, "KOSDAQ", "common")
    raw = bars(security, [
        ("2016-08-02", 6920, 6960, 6800, 6840, -60, 49_205, 337_845_670, 8_000_000),
        ("2016-08-03", 5990, 6430, 5360, 5390, 80, 424_333, 2_523_757_790, 8_000_000),
        ("2016-08-24", 4700, 4785, 4635, 4720, 20, 90_291, 426_705_470, 11_500_000),
        ("2016-08-25", 4680, 4740, 4645, 4660, -60, 153_064, 716_772_010, 14_823_466),
    ])
    ex_price, terms = actual_notices(security, "20160802000269", "20160722000097")
    return security, raw, ex_price, terms


def _bonus_ex_event(security, raw, notices):
    day = raw.Date.iloc[1].date().isoformat()
    ledger = resolve(security, raw, notices, coverage_complete=True)
    event, = (resolution for resolution in ledger.resolutions if resolution.date == day)
    return event


def test_combined_offering_bonus_keeps_the_krx_price_and_official_volume_ratio(jnk_bonus):
    security, raw, ex_price, terms = jnk_bonus
    row = _bonus_ex_event(security, raw, [ex_price, terms])
    assert (row.kind, row.reason, row.price_factor, row.volume_factor, row.review) == (
        Resolution.BONUS, "combined_offering_bonus_terms", Fraction(5310, 6840), Fraction(13, 10), False,
    )

    raw.loc[1, "RawChange"] += 180
    ex_price = replace(ex_price, facts=replace(ex_price.facts, base=5130))
    row = _bonus_ex_event(security, raw, [ex_price, terms])
    assert (row.kind, row.review, row.failed_check) == (
        Resolution.SEGMENT_BREAK, True, "combined_bonus_reference_price_mismatch",
    )


@pytest.fixture
def tess_bonus():
    security = SecurityKey("095610", "KR7095610002", "2016-01-01", None, "KOSDAQ", "common")
    raw = bars(security, [
        ("2016-04-12", 18800, 18900, 18000, 18900, 100, 233_758, 4_304_322_750, 10_542_387),
        ("2016-04-14", 13400, 15600, 12950, 13800, 1200, 719_583, 10_111_180_900, 10_542_387),
        ("2016-05-04", 13400, 13900, 12800, 13500, 300, 223_726, 3_013_133_850, 12_116_490),
        ("2016-05-09", 13300, 13900, 12900, 13000, -500, 435_890, 5_780_048_950, 18_174_030),
    ])
    notices = actual_notices(security, "20160412000324", "20160428000303")
    return security, raw, notices


def test_combined_offering_bonus_uses_the_corrected_listing_session(tess_bonus):
    security, raw, notices = tess_bonus
    row = _bonus_ex_event(security, raw, notices)
    assert (row.kind, row.price_factor, row.volume_factor, row.review) == (
        Resolution.BONUS, Fraction(2, 3), Fraction(3, 2), False,
    )

    row = _bonus_ex_event(security, raw.iloc[:-1], notices)
    assert (row.kind, row.review, row.failed_check) == (
        Resolution.SEGMENT_BREAK, True, "combined_bonus_listing_session_unavailable",
    )


def test_independent_standard_and_combined_bonus_terms_require_review(tess_bonus):
    security, raw, (ex_price, combined) = tess_bonus
    accession = "20160411000001"
    standard = replace(
        combined, accession=accession, document_no=accession, family=(), form="11307",
        facts=replace(combined.facts, shares_before=int(raw.ListedShares.iloc[0]),
                      paid_record_date=None, paid_listing=None),
    )
    row = _bonus_ex_event(security, raw, [ex_price, standard])
    assert (row.kind, row.reason, row.price_factor, row.volume_factor) == (
        Resolution.BONUS, "bonus_terms", Fraction(2, 3), Fraction(3, 2),
    )

    row = _bonus_ex_event(security, raw, [ex_price, combined, standard])
    assert (row.kind, row.review, row.failed_check) == (Resolution.SEGMENT_BREAK, True, "bonus_terms_ambiguous")
    assert row.price_factor is None and row.volume_factor is None


def test_conflicting_final_family_blocks_standard_and_combined_offering_terms(tess_bonus):
    security, raw, (ex_price, combined) = tess_bonus
    common_source, accession = "20160212001742", "20160411000001"
    combined = replace(combined, family=(common_source, combined.document_no))
    standard = replace(
        combined, accession=accession, document_no=accession, family=(common_source, accession), form="11307",
        facts=replace(combined.facts, shares_before=int(raw.ListedShares.iloc[0]),
                      paid_record_date=None, paid_listing=None),
    )
    row = _bonus_ex_event(security, raw, [ex_price, combined, standard])
    assert (row.kind, row.failed_check) == (Resolution.SEGMENT_BREAK, "correction_final_ambiguous")
    assert {combined.accession, standard.accession} <= {item.accession for item in row.evidence}


def test_combined_offering_bonus_rejects_same_record_day(jnk_bonus):
    security, raw, ex_price, terms = jnk_bonus
    terms = replace(terms, facts=replace(terms.facts, paid_record_date=terms.facts.effective))
    row = _bonus_ex_event(security, raw, [ex_price, terms])
    assert (row.kind, row.review, row.failed_check) == (
        Resolution.SEGMENT_BREAK, True, "combined_bonus_record_date_overlap",
    )


def test_combined_offering_bonus_requires_both_listing_tranches_on_same_day(jnk_bonus):
    security, raw, ex_price, terms = jnk_bonus
    terms = replace(terms, facts=replace(terms.facts, paid_listing=terms.facts.listing))
    row = _bonus_ex_event(security, raw, [ex_price, terms])
    assert (row.kind, row.review, row.failed_check) == (
        Resolution.SEGMENT_BREAK, True, "combined_bonus_listing_overlap_unproven",
    )

    raw.loc[2, "ListedShares"] = 8_000_000
    bonus = replace(
        terms, accession="20160823000001", form="68154",
        facts=NoticeSection(1, "listing", "제이엔케이히터", "보통주", "2016-08-25", "무상증자",
                            added_shares=3_323_466, shares_after=14_823_466),
    )
    paid = replace(
        bonus, accession="20160823000002",
        facts=replace(bonus.facts, reason="유상증자", added_shares=3_500_000),
    )
    row = _bonus_ex_event(security, raw, [ex_price, terms, bonus, paid])
    assert (row.kind, row.price_factor, row.volume_factor) == (
        Resolution.BONUS, Fraction(5310, 6840), Fraction(13, 10),
    )

    paid = replace(paid, facts=replace(paid.facts, shares_after=11_500_000))
    row = _bonus_ex_event(security, raw, [ex_price, terms, bonus, paid])
    assert (row.kind, row.review, row.failed_check) == (
        Resolution.SEGMENT_BREAK, True, "combined_bonus_listing_totals_mismatch",
    )


@pytest.mark.parametrize("case,check", [
    ("contradiction", "combined_bonus_listing_totals_mismatch"), ("sequential", ""),
    ("single", "combined_bonus_listing_totals_mismatch"),
])
def test_combined_offering_reconciles_explicit_listing_share_counts(jnk_bonus, case, check):
    security, raw, ex_price, terms = jnk_bonus
    bonus_prior = 11_500_000 if case != "single" else 11_500_001
    bonus = replace(terms, accession="20160823000001", form="68154", facts=NoticeSection(
        1, "listing", "제이엔케이히터", "보통주", "2016-08-25", "무상증자",
        added_shares=3_323_466, shares_before=bonus_prior, shares_after=14_823_466,
    ))
    listings = [bonus]
    if case != "single":
        terms = replace(terms, facts=replace(terms.facts, paid_listing=terms.facts.listing))
        raw.loc[2, "ListedShares"] = 8_000_000
        paid_before, paid_after = (11_323_466, 14_823_466) if case == "contradiction" else (8_000_000, 11_500_000)
        listings.append(replace(bonus, accession="20160823000002", facts=replace(
            bonus.facts, reason="유상증자", added_shares=3_500_000, shares_before=paid_before, shares_after=paid_after,
        )))
    event = _bonus_ex_event(security, raw, [ex_price, terms, *listings])
    assert event.failed_check == check
    assert event.kind == (Resolution.SEGMENT_BREAK if check else Resolution.BONUS)


def test_linked_standalone_final_terms_are_not_chosen_by_numeric_fit(jnk_bonus):
    security, raw, ex_price, terms = jnk_bonus
    common_source = "20160602000001"
    terms = replace(terms, family=(common_source, terms.document_no))
    alternative = replace(terms, accession="20160722000098", document_no="20160722000329",
                          family=(common_source, "20160722000329"), facts=replace(terms.facts, ratio=Fraction(3)))
    event = _bonus_ex_event(security, raw, [ex_price, terms, alternative])
    assert (event.kind, event.failed_check) == (Resolution.SEGMENT_BREAK, "correction_final_ambiguous")
