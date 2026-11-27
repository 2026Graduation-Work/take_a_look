from dataclasses import replace
from datetime import date
from fractions import Fraction
from unittest.mock import Mock

import pandas as pd
from experiments.dataset import census_actions
from shared.data.kind_market import DocumentRoute, FinalReferral, KindUnavailable
from shared.data.market_notices import SecurityKey
from shared.data.market_resolutions import Resolution, observe_candidates, resolve_events
from shared.tests.test_corporate_action_review import moa_data
from shared.tests.test_market_resolutions import bars, official_body
from shared.tests.test_notice_security import SOURCE, _price_notice


def test_compound_70768_does_not_request_pure_bonus_terms():
    key = SecurityKey("023900", "KR7023900004", "1994-11-23", None, "KOSDAQ", "common")
    filing, form, body = official_body("20161108000394")
    filing = replace(filing, company_id="02390", submitter="코스닥시장본부")
    terms = replace(filing, accession="20161107000001", published=date(2016, 11, 7),
                    title="무상증자결정", submitter="풍국주정")
    raw = bars(key, [
        ("2016-11-08", 10_000, 10_000, 10_000, 10_000, 0, 10, 100_000, 8_000_000),
        ("2016-11-09", 8_200, 8_200, 8_200, 8_200, 0, 10, 82_000, 8_000_000),
    ])

    def document(filing):
        if filing == terms:
            raise KindUnavailable("KIND requests stopped or budget exhausted; resume collection")
        return form, body, (SOURCE, SOURCE, body.evidence)

    client = Mock(document=Mock(side_effect=document))
    days = pd.DatetimeIndex(raw.Date)
    candidates = observe_candidates(key, raw, days)
    parsed, blocked, unparsed, _, _, failures, *_ = census_actions._collect_notices(
        client, [filing, terms], {key: {"풍국주정"}}, {key: candidates},
        anchors={}, spac_keys=set(), bounded=True,
    )
    client.document.assert_called_once_with(filing)
    assert not blocked and not failures
    event, = resolve_events(key, raw, days, parsed[key], coverage_complete=True,
                            blocked_dates=blocked[key], unparsed_dates=unparsed[key]).resolutions
    assert event.kind == Resolution.SEGMENT_BREAK and event.review


def test_corrected_bonus_terms_failure_does_not_block_unrelated_face_value_date(monkeypatch):
    key, raw, par_listing = moa_data.__wrapped__()
    quote, body = _price_notice("2026-11-12", [("보통주", "700")])
    quote = replace(quote, accession="20261111000001", published=date(2026, 11, 11), company_id="28898",
                    title="권리락(무상증자)", submitter="코스닥시장본부")
    text = body.text().replace("삼성중공업", "모아데이타").replace("권리락(유상증자)", "권리락(무상증자)")
    body = replace(body, body=text.encode(), document_no=quote.accession, family=(quote.accession,))
    par = replace(quote, accession=par_listing.accession, published=date(2026, 11, 10), title=par_listing.title)
    par_body = replace(body, document_no=par.accession, family=(par.accession,))
    terms, form, terms_body = official_body("20210707000126")
    original = replace(terms, accession="20260901000001", published=date(2026, 9, 1), company_id="28898")
    final = replace(terms, accession="20261111000002", published=date(2026, 11, 11), company_id="28898")
    family = (original.accession, final.accession)
    old_body = replace(terms_body, document_no=original.accession, family=family, final=False)
    new_body = replace(terms_body, document_no=final.accession, family=family, final=True)
    route = DocumentRoute(final.accession, final.accession, "https://kind.krx.co.kr/fixture", form)
    referral = FinalReferral(route, ((original.accession, "N"), (final.accession, "Y")), SOURCE)
    docs = {quote: ("99301", body), par: (par_listing.form, par_body), original: (form, old_body), final: (form, new_body)}
    document = Mock(side_effect=lambda filing, **_: (*docs[filing], (SOURCE, SOURCE, docs[filing][1].evidence)))
    client = Mock(document=document, final_referral=Mock(return_value=referral), dated_filing=Mock(return_value=final))
    parse = census_actions.parse_notice
    monkeypatch.setattr(census_actions, "parse_notice", lambda filing, form, body: (
        [par_listing.facts] if filing == par else parse(filing, form, body)
    ))
    days = pd.DatetimeIndex(raw.Date)
    par_event, = observe_candidates(key, raw, days)
    bonus_event = replace(par_event, prev_date=par_event.date, date="2026-11-12")
    parsed, blocked, unparsed, _, _, failures, *_ = census_actions._collect_notices(
        client, [quote, par, original, final], {key: {"모아데이타"}}, {key: [par_event, bonus_event]},
        anchors={}, spac_keys=set(), bounded=True, daily={final.published: object()},
    )
    failure, = failures
    assert failure["AcptNo"] == original.accession and failure["FailedCheck"] == "notice_security_unresolved"
    assert set(unparsed[key]) == {bonus_event.date}
    assert not blocked
    event, = resolve_events(key, raw, days, parsed[key], coverage_complete=True,
                            blocked_dates=blocked[key], unparsed_dates=unparsed[key]).resolutions
    assert (event.kind, event.review, event.price_factor, event.volume_factor) == (
        Resolution.UNIT_CHANGE, False, Fraction(5), Fraction(1, 5),
    )
