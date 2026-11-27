import gzip
import hashlib
import json
from dataclasses import replace
from datetime import date
from fractions import Fraction
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock

import pandas as pd
import pytest
from requests.exceptions import ChunkedEncodingError, ConnectionError, ReadTimeout
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
from shared.data.market_notices import (
    SecurityKey,
    auction_identity_witness,
    match_notice,
    normal_company,
    parse_notice,
    superseded_merger_facts,
)
from shared.data.market_resolutions import (
    NoticeFailure,
    Resolution,
    adjustment_events,
    issuer_merger_boundaries,
    raw_window_fingerprint,
    resolve_events,
    role_correction_windows,
    structural_closure,
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


def official_body(accession):
    info = SOURCES[accession]
    body = gzip.decompress((FIXTURES / f"{accession}.html.gz").read_bytes())
    assert hashlib.sha256(body).hexdigest() == info["sha256"]
    published = date.fromisoformat(f"{accession[:4]}-{accession[4:6]}-{accession[6:8]}")
    source = Evidence(info["sha256"], "c" * 64)
    response = KindBody(body, info["charset"], source, info["document_no"], tuple(info["family"]), info["final"])
    return MarketFiling(accession, published, info["title"], TEST_SOURCE, company=info["company"]), info["form"], response


def actual_notices(security, *accessions, aliases=()):
    notices = []
    for accession in accessions:
        filing, form, response = official_body(accession)
        scope = {security: {normal_company(name) for name in (filing.company, *aliases)}}
        notices.extend(match_notice(filing, form, facts, response, (response.evidence,), scope)
                       for facts in parse_notice(filing, form, response))
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
                        unparsed_dates={"2018-03-07": [NoticeFailure((unparsable,), "notice_parse_failed")]}).resolutions
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


@pytest.mark.parametrize("accession,record,shares,added,ratio", [
    ("20161212000116", "2016-12-31", 37_387_521, 7_176_963, "0.20"),
    ("20161213000252", "2016-12-31", 15_378_717, 1_512_065, "0.10"),
    ("20161215000330", "2016-12-31", 85_000_000, 8_500_000, "0.10"),
    ("20161215000596", "2016-12-31", 21_646_800, 216_468, "0.01"),
    ("20161215001046", "2016-12-30", 8_881_471, 85_925, "0.01"),
    ("20161215001212", "2016-12-31", 2_294_311, 41_475, "0.025"),
])
def test_legacy_stock_dividend_reads_explicit_proposal_terms(accession, record, shares, added, ratio):
    filing, form, body = official_body(accession)
    assert form == "61474" and body.final
    facts, = parse_notice(filing, form, body)
    assert (facts.kind, facts.company, facts.share_label, facts.listing) == (
        "dividend_terms", filing.company, "보통주식", None)
    assert (facts.effective, facts.shares_before, facts.added_shares, facts.ratio) == (
        record, shares, added, Fraction(ratio))


def test_final_legacy_dividend_proposal_alone_cannot_adjust_prices():
    security = SecurityKey("003000", "KR7003000007", "1988-08-05", None, "KOSPI", "common")
    raw = bars(security, [
        ("2016-12-27", 31000, 31000, 30200, 31000, 50, 393929, 12_140_001_200, 37_387_521),
        ("2016-12-28", 26550, 26650, 25700, 25800, -250, 265425, 6_931_590_350, 37_387_521),
    ])
    proposal, = actual_notices(security, "20161212000116")
    row, = resolve(security, raw, [proposal], coverage_complete=True).resolutions
    assert (row.kind, row.review, row.price_factor, row.volume_factor) == (Resolution.SEGMENT_BREAK, True, None, None)


@pytest.mark.parametrize("accession", ["20161216000832", "20161219000279", "20171215000527"])
def test_stock_dividend_rejects_subsidiary_terms_even_without_listing_caption(accession):
    filing, form, body = official_body(accession)
    for title in (filing.title, "주식배당결정"):
        with pytest.raises(DisclosureError, match="terms belong to a subsidiary"):
            parse_notice(replace(filing, title=title), form, body)


@pytest.mark.parametrize("accession,expected", [
    ("20230127000869", [("450140", "KR7450140009", "2023-01-31", "보통주", 62_777_250),
                        ("45014K", "KR745014K018", "2023-01-31", "1우선주", 2_456_120)]),
    ("20230329002563", [("452260", "KR7452260003", "2023-03-31", "보통주", 193_859_610),
                        ("45226K", "KR745226K018", "2023-03-31", "1우선주", 2_904_470)]),
    ("20230616000691", [("090460", "KR7090460007", "2023-06-20", "보통주", 34_464_379)]),
    ("20230804000334", [("030190", "KR7030190003", "2023-08-08", "보통주", 60_714_820)]),
])
def test_numbered_new_listing_routes_preserve_exact_stock_identity(accession, expected):
    filing, form, body = official_body(accession)
    facts = parse_notice(filing, form, body)
    assert [row.section for row in facts] == list(range(1, len(expected) + 1))
    assert [(row.code, row.isin, row.effective, row.share_label, row.shares_after) for row in facts] == expected


