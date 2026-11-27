import gzip
import hashlib
import json
from dataclasses import asdict, replace
from datetime import date
from pathlib import Path

import pandas as pd
import pytest
from shared.data.actions import (
    PRICE_POLICY,
    Security,
    actions_for_window,
    parse_auction,
    parse_decision,
    parse_implementation,
    reconcile,
)
from shared.data.disclosures import (
    DisclosureError,
    Evidence,
    Filing,
    Response,
    collect_pages,
    kind_page,
)
from shared.data.events import verify_events
from shared.data.training_prices import adjust_training_window

FIXTURES = Path(__file__).parent / "fixtures"
OFFICIAL = FIXTURES / "official_actions"
SOURCES = json.loads((OFFICIAL / "sources.json").read_text())


def response(name):
    path = OFFICIAL / name
    info = SOURCES[name]
    body = gzip.decompress(path.with_suffix(".html.gz").read_bytes()) if path.suffix == ".html" else path.read_bytes()
    assert hashlib.sha256(body).hexdigest() == info["sha256"]
    return Response(body, info["charset"], Evidence(info["sha256"], "fixture"))


def filing(accession, title, body, security=None):
    return Filing(accession, date.fromisoformat(accession[:8]), title, body.evidence,
                  "" if security is None else security.issuer_code)


def action_case(code, *, preferred=False):
    cases = {
        "005930": ("KR7005930003", "00126380", "KOSPI", "20180316800856", "주식분할결정",
                   "20180503000318", "변경상장(액면분할)", "20180503000318.notice.html", None, "2018-05-04", None),
        "005935": ("KR7005931001", "00126380", "KOSPI", "20180316800856", "주식분할결정",
                   "20180503000318", "변경상장(액면분할)", "20180503000318.notice.html", None, "2018-05-04", None),
        "031820": ("KR7031820004", "00186559", "KOSPI", "20260303801271", "주식병합결정",
                   "20260429000143", "변경상장(액면병합)", "031820.notice.html", None, "2026-05-06", None),
        "004920": ("KR7004920005", "00127158", "KOSPI", "20191230000553", "주요사항보고서(감자결정)",
                   "20200317000810", "변경상장(감자(주식병합))", "20200317000810.notice.html",
                   "004920-reduction.response", "2020-03-20", "20200319001024"),
        "003410": ("KR7003410008", "00138224", "KOSPI", "20201110000127", "주요사항보고서(감자결정)",
                   "20201201000101", "상장안내(감자(액면변경))", "20201201000101.notice.html",
                   "003410-reduction.response", "2020-12-04", "20201203000329"),
        "104620": ("KR7104620000", "00632845", "KOSDAQ", "20210707000113", "주요사항보고서(무상증자결정)",
                   "20210721000416", "권리락(무상증자)", "104620.notice.html", "104620-bonus.response", "2021-07-22", None),
        "403870": ("KR7403870009", "01288827", "KOSDAQ", "20230302000205", "주요사항보고서(무상증자결정)",
                   "20230315002060", "권리락(무상증자)", "403870.notice.html", "403870-bonus.response", "2023-03-16", None),
    }
    isin, corp, market, receipt, title, kind_rcp, kind_title, kind_file, detail_file, day, auction_rcp = cases[code]
    common = "005930" if preferred else code
    security = Security(code, isin, "preferred" if preferred else "common", "2016-01-01", None, corp, common, market)
    family = ((receipt, title),)
    if code in {"005930", "005935"}:
        original = "20180131800068"
        family = ((receipt, "[정정] " + title), (original, title))
    detail = None
    if detail_file:
        body = response(detail_file)
        detail = (json.loads(body.body)["list"][0], body.evidence)
    else:
        body = response(receipt + ".body.html")
    name = "[정정] " + title if len(family) == 2 else title
    current = parse_decision(security, filing(receipt, name, body, security), body, family, detail)
    decisions = [current]
    if len(family) == 2:
        original_rcp = family[-1][0]
        body = response(original_rcp + ".body.html")
        decisions.append(parse_decision(security, filing(original_rcp, title, body, security), body, family))
    body = response(kind_file)
    notice = parse_implementation(security, filing(kind_rcp, kind_title, body), body)
    auctions = []
    if auction_rcp:
        body = response(auction_rcp + ".notice.html")
        auctions.append(parse_auction(security, filing(auction_rcp, "기준가격결정방법 안내", body), body))
    sessions = {day: {"104620": "2021-07-23", "403870": "2023-03-17"}.get(code)}
    return security, decisions, notice, sessions, auctions


