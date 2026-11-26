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