def test_uncoded_auction_identity_requires_exact_final_listing_and_rename_sections():
    filing, form, body = official_body("20180104000369")
    auction, = parse_notice(filing, form, body)
    assert auction.code is auction.isin is None
    preferred = SecurityKey("006125", "KR7006121008", "1989-11-24", None, "KOSPI", "preferred")
    filing, listing_form, body = official_body("20180102000170")
    filing = replace(filing, company_id="00612")
    related = [match_notice(filing, listing_form, row, body, (body.evidence,), {preferred: set()})
               for row in parse_notice(filing, listing_form, body) if row.code == preferred.code]
    rename, listing = related
    assert auction_identity_witness(form, auction, "00612", True, related) == (listing, rename)
    assert not auction_identity_witness(form, auction, "00612", False, related)
    for altered in ([listing], [rename], [rename, listing, listing],
                    [rename, replace(listing, company_id="01232")],
                    [rename, replace(listing, final=False)],
                    [rename, replace(listing, facts=replace(listing.facts, effective="2018-01-04"))],
                    [rename, replace(listing, facts=replace(listing.facts, share_label="2우선주"))],
                    [rename, replace(listing, facts=replace(listing.facts, isin="KR7006120000"))],
                    [replace(rename, facts=replace(rename.facts, renamed_company="다른회사")), listing]):
        assert not auction_identity_witness(form, auction, "00612", True, altered)


def test_fixed_new_listing_price_checks_the_first_krx_base_without_a_price_candidate():
    security = SecurityKey("419540", "KR7419540000", "2022-10-18", None, "KOSDAQ", "common")
    notice, = actual_notices(security, "20221017000403")
    raw = bars(security, [("2022-10-18", 3470, 3870, 3470, 3870, 890, 9_494_166, 36_050_256_885, 21_175_308)])
    assert (notice.facts.kind, notice.facts.base) == ("listing_price", 2980)
    ledger = resolve(security, raw, [notice], coverage_complete=True)
    assert ledger.candidates == ledger.resolutions == ()
    with pytest.raises(DisclosureError, match="new-listing reference differs from the KRX base"):
        resolve(security, raw, [replace(notice, facts=replace(notice.facts, base=2985))], coverage_complete=True)


@pytest.mark.parametrize("accession,record,shares,added,ratio,listing", [
    ("20160419000452", "2016-05-04", 10_607_725, 3_182_146, "0.3", "2016-05-31"),
    ("20161109000570", "2016-11-29", 22_504_880, 45_009_760, "2", "2016-12-28"),
])
def test_final_bonus_correction_reads_only_the_operative_terms(accession, record, shares, added, ratio, listing):
    filing, form, body = official_body(accession)
    assert form == "11307" and body.final
    facts, = parse_notice(filing, form, body)
    assert (facts.kind, facts.share_label) == ("bonus_terms", "보통주식")
    assert (facts.effective, facts.shares_before, facts.added_shares, facts.ratio, facts.listing) == (
        record, shares, added, Fraction(ratio), listing)

    missing_declaration = body.text().replace("금융위원회 / 한국거래소 귀중", "정정 비교 안내").encode(body.charset)
    assert missing_declaration != body.body
    with pytest.raises(DisclosureError, match="lacks a unique operative declaration"):
        parse_notice(filing, form, replace(body, body=missing_declaration))


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


def test_issuer_merger_only_reaches_active_listing_windows_with_the_effective_session():
    common = SecurityKey("005720", "KR7005720008", "1987-12-19", None, "KOSPI", "common")
    preferred = SecurityKey("005725", "KR7005721006", "1989-09-23", None, "KOSPI", "preferred")
    relisted = replace(preferred, listing="2016-01-04")
    earlier = replace(preferred, delisting=relisted.listing)
    future = replace(preferred, listing="2018-01-02")
    other_issuer = replace(SAMSUNG, listing=common.listing)
    day = "2017-11-24"
    notice, = actual_notices(common, "20171123000384")
    notice = replace(notice, company_id="00572")
    windows = {common, relisted, earlier, future, other_issuer}

    def has_session(key, day):
        return key in windows and day == "2017-11-24"

    assert issuer_merger_boundaries([notice], windows, has_session) == {relisted: {day: [notice]}}
    issuer_windows = windows - {other_issuer}
    assert structural_closure([notice], issuer_windows, has_session) == ({common, relisted}, {common, relisted})
    assert not issuer_merger_boundaries([notice], windows, lambda key, _: key != relisted)
    for excluded in (replace(notice, final=False), replace(notice, company_id="01014"),
                     replace(notice, facts=replace(notice.facts, reason="인적분할"))):
        assert not issuer_merger_boundaries([excluded], windows, has_session)