def snapshot_for(security, days, actions, *, status="covered"):
    start, end = days[0].date().isoformat(), days[-1].date().isoformat()
    return {
        "version": 1, "price_policy": PRICE_POLICY,
        "securities": [{
            "security": asdict(security), "status": status, "start": start, "end": end,
            "coverage": [{"source": source, "start": start, "end": end, "rows": 0,
                          "pages": [{"sha256": "input", "receipt": "fixture"}]}
                         for source in ("KIND market actions", "OpenDART list")],
            "actions": [asdict(event) for event in actions],
        }],
    }


@pytest.mark.parametrize(
    ("code", "name", "price", "volume"),
    [
        ("005930", "005930_2018.csv", 1 / 50, 50),
        ("004920", "004920_2020.csv", 3, 1 / 3),
        ("031820", "031820_2026.csv", 10, 0.1),
        ("003410", "003410_2020.csv", 1, 1),
        ("104620", "official_actions/104620-raw.csv", 1 / 3, 3),
    ],
)
def test_official_evidence_applies_the_actual_unit_conversion(code, name, price, volume):
    security, decisions, notice, sessions, auctions = action_case(code)
    if code == "005930":
        assert [item.listing for item in decisions] == ["2018-05-04", "2018-05-16"]
    raw = pd.read_csv(FIXTURES / name, comment="#", parse_dates=["Date"]).drop(columns="NaverClose", errors="ignore")
    raw = raw.sort_values("Date").reset_index(drop=True)
    days = pd.DatetimeIndex(raw.Date)
    original = raw.copy(deep=True)
    actions, pending = reconcile(security, decisions, [notice], "2018-01-01", "2026-12-31", sessions, auctions)
    assert pending == []
    snapshot = snapshot_for(security, days, actions)
    adjusted, events = adjust_training_window(code, raw, days, days[-1], snapshot, listing=security.listing)
    assert len(events) == 1
    applied = events.iloc[0]
    assert (applied.PriceFactor, applied.VolumeFactor) == (price, volume)
    assert applied.ExDate == pd.Timestamp(notice.ex_date)
    pd.testing.assert_frame_equal(raw, original)
    pd.testing.assert_frame_equal(adjusted[raw.columns], original)
    before = adjusted.Date < applied.ExDate
    assert adjusted.loc[before, "Volume"].tolist() == pytest.approx((raw.loc[before, "RawVolume"] * volume).tolist())
    assert adjusted.loc[~before, "AdjustmentFactor"].eq(1).all()
    if code == "004920":
        assert adjusted.loc[adjusted.Date.eq(applied.ExDate), "Change"].item() == pytest.approx((623 / 885 - 1) * 100)
        assert applied.BasePrice == 636
    if code == "003410":
        assert applied.Kind == "reference_reset"
        assert adjusted.loc[adjusted.Date.eq(applied.ExDate), "Change"].item() == pytest.approx((6700 / 5550 - 1) * 100)
    if code == "104620":
        assert adjusted.loc[adjusted.Date.eq(pd.Timestamp("2021-08-17")), "AdjustmentFactor"].item() == 1


def test_preferred_shares_and_holdout_bonus_have_distinct_terms():
    security, decisions, notice, sessions, _ = action_case("005935", preferred=True)
    action, pending = reconcile(security, decisions, [notice], notice.ex_date, notice.ex_date, sessions)
    assert pending == []
    assert action[0].shares == (18_072_580, 903_629_000)
    security, decisions, notice, sessions, _ = action_case("403870")
    action, pending = reconcile(security, decisions, [notice], notice.ex_date, notice.ex_date, sessions)
    assert pending == []
    assert (action[0].new_units, action[0].old_units) == (4, 1)


