from dataclasses import replace
from datetime import date
from fractions import Fraction
from pathlib import Path
from unittest.mock import Mock

import pandas as pd
import pytest
from experiments.dataset.census_actions import _collect_notices
from shared.data.disclosures import DisclosureError, Evidence
from shared.data.kind_market import KindBody, KindMarket, KindUnavailable, MarketFiling
from shared.data.market_notices import SecurityKey, parse_notice
from shared.data.market_resolutions import (
    Resolution,
    combined_bonus_observation,
    observe_candidates,
    resolve_events,
)
from shared.tests.test_market_resolutions import official_body

FIXTURES = Path(__file__).parents[2] / "shared/tests/fixtures/market_actions"
SECURITY = SecurityKey("126880", "KR7126880004", "2016-01-01", None, "KOSDAQ", "common")
EX_DAY = "2016-08-03"


def _additional_listing(number, amount, reason):
    evidence = Evidence(f"{number:064x}", f"{number + 100:064x}")
    accession = f"2016082400000{number}"
    filing = MarketFiling(accession, date(2016, 8, 24), f"추가상장({reason})", evidence,
                          company_id="12688", submitter="코스닥시장본부")
    rows = [
        ("1. 회사명", "제이엔케이히터"), ("2.추가주식의 종류와 수", "주권종류", "단축코드", "추가주식수(주)"),
        ("보통주", f"A{SECURITY.code}", f"{amount:,}"), ("3.1주당 액면가/자본금(원)", "500"),
        ("4.추가상장후 총발행주식수", "주권종류", "주식수(주)", "배당기산일"),
        ("보통주", "14,823,466", "2016-01-01"), ("5. 상장일", "2016-08-25"), ("6. 기타", "-"),
        ("【발행내역】",), ("보통주", reason, "-", f"{amount:,}", "500", "제1회"),
    ]
    text = "<table>" + "".join(
        "<tr>" + "".join(f"<td>{value}</td>" for value in row) + "</tr>" for row in rows
    ) + "</table>"
    return filing, "70791", KindBody(text.encode(), "utf-8", evidence, accession, (accession,), True)