def test_initial_listing_correction_only_closes_the_exact_original_market_window():
    original = SecurityKey("388610", "KR7388610008", "2022-12-23", "2025-06-30", "KONEX", "common")
    later = replace(original, listing="2025-06-30", delisting=None, market="KOSDAQ")
    filing, form, body = official_body("20221220000314")
    filing = replace(filing, company_id="38861", submitter="코스닥시장본부")
    start, = parse_notice(filing, form, body)
    final, = actual_notices(original, "20221220000503")
    final = replace(final, company_id=filing.company_id)
    assert start.shares_after == 1_036_526

    def has_session(key, day):
        return day == key.listing

    keys = {original, later}
    assert role_correction_windows(filing, form, [start], [final], keys, has_session) == {original}
    with pytest.raises(DisclosureError, match="source role or listing window"):
        role_correction_windows(filing, form, [start], [replace(final, security=later)], keys, has_session)
    with pytest.raises(DisclosureError, match="source role or listing window"):
        role_correction_windows(filing, form, [replace(start, shares_after=1)], [final], keys, has_session)


def test_nonfinal_merger_review_reads_only_reconcilable_two_rounds_and_same_identity():
    filing, form, body = official_body("20201116000323")
    filing = replace(filing, submitter="유가증권시장본부", company_id="00509")
    facts = superseded_merger_facts(filing, form, body)
    assert (facts.code, facts.isin, facts.effective, facts.added_shares, facts.shares_after) == (
        "005090", "KR7005090006", "2020-11-19", 9_822_586, 14_677_004)
    for old, wrong in [(b"9,822,586", b"9,822,587"), (b"4,841,814", b"4,841,815"),
                       (b"A005090", b"A006120"), ("분할합병".encode(), "유상증자".encode())]:
        altered = body.body.replace(old, wrong, 1)
        assert altered != body.body
        with pytest.raises(DisclosureError, match="KIND structural review|KIND additional listing quantity"):
            superseded_merger_facts(filing, form, replace(body, body=altered))


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


@pytest.mark.parametrize("status", [403, 429])
def test_kind_access_rejection_stops_further_live_requests(tmp_path, status):
    class Rejected:
        status_code = status

        def __enter__(self):
            return self

        def __exit__(self, *_):
            pass

    class Session:
        def request(self, *_args, **_kwargs):
            return Rejected()

    client = KindMarket(tmp_path, budget=3, session=Session())
    with pytest.raises(KindUnavailable, match=str(status)):
        client.day(date(2016, 1, 1))
    with pytest.raises(KindUnavailable, match="stopped"):
        client.day(date(2016, 1, 2))
    assert client.calls == 1
    call = json.loads((tmp_path / "calls.jsonl").read_text())
    assert call["status"] == status


