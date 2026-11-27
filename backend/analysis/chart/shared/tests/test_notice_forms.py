import re
from dataclasses import replace
from fractions import Fraction

import pytest
from shared.data.disclosures import DisclosureError
from shared.data.market_notices import parse_notice
from shared.tests.test_market_resolutions import official_body


def test_combined_rights_table_preserves_both_causes():
    filing, form, body = official_body("20161108000394")
    facts, = parse_notice(filing, form, body)
    assert (facts.kind, facts.code, facts.share_label, facts.effective, facts.base, facts.reason) == (
        "ex_price", "023900", "보통주식", "2016-11-09", 8200, "무상증자 및 배당",
    )


@pytest.mark.parametrize("accession,record,listing,shares,ratio,paid_record,paid_listing", [
    ("20160722000097", "2016-08-04", "2016-08-25", 3_323_466, Fraction(3, 10), "2016-06-23", "2016-08-18"),
    ("20160428000303", "2016-04-15", "2016-05-09", 6_057_540, Fraction(1, 2), "2016-03-02", "2016-04-29"),
])
def test_combined_terms_use_only_the_final_bonus_section(accession, record, listing, shares, ratio, paid_record, paid_listing):
    filing, form, body = official_body(accession)
    facts, = parse_notice(filing, form, body)
    assert (facts.kind, facts.share_label, facts.effective, facts.listing, facts.added_shares, facts.ratio) == (
        "bonus_terms", "보통주식", record, listing, shares, ratio,
    )
    assert (facts.paid_record_date, facts.paid_listing) == (paid_record, paid_listing)
    with pytest.raises(DisclosureError, match="lack a final document"):
        parse_notice(filing, form, replace(body, final=False))


@pytest.mark.parametrize("accession,canonical,alias", [
    ("20161212000116", "1. 1주당 배당주식수 (주)", "1주당 배당주식수"),
    ("20221220000339", "1. 1주당 배당주식수 (주)", "1. 1주당 배당주식수"),
    ("20210707000126", "5. 1주당 신주배정 주식수", "1주당 신주배정 주식수 (주)"),
])
def test_per_share_quantity_labels_preserve_facts_and_reject_duplicate_fields(accession, canonical, alias):
    filing, form, body = official_body(accession)
    text = body.text()
    row, = [row for row in re.findall(r"<tr\b[^>]*>.*?</tr>", text, re.I | re.S) if canonical in row]
    alternate = row.replace(canonical, alias)
    canonical_facts = parse_notice(filing, form, body)
    aliased = replace(body, body=text.replace(row, alternate, 1).encode(body.charset))
    assert parse_notice(filing, form, aliased) == canonical_facts
    duplicate = replace(body, body=text.replace(row, row + alternate, 1).encode(body.charset))
    with pytest.raises(DisclosureError, match="KIND dividend or bonus terms lack"):
        parse_notice(filing, form, duplicate)


@pytest.mark.parametrize("accession,day,before,added,ratio", [
    ("20161212000241", "2016-12-31", 12_011_889, 590_407, Fraction(1, 20)),
    ("20241220000454", "2024-12-31", 1_842_040, 68_805, Fraction(1, 25)),
])
def test_dividend_correction_uses_the_unique_operative_body(accession, day, before, added, ratio):
    filing, form, body = official_body(accession)
    facts, = parse_notice(filing, form, body)
    assert (facts.effective, facts.shares_before, facts.added_shares, facts.ratio, facts.share_label) == (
        day, before, added, ratio, "보통주식",
    )
    with pytest.raises(DisclosureError, match="unique operative heading"):
        parse_notice(filing, form, replace(body, final=False))
    text = body.text()
    heading = text.index('<div class="xforms_title">')
    duplicate = replace(body, body=(text + text[heading:]).encode(body.charset))
    with pytest.raises(DisclosureError, match="unique operative heading"):
        parse_notice(filing, form, duplicate)
    # A correction-only document must not use the comparison's after value as its body.
    comparison_only = replace(body, body=text[:heading].encode(body.charset))
    with pytest.raises(DisclosureError, match="unique operative heading"):
        parse_notice(filing, form, comparison_only)


@pytest.mark.parametrize("accession", ["20181220000241", "20250219000916"])
def test_subsidiary_dividend_stays_outside_the_issuer_terms(accession):
    filing, form, body = official_body(accession)
    with pytest.raises(DisclosureError, match="belong to a subsidiary"):
        parse_notice(filing, form, body)


def test_collected_bonus_and_same_day_cb_listing_keep_their_distinct_quantities():
    facts = []
    for accession in ("20210823000262", "20210823000265"):
        filing, form, body = official_body(accession)
        section, = parse_notice(filing, form, body)
        facts.append(section)
    assert [(f.code, f.isin, f.effective, f.reason, f.added_shares) for f in facts] == [
        ("025620", "KR7025620006", "2021-08-26", "무상증자", 11_535_471),
        ("025620", "KR7025620006", "2021-08-26", "국내CB전환", 607_566),
    ]
    assert sum(f.added_shares for f in facts) == 12_143_037
