from dataclasses import replace
from datetime import date
from types import SimpleNamespace
from unittest.mock import Mock

import pandas as pd
import pytest
from experiments.dataset import census_actions
from shared.data.disclosures import Evidence, Response
from shared.data.kind_market import (
    CorrectionError,
    DocumentRoute,
    FinalReferral,
    KindBody,
    MarketFiling,
    daily_page,
    final_document_number,
    kind_withdrawal,
    viewer_documents,
)
from shared.data.market_notices import SecurityKey
from shared.data.market_resolutions import Resolution, observe_candidates, resolve_events
from shared.tests.test_market_resolutions import bars
from shared.tests.test_notice_security import SAMSUNG_UNIVERSE, _price_notice

SECURITY = SecurityKey("010140", "KR7010140002", "1994-01-28", None, "KOSPI", "common")


def _evidence(number):
    return Evidence(f"{number:064x}", f"{number + 100:064x}")


def _filing(number, title="권리락 기준가격 안내"):
    return MarketFiling(f"2021010{number}000001", date(2021, 1, number), title, _evidence(number),
                        company_id="01014", submitter="유가증권시장본부")


@pytest.mark.parametrize("title,check,calls", [
    ("권리락 기준가격 안내", "unsupported_form:99999", 1),
    ("[정정][철회] 권리락 기준가격 안내", "correction_withdrawn", 0),
])
def test_final_failure_preserves_its_diagnosis_and_evidence_for_each_referral(monkeypatch, title, check, calls):
    final, *originals = (_filing(4, title), _filing(5), _filing(6))
    final_route = DocumentRoute(final.accession, "20210104009999", "https://kind.krx.co.kr/fixture", "99999")
    document_numbers = (final_route.document_no, "20210105009999", "20210106009999")
    family = tuple((doc, "Y" if doc == final_route.document_no else "N") for doc in document_numbers)
    refs = {filing.accession: tuple(_evidence(10 * filing.published.day + offset) for offset in range(3))
            for filing in (final, *originals)}
    referrals = {row.accession: FinalReferral(final_route, family, _evidence(100 + row.published.day)) for row in originals}

    def document(filing, *, expected=None):
        is_final = filing == final
        assert expected is None or (is_final and expected in referrals.values())
        acquired = refs[filing.accession]
        return "99999", KindBody(b"body", "utf-8", acquired[-1], document_numbers[filing.published.day - 4],
                                 document_numbers, is_final), acquired

    client = Mock(document=Mock(side_effect=document), dated_filing=Mock(return_value=final),
                  final_referral=Mock(side_effect=lambda filing, *_: referrals[filing.accession]))
    parse = Mock(wraps=census_actions.parse_notice)
    monkeypatch.setattr(census_actions, "parse_notice", parse)
    candidate = SimpleNamespace(prev_date="2021-01-07", date="2021-01-08")
    result = census_actions._collect_notices(
        client, [*originals, final], {SECURITY: {"삼성중공업"}}, {SECURITY: [candidate]},
        anchors={}, spac_keys=set(), bounded=True, daily={final.published: object()},
    )
    parsed, blocked, unparsed, _, _, failures, _, families, *_ = result
    assert not parsed and not blocked and not families
    assert parse.call_count == calls
    if calls:
        assert parse.call_args.args[0] == final and parse.call_args.args[2].final
    assert [row["FailedCheck"] for row in failures] == [check] * 3
    assert len({row["Reason"] for row in failures}) == 1
    assert [item.failed_check for item in unparsed[SECURITY][candidate.date]] == [check] * 3
    for original, failure in zip(originals, failures[1:]):
        expected = (original.evidence, *refs[original.accession], referrals[original.accession].evidence,
                    final.evidence, *refs[final.accession])
        assert tuple(Evidence(**ref) for ref in failure["Evidence"]) == expected


def _viewer(filing, marker, other):
    return Response((f'<input name="acptNo" id="acptNo" value="{filing.accession}">'
                     f'<select id="mainDoc"><option value="20210104009998|{marker}" selected></option>'
                     f'<option value="20210104009999|{other}"></option></select>').encode(), "utf-8", _evidence(90))