def test_kind_transport_failure_limit_keeps_cache_and_allows_a_new_run(tmp_path, monkeypatch):
    now, starts, sleeps = 0.0, [], []

    def advance(seconds):
        nonlocal now
        now += seconds

    def sleep(seconds):
        sleeps.append(seconds)
        advance(seconds)

    monkeypatch.setattr("shared.data.kind_market.time", SimpleNamespace(monotonic=lambda: now, sleep=sleep))
    complete = MagicMock(status_code=200, headers={})
    complete.__enter__.return_value = complete
    partial = MagicMock(status_code=200, headers={})
    partial.__enter__.return_value = partial
    body_delays = iter([0.8, 0.1, 0])

    def full_body(_chunk_size):
        advance(next(body_delays))
        return ["조회된 결과값이 없습니다. 전체 <em>0</em>건 : <strong>1</strong>/1".encode()]

    def broken_body(_chunk_size):
        advance(0.2)
        raise ChunkedEncodingError("fake secret in partial response")

    complete.iter_content.side_effect = full_body
    partial.iter_content.side_effect = broken_body
    results = iter([
        (0.1, ReadTimeout("fake secret in timeout")), (0.8, ConnectionError("fake secret in connection")),
        (0, complete), (0, complete), (0.1, ReadTimeout()), (0, partial), (0, ConnectionError()), (0, complete),
    ])

    def respond(*_args, **_kwargs):
        starts.append(now)
        seconds, result = next(results)
        advance(seconds)
        if isinstance(result, Exception):
            raise result
        return result

    request = Mock(side_effect=respond)
    session = Mock(request=request)
    client = KindMarket(tmp_path, budget=10, session=session)
    for day in (1, 2):
        with pytest.raises(KindUnavailable, match="network request failed"):
            client.day(date(2016, 1, day))
    cached_day = date(2016, 1, 3)
    saved = client.day(cached_day)
    assert client.day(date(2016, 1, 4))[0] == []
    for day in (5, 6):
        with pytest.raises(KindUnavailable, match="network request failed"):
            client.day(date(2016, 1, day))
    assert client.day(cached_day) == saved
    with pytest.raises(KindUnavailable, match="network request failed"):
        client.day(date(2016, 1, 7))

    with pytest.raises(KindUnavailable, match="stopped"):
        client.day(date(2016, 1, 8))
    assert client.day(cached_day) == saved
    assert request.call_count == client.calls == 7 and client.remaining == 3
    assert starts == pytest.approx([0, 0.6, 1.4, 2.2, 2.8, 3.4, 4.0])
    assert sleeps == pytest.approx([0.5, 0.5, 0.5, 0.4])

    resumed = KindMarket(tmp_path, budget=1, session=session)
    assert resumed.day(cached_day) == saved
    assert resumed.day(date(2016, 1, 8))[0] == []
    with pytest.raises(KindUnavailable, match="budget exhausted"):
        resumed.day(date(2016, 1, 9))
    assert request.call_count == 8 and resumed.calls == 1 and resumed.remaining == 0
    assert starts[-1] == pytest.approx(4.0)
    assert sleeps == pytest.approx([0.5, 0.5, 0.5, 0.4])

    log = (tmp_path / "calls.jsonl").read_text()
    assert "fake secret" not in log
    calls = [json.loads(line) for line in log.splitlines()]
    assert [call["status"] for call in calls] == [None, None, 200, 200, None, 200, None, 200]
    assert [call.get("error_type") for call in calls] == [
        "ReadTimeout", "ConnectionError", None, None, "ReadTimeout", "ChunkedEncodingError", "ConnectionError", None,
    ]


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
        ("20160706000436", SecurityKey("034830", "KR7034830000", "2016-07-11", None, "KOSPI", "common"), 252_489_230),
        ("20160804000125", SecurityKey("248170", "KR7248170003", "2016-08-09", None, "KOSPI", "common"), 4_568_286),
        ("20160826000199", SecurityKey("249420", "KR7249420001", "2016-08-31", None, "KOSPI", "common"), 17_845_253),
        ("20170502000545", SecurityKey("267270", "KR7267270007", "2017-05-10", None, "KOSPI", "common"), 3_584_046),
        ("20170518000349", SecurityKey("268280", "KR7268280005", "2017-05-22", None, "KOSPI", "common"), 5_179_111),
        ("20210702000621", SecurityKey("097520", "KR7097520001", "2021-07-06", None, "KOSPI", "common"), 17_863_482),
    ],
)
def test_official_new_and_relisting_forms_keep_exact_identity_and_session(accession, security, shares):
    notice, = actual_notices(security, accession)
    facts = notice.facts
    assert (facts.kind, facts.isin, facts.code) == ("new_listing", security.isin, security.code)
    assert (facts.effective, facts.share_label, facts.shares_after) == (security.listing, "보통주", shares)


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



def test_official_paid_rights_and_consolidation_reference_stays_unresolved():
    security = SecurityKey("103130", "KR7103130001", "2010-06-30", "2020-06-01", "KOSPI", "common")
    notice, = actual_notices(security, "20160829000348")
    assert (notice.facts.kind, notice.facts.effective, notice.facts.base) == ("listing_price", "2016-08-30", 8_450)
    assert notice.facts.reason == "권리락(유상증자), 액면병합"
    raw = bars(security, [
        ("2016-08-29", 0, 0, 0, 1_065, 0, 0, 0, 108_075_159),
        ("2016-08-30", 8_320, 10_950, 7_550, 8_840, 390, 2_152_679, 20_923_926_320, 10_807_515),
    ])
    event, = resolve(security, raw, [notice], coverage_complete=True).resolutions
    assert event.kind == Resolution.SEGMENT_BREAK and event.review
    assert event.price_factor is None and event.volume_factor is None


def test_official_additional_listing_reconciles_only_its_own_tranches():
    security = SecurityKey("050320", "KR7050320001", "2002-01-15", "2022-05-31", "KOSDAQ", "common")
    notice, = actual_notices(security, "20160829000468")
    facts = notice.facts
    assert (facts.effective, facts.code, facts.share_label) == ("2016-08-30", security.code, "보통주")
    assert (facts.added_shares, facts.shares_after) == (506_000, 10_097_141)
    raw = bars(security, [
        ("2016-08-29", 0, 0, 0, 14_850, 0, 0, 0, 9_591_141),
        ("2016-08-30", 3_510, 3_745, 3_160, 3_240, 270, 15_927_189, 56_080_852_895, 50_485_705),
    ])
    event, = resolve(security, raw, [notice], coverage_complete=True).resolutions
    assert event.kind == Resolution.SEGMENT_BREAK and event.review
    info = SOURCES[notice.accession]
    sample = gzip.decompress((FIXTURES / f"{notice.accession}.html.gz").read_bytes()).decode(info["charset"])
    assert "10,097,141" in sample
    malformed = sample.replace("10,097,141", "10,097,142")
    filing = MarketFiling(notice.accession, date(2016, 8, 29), notice.title, TEST_SOURCE)
    with pytest.raises(DisclosureError, match="tranche totals do not reconcile"):
        parse_notice(filing, notice.form, Response(malformed.encode(), "utf-8", TEST_SOURCE))