@pytest.mark.parametrize("case,check,automated", [
    *((case, check, False) for case, check in [
    ("simple", ""), ("matched", ""), ("delta-only", ""), ("mismatch", "combined_bonus_listing_totals_mismatch"),
    ("unavailable", "combined_bonus_listing_source_missing"), ("invalid", "combined_bonus_listing_source_unverified"),
    ("extra-unavailable", "combined_bonus_listing_source_missing"),
    ("known-conflict", "combined_bonus_listing_shares_mismatch"),
    ("known-unavailable", "combined_bonus_listing_source_missing"),
    ("pure-unavailable", ""),
    ("withdrawn-unavailable", "combined_bonus_listing_source_unverified"),
    ("bad-terms", ""),
    ]),
    ("matched", "", True), ("unavailable", "combined_bonus_listing_source_missing", True),
])
def test_collects_additional_listings_only_when_needed_for_combined_bonus(case, check, automated):
    raw = pd.read_csv(FIXTURES / "126880.bonus-prices.csv.gz", dtype={"Code": str}).rename(columns={"MKT_NM": "Market"})
    raw["Date"] = pd.to_datetime(raw.Date)
    quote, quote_form, quote_body = official_body("20160802000269")
    term, term_form, term_body = official_body("20160722000097")
    overlap = case not in {"simple", "known-conflict", "known-unavailable", "pure-unavailable", "withdrawn-unavailable", "bad-terms"}
    if overlap:
        raw.loc[raw.Date.lt("2016-08-25"), "ListedShares"] = 8_000_000
    if overlap and case != "delta-only":
        source = term_body.body
        changed = source.replace("2016년 08월 18일".encode(), "2016년 08월 25일".encode())
        assert changed != source
        term_body = replace(term_body, body=changed)
    quote = replace(quote, company_id="12688", submitter="코스닥시장본부")
    term = replace(term, company_id="12688", submitter="제이엔케이히터")
    bonus = _additional_listing(1, 3_323_466, "무상증자")
    if case == "withdrawn-unavailable":
        bonus = replace(bonus[0], withdrawn=True), *bonus[1:]
    paid_amount = {"mismatch": 3_499_000, "known-conflict": 3_323_466}.get(case, 3_500_000)
    paid = _additional_listing(2, paid_amount, "유상증자")
    extra = _additional_listing(3, 1_000, "국내CB전환")
    additions = [bonus, paid, extra] if case == "extra-unavailable" else [bonus, paid]
    if case in {"simple", "bad-terms"}:
        additions = []
    if case in {"known-conflict", "known-unavailable"}:
        additions = [paid]
    if case in {"pure-unavailable", "withdrawn-unavailable"}:
        additions = [bonus]
    additional_filings = [notice[0] for notice in additions]
    expected_failure = {"extra-unavailable": extra[0], "pure-unavailable": bonus[0],
                        "withdrawn-unavailable": bonus[0]}.get(case, paid[0])
    documents = {row.accession: (form, body) for row, form, body in [(quote, quote_form, quote_body),
                                                                   (term, term_form, term_body), *additions]}
    other_filings = []
    if case == "bad-terms":
        bad = replace(term, accession="20160722000098")
        data = term_body.body.replace(b"0.3000000000", b"3.0000000000")
        data = data.replace("2016년 08월 25일".encode(), "2016년 08월 19일".encode())
        assert data != term_body.body
        documents[bad.accession] = (term_form, replace(term_body, body=data, document_no=bad.accession, family=(bad.accession,)))
        unneeded = replace(paid[0], published=date(2016, 8, 15))
        other_filings = [bad, unneeded]

    def document(filing, *, cache_only=False):
        assert cache_only == (filing in additional_filings and not automated)
        if (filing == expected_failure and case in {"unavailable", "extra-unavailable", "known-unavailable", "pure-unavailable",
                                                    "withdrawn-unavailable"}
                or case == "bad-terms" and filing == unneeded):
            raise KindUnavailable("KIND supplemental response is unavailable in cache")
        form, body = documents[filing.accession]
        if filing == paid[0] and case == "invalid":
            body = replace(body, body=b"malformed additional listing")
        return form, body, (body.evidence,)

    client = Mock(document=Mock(side_effect=document))
    days = pd.DatetimeIndex(raw.Date)
    candidates = observe_candidates(SECURITY, raw, days)
    assert [candidate.date for candidate in candidates] == [EX_DAY]
    notices, blocked, unparsed, structural_gaps, _, failures, *_ = _collect_notices(
        client, [term, quote, *additional_filings, *other_filings], {SECURITY: {"제이엔케이히터"}}, {SECURITY: candidates},
        anchors={}, spac_keys=set(), bounded=True, raw_prices={SECURITY: raw}, acquire_supplements=automated,
    )
    assert not blocked and not structural_gaps
    expected_calls = {"bad-terms": 3, "withdrawn-unavailable": 2}.get(case, 2 + len(additions))
    assert client.document.call_count == expected_calls
    ledger = resolve_events(SECURITY, raw, days, notices[SECURITY], coverage_complete=True,
                            unparsed_dates=unparsed[SECURITY])
    event, = ledger.resolutions
    assert event.failed_check == check
    assert event.kind == (Resolution.SEGMENT_BREAK if check else Resolution.BONUS)
    if case in {"unavailable", "invalid", "extra-unavailable", "known-unavailable", "withdrawn-unavailable"}:
        failure, = failures
        stage = "kind_document" if automated and case == "unavailable" else "kind_notice"
        assert (failure["Stage"], failure["FailedCheck"], failure["AcptNo"]) == (stage, check, expected_failure.accession)
        assert vars(expected_failure.evidence) in failure["Evidence"]
        assert expected_failure.evidence in {item.source for item in event.evidence}
        if case == "withdrawn-unavailable":
            assert "withdrawn or cancelled" in failure["Reason"]
    elif case == "pure-unavailable":
        failure, = failures
        assert failure["FailedCheck"] == "combined_bonus_listing_source_missing" and "CombinedBonusListing" not in failure
        assert not unparsed[SECURITY]
    else:
        assert failures == []


@pytest.mark.parametrize("malformed", ["row", "column"])
def test_additional_listing_rejects_unreadable_operative_rows_and_identity_columns(malformed):
    filing, form, body = _additional_listing(1, 3_323_466, "무상증자")
    if malformed == "row":
        source = "<tr><td>보통주</td><td>A126880</td>"
        changed = "<tr><td>미지원종류</td><td>A126880</td><td>1,000</td></tr>" + source
    else:
        source = "<td>단축코드</td><td>추가주식수(주)</td>"
        changed = "<td>단축코드</td><td>단축코드</td><td>추가주식수(주)</td>"
    with pytest.raises(DisclosureError, match="KIND additional listing"):
        parse_notice(filing, form, replace(body, body=body.body.replace(source.encode(), changed.encode(), 1)))


def test_supplemental_acquisition_cannot_make_a_network_request_with_budget(tmp_path):
    session = Mock()
    market = KindMarket(tmp_path, budget=1, session=session)
    filing, *_ = _additional_listing(1, 3_323_466, "무상증자")
    with pytest.raises(KindUnavailable, match="unavailable in cache"):
        market.document(filing, cache_only=True)
    assert market.calls == 0 and market.remaining == 1
    session.request.assert_not_called()