def test_absent_and_multiple_finals_are_reported_as_review():
    filing = _filing(4)
    with pytest.raises(CorrectionError) as missing:
        final_document_number(*viewer_documents(filing.accession, _viewer(filing, "N", "N")))
    assert missing.value.failed_check == "correction_final_unresolved"

    client = Mock(document=Mock(side_effect=lambda row: viewer_documents(row.accession, _viewer(row, "Y", "Y"))))
    candidate = SimpleNamespace(prev_date="2021-01-07", date="2021-01-08")
    _, blocked, unparsed, _, _, failures, *_ = census_actions._collect_notices(
        client, [filing], {SECURITY: {"삼성중공업"}}, {SECURITY: [candidate]},
        anchors={}, spac_keys=set(), bounded=True,
    )
    assert not blocked
    assert unparsed[SECURITY][candidate.date][0].failed_check == "correction_final_unresolved"
    failure, = failures
    assert failure["Stage"] == "kind_notice"
    assert failure["Evidence"] == [vars(filing.evidence), vars(_evidence(90))]


def test_withdrawal_marker_survives_a_caption_without_the_displayed_prefix():
    filing = _filing(4)
    listing = (f'<tr><td>12:00</td><td><a onclick="companysummary_open(\'01014\')">삼성중공업</a></td>'
               f'<td><a onclick="openDisclsViewer(\'{filing.accession}\',\'\')" title="무상증자결정">'
               '[취소] 무상증자결정</a></td><td>삼성중공업</td><td></td></tr>')
    html = f'<table>{listing}</table>전체 <em>1</em>건 : <strong>1</strong>/1'
    _, _, [selected], _ = daily_page(Response(html.encode(), "utf-8", _evidence(91)), filing.published, 1)
    assert selected.title == "무상증자결정" and selected.withdrawn
    assert kind_withdrawal("[기재정정] 무상증자결정 (철회)")
    assert kind_withdrawal("변경상장 (취소)")
    assert not kind_withdrawal("무상증자결정(철회 가능성 및 후속 공시)")


def test_failed_referral_covers_target_candidates_and_does_not_skip_direct_acquisition():
    effective = "2016-09-30"
    quote, body = _price_notice(effective, [("보통주", "9,200")])
    quote = replace(quote, title="권리락 기준가격 안내", submitter="유가증권시장본부")
    original = replace(quote, accession="20160901000293", published=date(2016, 9, 1))
    final = replace(quote, accession="20160930000296", published=date(2016, 9, 30))
    route = DocumentRoute(final.accession, final.accession, "https://kind.krx.co.kr/fixture", "99301")
    referral = FinalReferral(route, ((original.accession, "N"), (final.accession, "Y")), _evidence(10))

    def document(filing, *, expected=None):
        if expected:
            raise CorrectionError("KIND final viewer selection or correction family differs", (_evidence(90),))
        return "99301", replace(body, document_no=filing.accession, family=(filing.accession,), final=filing != original), (
            _evidence(90), _evidence(91), _evidence(92),
        )

    client = Mock(document=Mock(side_effect=document), final_referral=Mock(return_value=referral),
                  dated_filing=Mock(return_value=final))
    raw = bars(SECURITY, [
        ("2016-09-29", 10_600, 10_600, 10_600, 10_600, 0, 10, 106_000, 390_000_000),
        (effective, 9_200, 9_200, 9_200, 9_200, 0, 10, 92_000, 390_000_000),
    ])
    days = pd.DatetimeIndex(raw.Date)
    candidate, = observe_candidates(SECURITY, raw, days)
    earlier = replace(candidate, prev_date="2016-09-01", date="2016-09-02")
    parsed, blocked, unparsed, _, _, failures, *_ = census_actions._collect_notices(
        client, [original, quote, final], SAMSUNG_UNIVERSE,
        {key: [earlier, candidate] if key == SECURITY else [] for key in SAMSUNG_UNIVERSE},
        anchors={}, spac_keys=set(), bounded=True, daily={final.published: object()},
    )
    assert client.document.call_count == 4 and final.accession in {notice.accession for notice in parsed[SECURITY]}
    assert failures[0]["FailedCheck"] == "correction_final_unresolved"
    assert set(unparsed[SECURITY]) == {earlier.date, candidate.date}
    event, = resolve_events(SECURITY, raw, days, parsed[SECURITY], coverage_complete=True,
                            blocked_dates=blocked[SECURITY], unparsed_dates=unparsed[SECURITY]).resolutions
    assert event.kind == Resolution.SEGMENT_BREAK and event.review