def test_official_konex_rights_form_matches_krx_and_changes_price_only():
    security = SecurityKey("229480", "KR7229480009", "2016-06-10", "2019-06-10", "KONEX", "common")
    notice, = actual_notices(security, "20161026000294")
    facts = notice.facts
    assert (facts.kind, facts.code, facts.effective, facts.base) == ("ex_price", "229480", "2016-10-27", 4_510)
    raw = bars(security, [
        ("2016-10-26", 4_300, 4_550, 4_300, 4_550, -440, 241, 1_036_550, 10_344_680),
        ("2016-10-27", 5_000, 5_000, 5_000, 5_000, 490, 1, 5_000, 10_344_680),
    ])
    event, = resolve(security, raw, [notice], coverage_complete=True).resolutions
    assert (event.kind, event.price_factor, event.volume_factor) == (Resolution.RIGHTS, Fraction(451, 455), 1)
    adjusted = apply_events(raw, adjustment_events([event]))
    assert adjusted.Close.tolist() == [4_510, 5_000]
    assert adjusted.Volume.tolist() == raw.RawVolume.tolist()


def test_official_99311_stock_dividend_price_requires_independent_allocation_terms():
    security = SecurityKey("004840", "KR7004840005", "1976-05-21", None, "KOSPI", "common")
    notice, = actual_notices(security, "20161227000637")
    facts = notice.facts
    assert (facts.kind, facts.effective, facts.share_label, facts.base, facts.reason) == (
        "ex_price", "2016-12-28", "보통주식", 12_950, "주식배당",
    )
    assert facts.ratio is None
    raw = bars(security, [
        ("2016-12-27", 12_850, 13_250, 12_850, 13_250, 300, 40_023, 525_040_500, 18_510_000),
        ("2016-12-28", 12_800, 12_900, 12_700, 12_750, -200, 13_857, 176_802_300, 18_510_000),
    ])
    event, = resolve(security, raw, [notice], coverage_complete=True).resolutions
    assert event.kind == Resolution.SEGMENT_BREAK and event.review
    assert event.price_factor is None and event.volume_factor is None


def test_official_numbered_merger_rounds_split_common_and_preferred_without_price_candidates():
    common = SecurityKey("051910", "KR7051910008", "2001-04-25", None, "KOSPI", "common")
    preferred = SecurityKey("051915", "KR7051911006", "2001-04-25", None, "KOSPI", "preferred")
    accession = "20170112000046"
    info = SOURCES[accession]
    archived = gzip.decompress((FIXTURES / f"{accession}.html.gz").read_bytes())
    assert hashlib.sha256(archived).hexdigest() == info["sha256"]
    source = Evidence(info["sha256"], "c" * 64)
    body = KindBody(archived, info["charset"], source, info["document_no"], tuple(info["family"]), info["final"])
    filing = MarketFiling(accession, date(2017, 1, 12), info["title"], TEST_SOURCE, company=info["company"])
    listing = parse_notice(filing, info["form"], body)
    assert [(facts.share_label, facts.effective, facts.code, facts.isin, facts.added_shares) for facts in listing] == [
        ("보통주", "2017-01-17", common.code, common.isin, 4_321_243),
        ("1우선주", "2017-01-17", preferred.code, preferred.isin, 59_879),
    ]
    observed = {
        common: [
            ("2017-01-16", 282_000, 283_500, 278_000, 278_500, -4_500, 198_568, 55_506_248_500, 66_271_100),
            ("2017-01-17", 278_000, 284_000, 276_000, 278_500, 0, 218_884, 61_049_828_500, 70_592_343),
        ],
        preferred: [
            ("2017-01-16", 190_000, 191_500, 187_000, 189_500, -500, 10_813, 2_038_075_500, 7_628_921),
            ("2017-01-17", 188_000, 190_000, 185_000, 187_000, -2_500, 7_501, 1_398_591_000, 7_688_800),
        ],
    }
    for facts in listing:
        notice = match_notice(filing, info["form"], facts, body, (source,), {common: {"lg화학"}, preferred: {"lg화학"}})
        ledger = resolve(notice.security, bars(notice.security, observed[notice.security]), [notice])
        assert ledger.candidates == ()
        event, = ledger.resolutions
        assert event.kind == Resolution.SEGMENT_BREAK and event.date == "2017-01-17" and not event.review


def test_official_relisting_keeps_separate_numbered_common_and_preferred_blocks():
    accession = "20170406000265"
    info = SOURCES[accession]
    archived = gzip.decompress((FIXTURES / f"{accession}.html.gz").read_bytes())
    assert hashlib.sha256(archived).hexdigest() == info["sha256"]
    source = Evidence(info["sha256"], "c" * 64)
    body = KindBody(archived, info["charset"], source, info["document_no"], tuple(info["family"]), info["final"])
    filing = MarketFiling(accession, date(2017, 4, 6), info["title"], TEST_SOURCE, company=info["company"])
    sections = parse_notice(filing, info["form"], body)
    assert [(f.kind, f.code, f.isin, f.share_label, f.effective, f.shares_after) for f in sections] == [
        ("new_listing", "264900", "KR7264900002", "보통주", "2017-04-11", 12_523_850),
        ("new_listing", "26490K", "KR726490K013", "종류주식", "2017-04-11", 773_560),
    ]


