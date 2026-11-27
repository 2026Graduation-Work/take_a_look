import json
from collections import defaultdict
from dataclasses import replace
from pathlib import Path
from unittest.mock import Mock

import pytest
from experiments.dataset.census_actions import _collect_notices
from shared.data.actions import valid_isin
from shared.data.market_notices import SecurityKey, normal_company, parse_notice
from shared.data.market_resolutions import Candidate
from shared.tests.test_market_resolutions import official_body

FIXTURES = Path(__file__).parents[2] / "shared/tests/fixtures/market_actions"
CASES = json.loads((FIXTURES / "unlisted-terms-cases.json").read_text())
SOURCES = json.loads((FIXTURES / "sources.json").read_text())


@pytest.mark.parametrize("case", CASES, ids=lambda case: case["candidate"]["Code"])
@pytest.mark.parametrize("complete", [True, False])
@pytest.mark.parametrize("active_preferred", [False, True])
def test_company_terms_separate_a_verified_common_allocation_from_an_unlisted_class(case, complete, active_preferred):
    raw = case["candidate"]
    key = SecurityKey(raw["Code"], raw["ISIN"], raw["ListingDate"], raw["DelistingDate"] or None,
                      raw["Market"], raw["ShareClass"])
    candidate = Candidate(key, raw["Date"], raw["PrevDate"], *map(int, [raw[field] for field in (
        "PrevClose", "BasePrice", "SharesBefore", "SharesAfter")]), raw["Paused"] == "True")
    filings, docs = [], {}
    for accession in (case["quote"], case["terms"]):
        filing, form, body = official_body(accession)
        filing = replace(filing, company_id=SOURCES[accession]["company_id"], submitter=SOURCES[accession]["submitter"])
        filings.append(filing)
        docs[accession] = (form, body, (body.evidence,) * 3)
    term_filing = filings[-1]
    form, body, _ = docs[term_filing.accession]
    common, other = parse_notice(term_filing, form, body)
    assert common.share_label == "보통주식" and other.share_label == "종류주식" and other.ratio > 0
    assert other.code is None and other.isin is None
    aliases = {key: {normal_company(common.company)}}
    universe = dict(aliases)
    if active_preferred:
        isin = next(f"KR7{key.code[:5]}100{digit}" for digit in range(10)
                    if valid_isin(f"KR7{key.code[:5]}100{digit}"))
        preferred = replace(key, code=key.code[:5] + "5", isin=isin, listing=other.listing or other.effective,
                            share_class="preferred")
        universe[preferred] = {normal_company(common.company) + "우"}
        if other.listing:
            assert not preferred.active(other.effective) and preferred.active(other.listing)
    client = Mock()
    client.document.side_effect = lambda filing: docs[filing.accession]
    parsed, _, unparsed, _, _, failures, *_ = _collect_notices(
        client, filings, aliases, defaultdict(tuple, {key: (candidate,)}), anchors={}, spac_keys=set(), bounded=True,
        identity_universe=universe if complete else None,
    )
    if complete and (not active_preferred or other.listing is None):
        assert not failures and not unparsed[key]
        assert [notice.facts.kind for notice in parsed[key]] == ["ex_price", common.kind]
    else:
        assert len(failures) == 1
        failure, = unparsed[key][candidate.date]
        assert failure.failed_check == "notice_security_unresolved"