def test_ambiguity_and_cancellation_are_distinct_from_a_verified_event():
    security, decisions, notice, sessions, _ = action_case("104620")
    first = decisions[0]
    second = replace(first, accession="20210708000113", published=date(2021, 7, 8), family="20210708000113")
    _, pending = reconcile(security, [first, second], [notice], "2021-07-19", "2021-08-20", sessions)
    assert "found 2" in pending[0]
    cancelled = replace(first, accession="20210709000001", published=date(2021, 7, 9), cancelled=True)
    assert reconcile(security, [first, cancelled], [], "2021-07-19", "2021-08-20", sessions) == ([], [])
    actions, pending = reconcile(security, [first, cancelled], [notice], "2021-07-19", "2021-08-20", sessions)
    assert not actions and pending
    late = replace(cancelled, accession="20210726000001", published=date(2021, 7, 26))
    _, pending = reconcile(security, [first, late], [], "2021-07-19", "2021-08-20", sessions)
    assert "at or after scheduled implementation" in pending[0]


def test_unknown_implementation_form_stays_unverified():
    security, _, notice, _, _ = action_case("104620")
    body = response("104620.notice.html")
    unsupported = replace(body, body=body.body.replace(b'class="xforms_input"', b'class="unknown"'))
    with pytest.raises(DisclosureError, match="Unsupported KIND rights"):
        parse_implementation(security, filing(notice.evidence.accession, "권리락(무상증자)", body), unsupported)


def test_real_kind_page_count_uses_requested_size_and_total():
    start, end = date(2018, 5, 2), date(2018, 5, 5)
    rows, coverage = collect_pages("KIND market actions", start, end, 2, lambda page: kind_page(
        response(f"samsung-small-{page}.html"), start, end, page, page_size=2,
    ))
    assert len(rows) == coverage.rows == 3
    assert len(coverage.pages) == 2
    day = date(2018, 6, 5)
    rows, coverage = collect_pages("KIND market actions", day, day, 15, lambda page: kind_page(
        response("samsung-empty.html"), day, day, page,
    ))
    assert rows == [] and coverage.rows == 0


def test_duplicate_action_session_is_unverified():
    security, decisions, notice, sessions, _ = action_case("104620")
    actions, pending = reconcile(security, decisions, [notice], notice.ex_date, notice.ex_date, sessions)
    assert len(actions) == 1 and not pending
    raw = pd.read_csv(OFFICIAL / "104620-raw.csv", parse_dates=["Date"]).sort_values("Date")
    with pytest.raises(ValueError, match="multiple verified actions"):
        verify_events(security.code, raw, raw.Date, actions * 2)


def test_window_requires_valid_isin_and_canonical_listing_dates():
    security, *_ = action_case("005930")
    with pytest.raises(DisclosureError, match="listing interval date"):
        replace(security, listing="not-a-date")
    with pytest.raises(DisclosureError, match="Invalid KRX security identity"):
        replace(security, isin="KR7005930000")
    security = replace(security, listing="2021-07-22", delisting="2021-07-23")
    days = pd.DatetimeIndex(["2021-07-21", "2021-07-22", "2021-07-23"])
    snapshot = snapshot_for(security, days, [])
    with pytest.raises(DisclosureError, match="prices lie outside"):
        actions_for_window(snapshot, security.code, days, listing=security.listing, delisting=security.delisting)


def test_joint_listing_requires_the_matching_code_isin_and_class():
    security, _, notice, _, _ = action_case("005935", preferred=True)
    body = response("20180503000318.notice.html")
    listing = filing(notice.evidence.accession, "변경상장(액면분할)", body)
    for mismatched in (replace(security, isin="KR7005930003"), replace(security, share_class="common")):
        with pytest.raises(DisclosureError):
            parse_implementation(mismatched, listing, body)