def test_official_same_class_merger_total_matches_round_quantities_and_requires_reconciliation():
    security = SecurityKey("213500", "KR7213500002", "2015-01-26", None, "KOSPI", "common")
    notice, = actual_notices(security, "20170310000088")
    assert (notice.facts.kind, notice.facts.reason, notice.facts.effective, notice.facts.added_shares) == (
        "listing", "합병", "2017-03-15", 3_664_067,
    )
    info = SOURCES[notice.accession]
    original = gzip.decompress((FIXTURES / f"{notice.accession}.html.gz").read_bytes())
    tampered = original.replace(b"3,664,067", b"3,664,068")
    filing = MarketFiling(notice.accession, date(2017, 3, 10), info["title"], TEST_SOURCE, company=info["company"])
    with pytest.raises(DisclosureError, match="quantity total does not reconcile"):
        parse_notice(filing, info["form"], Response(tampered, info["charset"], TEST_SOURCE))


def test_official_lockup_quantity_does_not_duplicate_additional_listing_shares():
    security = SecurityKey("004740", "KR7004740007", "1988-09-30", None, "KOSPI", "common")
    notice, = actual_notices(security, "20170411000107")
    assert (notice.facts.kind, notice.facts.reason, notice.facts.effective, notice.facts.added_shares) == (
        "listing", "유상증자(제3자배정)", "2017-04-12", 3_170_612,
    )


def test_official_merger_without_a_quantity_colon_retains_both_security_sections():
    filing, form, raw = official_body("20160118000186")
    assert [(f.section, f.code, f.isin, f.share_label, f.effective, f.added_shares)
            for f in parse_notice(filing, form, raw)] == [
        (1, "145990", "KR7145990008", "보통주", "2016-01-21", 4_153_184),
        (2, "145995", "KR7145991006", "우선주", "2016-01-21", 205_390),
    ]


@pytest.mark.parametrize("accession,effective,common,preferred", [
    ("20200519000452", "2020-05-21", ("353200", "KR7353200009", "보통주", 49_416_925),
     ("35320K", "KR735320K011", "우선주", 2_095_519)),
    ("20200918000556", "2020-09-22", ("363280", "KR7363280009", "보통주", 37_500_902),
     ("36328K", "KR736328K013", "1우선주", 1_255_338)),
    ("20210121000538", "2021-01-25", ("375500", "KR7375500006", "보통주", 19_358_738),
     ("37550K", "KR737550K011", "1우선주", 2_113_885)),
    ("20210525000477", "2021-05-27", ("383800", "KR7383800000", "보통주", 76_280_690),
     ("38380K", "KR738380K012", "1우선주", 1_465_285)),
])
def test_official_relisting_and_preferred_initial_listing_share_one_dated_notice(accession, effective, common, preferred):
    filing, form, body = official_body(accession)
    facts = parse_notice(filing, form, body)
    assert [(row.section, row.kind, row.effective) for row in facts] == [
        (1, "new_listing", effective), (2, "new_listing", effective),
    ]
    assert [(row.code, row.isin, row.share_label, row.shares_after) for row in facts] == [common, preferred]


@pytest.mark.parametrize("accession,observed,added,expected", [
    ("20220224001140", [("2022-02-24", 0, 0, 0, 108, 0, 0, 0, 174_440_126),
                       ("2022-02-25", 0, 0, 0, 1335, 0, 0, 0, 13_601_878)], 11_800_000, Resolution.SEGMENT_BREAK),
    ("20220303000948", [("2022-03-03", 0, 0, 0, 1335, 0, 0, 0, 13_601_878),
                       ("2022-03-04", 0, 0, 0, 1335, 0, 0, 0, 32_801_878)], 19_200_000, Resolution.SHARES_ONLY),
])
def test_official_additional_listing_total_alias_keeps_actual_krx_reconciliation(accession, observed, added, expected):
    security = SecurityKey("141020", "KR7141020008", "2013-01-29", "2024-01-03", "KOSDAQ", "common")
    listing, = actual_notices(security, accession)
    facts = listing.facts
    assert (facts.code, facts.share_label, facts.effective, facts.added_shares, facts.shares_after) == (
        security.code, "보통주", observed[-1][0], added, observed[-1][-1],
    )
    event, = resolve(security, bars(security, observed), [listing], coverage_complete=True).resolutions
    assert (event.kind, event.review, event.price_factor, event.volume_factor) == (
        expected, expected == Resolution.SEGMENT_BREAK, None, None,
    )