@pytest.mark.parametrize("case,listing,published", [
    ("ratio", "2016년 04월 18일", "2016-04-18"),
    ("record-date", "2016년 04월 20일", "2016-04-20"),
    ("record-overlap", "2016년 04월 18일", "2016-04-18"),
    ("equal-listing", "2016년 04월 15일", "2016-04-18"),
    ("listing-absent", "2016년 04월 23일", "2016-04-22"),
    ("nonconsecutive", "2016년 04월 22일", "2016-04-22"),
    ("shares-changed", "2016년 04월 22일", "2016-04-22"),
])
def test_invalid_combined_term_never_requests_additional_proof_for_an_independent_valid_term(case, listing, published):
    key = SecurityKey("095610", "KR7095610002", "2016-01-01", None, "KOSDAQ", "common")
    raw = pd.read_csv(FIXTURES / "095610.bonus-prices.csv.gz", dtype={"Code": str}, parse_dates=["Date"])
    raw = raw.rename(columns={"MKT_NM": "Market"})
    if case == "nonconsecutive":
        raw = raw[raw.Date.ne("2016-04-21")].reset_index(drop=True)
    quote, quote_form, quote_body = official_body("20160412000324")
    terms, form, body = official_body("20160428000303")
    quote = replace(quote, company_id="09561", submitter="코스닥시장본부")
    terms = replace(terms, company_id="09561", submitter="테스")
    bad = replace(terms, accession="20160428000304")
    text = body.body.decode().replace("2016년 05월 09일", listing)
    if case == "ratio":
        text = text.replace("0.5000000000", "3.0000000000")
    if case in {"record-date", "shares-changed"}:
        text = text.replace("2016년 04월 15일", "2016년 04월 18일")
    if case == "record-overlap":
        text = text.replace("2016년 03월 02일", "2016년 04월 15일")
    bad_body = replace(body, body=text.encode(), document_no=bad.accession, family=(bad.accession,))
    related = replace(_additional_listing(3, 1_000, "국내CB전환")[0], company_id="09561",
                      published=date.fromisoformat(published))
    by_accession = {row.accession: (form_id, section, (section.evidence,)) for row, form_id, section in [
        (quote, quote_form, quote_body), (terms, form, body), (bad, form, bad_body),
    ]}

    def document(row, *, cache_only=False):
        if row == related:
            raise KindUnavailable("KIND supplemental response is unavailable in cache")
        return by_accession[row.accession]

    days = pd.DatetimeIndex(raw.Date)
    genuine, = (candidate for candidate in observe_candidates(key, raw, days) if candidate.date == "2016-04-14")
    independent = genuine
    observed = [genuine]
    if case == "shares-changed":
        independent = replace(genuine, date="2016-04-15", prev_date=genuine.date, shares_after=genuine.shares_after + 1)
        observed.append(independent)
    bad_facts, = parse_notice(bad, form, bad_body)
    observation, check = combined_bonus_observation(independent, bad_facts, raw, days)
    expected_check = {"ratio": "combined_bonus_reference_price_mismatch", "record-date": "combined_bonus_record_date_mismatch",
                      "record-overlap": "combined_bonus_record_date_overlap", "shares-changed": "ex_price_shares_changed"}
    assert observation is None and check == expected_check.get(case, "combined_bonus_listing_session_unavailable")
    client = Mock(document=Mock(side_effect=document))
    parsed, blocked, unparsed, _, _, failures, *_ = _collect_notices(
        client, [quote, terms, bad, related], {key: {"테스"}}, {key: observed},
        anchors={}, spac_keys=set(), bounded=True, raw_prices={key: raw},
    )
    assert {call.args[0] for call in client.document.call_args_list} == {quote, terms, bad}
    assert not failures and not blocked and not unparsed
    row, = (row for row in resolve_events(key, raw, days, parsed[key], coverage_complete=True).resolutions
            if row.date == genuine.date)
    assert (row.kind, row.price_factor, row.volume_factor) == (Resolution.BONUS, Fraction(2, 3), Fraction(3, 2))


def test_combined_observation_rejects_listing_as_the_first_available_price():
    key = SecurityKey("095610", "KR7095610002", "2016-01-01", None, "KOSDAQ", "common")
    raw = pd.read_csv(FIXTURES / "095610.bonus-prices.csv.gz", dtype={"Code": str}, parse_dates=["Date"])
    raw = raw.rename(columns={"MKT_NM": "Market"})
    genuine, = observe_candidates(key, raw, pd.DatetimeIndex(raw.Date))
    facts, = parse_notice(*official_body("20160428000303"))
    raw = raw[raw.Date.ge(facts.listing)]
    assert raw.Date.iloc[0].date().isoformat() == facts.listing
    assert combined_bonus_observation(genuine, facts, raw, pd.DatetimeIndex(raw.Date)) == (
        None, "combined_bonus_listing_session_unavailable",
    )
