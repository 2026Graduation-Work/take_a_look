import json
from dataclasses import replace
from fractions import Fraction

import pytest
from shared.data.actions import FieldEvidence
from shared.data.market_notices import SecurityKey
from shared.data.market_resolutions import NoticeFailure, Resolution
from shared.tests.test_market_resolutions import (
    FIXTURES,
    TEST_SOURCE,
    actual_notices,
    bars,
    resolve,
)

CASES = json.loads((FIXTURES / "unpaid-reduction-cases.json").read_text())


@pytest.fixture(params=CASES, ids=lambda case: case["security"]["Code"])
def unpaid_reduction(request):
    case = request.param
    security = case["security"]
    key = SecurityKey(security["Code"], security["ISIN"], security["ListingDate"],
                      security["DelistingDate"] or None, security["Market"], security["ShareClass"])
    return key, bars(key, case["raw"]), actual_notices(key, *case["accessions"]), case


def test_unpaid_reduction_uses_the_existing_checks_on_archived_forms(unpaid_reduction):
    key, raw, notices, case = unpaid_reduction
    listing, = [notice for notice in notices if notice.facts.kind == "listing"]
    assert listing.facts.reason == "감자(무상)"
    assert listing.facts.shares_after == raw.ListedShares.iloc[-1]
    event, = resolve(key, raw, notices, coverage_complete=True).resolutions
    factor = Fraction(case["factor"])
    assert (event.kind.value, event.price_factor, event.volume_factor, event.review, event.failed_check) == (
        case["expected"], factor, 1 / factor, False, "",
    )


@pytest.mark.parametrize("exception,check", [
    ("paid", "reduction_reason_conflict"),
    ("mixed_listing", "reduction_reason_conflict"),
    ("differential_reason", "reduction_reason_conflict"),
    ("mixed_auction", "reduction_reason_conflict"),
    ("missing_listing", "reduction_notice_pair_missing"),
    ("shares", "reduction_shares_mismatch"),
    ("listing_shares", "reduction_notice_shares_mismatch"),
    ("evaluation", "reduction_evaluation_price_mismatch"),
    ("range", "reduction_opening_auction_mismatch"),
    ("opening", "reduction_opening_auction_mismatch"),
    ("volume", "reduction_opening_auction_mismatch"),
    ("not_final", "notice_not_final"),
    ("unparsed", "notice_parse_failed"),
])
def test_unpaid_reduction_keeps_exceptions_under_review(unpaid_reduction, exception, check):
    key, raw, notices, _ = unpaid_reduction
    listing_at, = [at for at, notice in enumerate(notices) if notice.facts.kind == "listing"]
    auction_at = 1 - listing_at
    listing, auction = notices[listing_at], notices[auction_at]
    if exception in {"paid", "mixed_listing", "differential_reason"}:
        reason = {"paid": "감자(유상)", "mixed_listing": "감자(무상),유상증자",
                  "differential_reason": "감자(무상,차등감자)"}[exception]
        notices[listing_at] = replace(listing, facts=replace(listing.facts, reason=reason))
    elif exception == "mixed_auction":
        notices[auction_at] = replace(auction, facts=replace(auction.facts, reason="자본감소,권리락"))
    elif exception == "missing_listing":
        notices = [auction]
    elif exception == "shares":
        raw.loc[1, "ListedShares"] -= 1
        notices[listing_at] = replace(listing, facts=replace(listing.facts, shares_after=int(raw.ListedShares.iloc[1])))
    elif exception == "listing_shares":
        notices[listing_at] = replace(listing, facts=replace(listing.facts, shares_after=int(raw.ListedShares.iloc[1]) + 1))
    elif exception == "evaluation":
        notices[auction_at] = replace(auction, facts=replace(auction.facts, evaluation=1))
    elif exception == "range":
        notices[auction_at] = replace(auction, facts=replace(auction.facts, high=int(raw.RawOpen.iloc[1]) - 1))
    elif exception == "opening":
        raw.loc[1, "RawOpen"] += 1
        raw.loc[1, "RawHigh"] = max(raw.RawHigh.iloc[1], raw.RawOpen.iloc[1])
    elif exception == "volume":
        raw.loc[1, ["RawOpen", "RawHigh", "RawLow", "RawVolume", "Amount"]] = 0
    elif exception == "not_final":
        notices = [replace(notice, final=False) for notice in notices]
    failures = {}
    if exception == "unparsed":
        evidence = FieldEvidence(auction.accession, TEST_SOURCE, "KIND notice awaiting review")
        failures[raw.Date.iloc[1].date().isoformat()] = [NoticeFailure((evidence,), "notice_parse_failed")]
    event, = resolve(key, raw, notices, coverage_complete=True, unparsed_dates=failures).resolutions
    assert (event.kind, event.review, event.failed_check, event.price_factor, event.volume_factor) == (
        Resolution.SEGMENT_BREAK, True, check, None, None,
    )