def test_official_additional_listing_total_alias_still_rejects_unreconciled_tranches():
    filing, form, body = official_body("20220303000948")
    altered = body.body.replace(b"32,801,878", b"32,801,879", 1)
    assert altered != body.body
    with pytest.raises(DisclosureError, match="tranche totals do not reconcile"):
        parse_notice(filing, form, replace(body, body=altered))


@pytest.mark.parametrize("accession,code,isin,effective,added", [
    ("20200515002607", "145210", "KR7145210001", "2020-05-20", 5_519_167),
    ("20200515002809", "145210", "KR7145210001", "2020-05-20", 5_519_167),
    ("20200521000228", "145210", "KR7145210001", "2020-05-26", 12_602_499),
    ("20201116000173", "007630", "KR7007630007", "2020-11-19", 5_000_140),
    ("20210106000089", "007630", "KR7007630007", "2021-01-11", 695_983),
    ("20210114000153", "012170", "KR7012170007", "2021-01-15", 25_011_036),
    ("20210409000126", "307950", "KR7307950006", "2021-04-14", 6_423_982),
    ("20211111000275", "161000", "KR7161000005", "2021-11-16", 16_608_709),
    ("20180411000675", "084670", "KR7084670009", "2018-04-17", 122_937),
])
def test_official_multi_round_or_corrected_additional_listing_keeps_one_operative_fact(accession, code, isin, effective, added):
    filing, form, body = official_body(accession)
    row, = parse_notice(filing, form, body)
    assert (row.code, row.isin, row.effective, row.added_shares) == (code, isin, effective, added)


def test_official_par_value_reduction_does_not_change_either_share_count():
    filing, form, body = official_body("20210805000135")
    facts = parse_notice(filing, form, body)
    assert [(f.section, f.code, f.isin, f.share_label, f.effective, f.shares_before, f.shares_after,
             f.par_before, f.par_after, f.reason) for f in facts] == [
        (1, "010140", "KR7010140002", "보통주", "2021-08-10", 630_000_000, 630_000_000, 5000, 1000, "액면가액 감액"),
        (2, "010145", "KR7010141000", "1우선주", "2021-08-10", 114_845, 114_845, 5000, 1000, "액면가액 감액"),
    ]


def test_official_single_class_par_value_reduction_keeps_its_existing_form():
    row, = parse_notice(*official_body("20201201000101"))
    assert (row.code, row.isin, row.effective, row.par_before, row.par_after, row.shares_after, row.reason) == (
        "003410", "KR7003410008", "2020-12-04", 1000, 100, 503_859_595, "감자(액면변경)",
    )


def test_official_split_binds_per_round_dates_to_both_real_security_paths():
    filing, form, raw = official_body("20170515000565")
    common = SecurityKey("013360", "KR7013360003", "1989-12-02", None, "KOSPI", "common")
    preferred = SecurityKey("013367", "KR7013362009", "1989-12-02", None, "KOSPI", "preferred")
    facts = parse_notice(filing, form, raw)
    assert [(f.section, f.code, f.effective, f.shares_before, f.shares_after) for f in facts] == [
        (1, common.code, "2017-05-18", 5_340_364, 53_403_640),
        (2, preferred.code, "2017-05-18", 62_124, 621_240),
    ]
    observed = {
        common: [("2017-05-17", 0, 0, 0, 15_950, 0, 0, 0, 5_340_364),
                 ("2017-05-18", 1750, 1780, 1355, 1370, -225, 10_852_930, 16_828_555_580, 53_403_640)],
        preferred: [("2017-05-17", 0, 0, 0, 104_000, 0, 0, 0, 62_124),
                    ("2017-05-18", 12_000, 12_450, 8750, 9580, -820, 645_289, 6_769_059_060, 621_240)],
    }
    for section in facts:
        notice = match_notice(filing, form, section, raw, (raw.evidence,), {common: set(), preferred: set()})
        event, = resolve(notice.security, bars(notice.security, observed[notice.security]), [notice]).resolutions
        assert (event.kind, event.price_factor, event.volume_factor, event.review) == (
            Resolution.UNIT_CHANGE, Fraction(1, 10), 10, False,
        )


@pytest.mark.parametrize("accession,security,observed", [
    ("20170704000174", SecurityKey("001800", "KR7001800002", "1975-06-27", None, "KOSPI", "common"), [
        ("2017-07-06", 0, 0, 0, 798_000, 0, 0, 0, 6_008_435),
        ("2017-07-07", 39_200, 42_000, 32_900, 32_900, -6300, 4_263_126, 157_721_013_850, 20_550_849),
    ]),
    ("20171130000199", SecurityKey("029460", "KR7029460003", "1997-11-25", None, "KOSPI", "common"), [
        ("2017-12-04", 0, 0, 0, 24_000, 0, 0, 0, 33_393_384),
        ("2017-12-05", 20_000, 25_600, 19_650, 23_200, 3200, 1_675_999, 39_106_596_300, 13_554_044),
    ]),
])
def test_official_surviving_division_takes_identity_and_date_only_from_the_common_section(accession, security, observed):
    notice, = actual_notices(security, accession)
    assert notice.facts.code == security.code and notice.facts.isin == security.isin
    assert notice.facts.shares_after is notice.facts.par_after is None
    event, = resolve(security, bars(security, observed), [notice]).resolutions
    assert (event.kind, event.date, event.reason, event.price_factor, event.volume_factor, event.review) == (
        Resolution.SEGMENT_BREAK, observed[-1][0], "official_division", None, None, False,
    )


@pytest.mark.parametrize("accession,old,new,reason", [
    ("20170518000349", "보통주 5,179,111주", "우선주 5,179,111주", "security identity differs"),
    ("20170515000565", "제27회 : 2017년05월18일", "제28회 : 2017년05월18일", "identities or dates differ"),
    ("20170704000174", "KR7001800002", "KR7001800000", "common identity is ambiguous"),
    ("20171025000484", "기명식 우선주 987,623주", "기명식 보통주 987,623주", "quantity does not match its class"),
    ("20190308000743", "더블유게임즈보통주", "다른게임즈보통주", "issuer differs from the publication list"),
    ("20190308000743", "KR7192080000", "KR7192080001", "numbered listing security identity differs"),
    ("20190430000089", "변경일자: 2019년05월02일", "변경일자: 2019년05월03일", "differs from the preceding split listing"),
    ("20191016000448", "- 보통주 14,406,898주", "- 우선주 14,406,898주", "numbered listing security identity differs"),
    ("20191015000306", "2019년 10월 18일", "2019년 10월 21일", "class relisting effective dates differ"),
    ("20191015000308", "두산퓨얼셀2우선주(신형)", "두산퓨얼셀3우선주(신형)", "numbered listing security identity differs"),
    ("20191015000308", "KR733626K021 (단축코드:A33626L)", "KR733626K013 (단축코드:A33626K)", "identifiers are duplicated"),
    ("20210525000477", "엘엑스홀딩스1우선주", "엘엑스홀딩스보통주", "numbered listing security identity differs"),
    ("20210525000477", "엘엑스홀딩스1우선주", "다른회사1우선주", "relisting issuer differs"),
    ("20210702000621", "수 - 보통주 17,863,482주", "수 - 우선주 17,863,482주", "numbered listing security identity differs"),
    ("20200515002809", "5,519,167주", "5,519,168주", "additional listing quantity total does not reconcile"),
    ("20201116000173", "제53회", "제52회", "additional listing quantity total does not reconcile"),
    ("20180411000675", "→ 2018년04월17일", "→ 2018년04월18일", "corrected listing date differs"),
    ("20210805000135", "114,845,000원", "114,845,001원", "par change capital does not reconcile"),
])
def test_official_text_variants_reject_conflicting_fields(accession, old, new, reason):
    filing, form, raw = official_body(accession)
    # Alter the normalized fields without depending on the source's exact HTML whitespace.
    from shared.data.market_notices import _document_text

    original = _document_text(raw.text())
    assert old in original
    with pytest.raises(DisclosureError, match=reason):
        parse_notice(filing, form, replace(raw, body=original.replace(old, new, 1).encode(), charset="utf-8"))


def test_quarterly_dividend_reference_rejects_ambiguous_official_effective_date():
    filing, form, raw = official_body("20190327001145")
    duplicated = raw.text().replace("2019-03-28", "2019-03-28 / 2019-03-29")
    assert duplicated != raw.text()
    with pytest.raises(DisclosureError, match="date"):
        parse_notice(filing, form, replace(raw, body=duplicated.encode(), charset="utf-8"))


def test_official_oqp_division_reference_applies_while_stock_is_still_halted():
    key = SecurityKey("078590", "KR7078590007", "2005-10-27", None, "KOSDAQ", "common")
    notice, = actual_notices(key, "20210823000471", aliases=("OQP",))
    assert (notice.facts.effective, notice.facts.kind, notice.facts.evaluation, notice.facts.low, notice.facts.high) == (
        "2021-08-24", "auction", 2380, 1190, 4760,
    )
    raw = bars(key, [("2021-08-23", 0, 0, 0, 3890, 0, 0, 0, 83_006_958),
                     ("2021-08-24", 0, 0, 0, 2380, 0, 0, 0, 83_006_958)])
    event, = resolve(key, raw, [notice]).resolutions
    assert (event.kind, event.reason, event.date, event.price_factor, event.volume_factor) == (
        Resolution.SEGMENT_BREAK, "official_division", "2021-08-24", None, None,
    )
    filing, form, body = official_body("20210823000471")
    altered = body.text().replace("정지가 계속됨", "정지가 해제됨")
    assert altered != body.text()
    with pytest.raises(DisclosureError, match="suspension terms differ"):
        parse_notice(filing, form, replace(body, body=altered.encode(), charset="utf-8"))
