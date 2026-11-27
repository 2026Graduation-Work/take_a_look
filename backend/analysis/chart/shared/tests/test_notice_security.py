from dataclasses import replace
from datetime import date

import pytest
from shared.data.disclosures import DisclosureError, Evidence
from shared.data.kind_market import KindBody, MarketFiling
from shared.data.market_notices import (
    NoticeSection,
    SecurityKey,
    match_notice,
    notice_security_scope,
    parse_notice,
    resolve_notice_security,
)

SOURCE = Evidence("a" * 64, "b" * 64)
SAMSUNG = SecurityKey("010140", "KR7010140002", "1994-01-28", None, "KOSPI", "common")
SAMSUNG_PREF = SecurityKey("010145", "KR7010141000", "1994-11-22", "2023-07-17", "KOSPI", "preferred")
SAMSUNG_UNIVERSE = {SAMSUNG: {"삼성중공업"}, SAMSUNG_PREF: {"삼성중공우"}}
JW_PREF = SecurityKey("001065", "KR7001061001", "1994-10-21", None, "KOSPI", "preferred")
JW_SECOND = SecurityKey("001067", "KR7001062009", "1998-04-13", None, "KOSPI", "preferred")
JW_UNIVERSE = {JW_PREF: {"jw중외제약우", "jw중외제약1우선주"}, JW_SECOND: {"jw중외제약2우b"}}


def _price_notice(day, rows, *, columns=("주권종류", "기준가격(원)"), final=True):
    fields = [
        ("1. 회사명", "삼성중공업"),
        ("2. 주식의 종류와 가격", *columns),
        *rows,
        ("3. 사유", "권리락(유상증자)"),
        ("4. 적용일", day),
    ]
    html = "<table>" + "".join(
        "<tr>" + "".join(f"<td>{cell}</td>" for cell in row) + "</tr>" for row in fields
    ) + "</table>"
    filing = MarketFiling("20160929000295", date(2016, 9, 29), "권리락 기준가격 안내", SOURCE, company_id="01014")
    body = KindBody(html.encode(), "utf-8", SOURCE, "20160929000711", (), final)
    return filing, body


@pytest.mark.parametrize("day,common_base,preferred_base", [("2016-09-30", 9200, 33150), ("2018-03-07", 7510, 39150)])
def test_uncoded_rights_prices_match_the_two_samsung_securities(day, common_base, preferred_base):
    for label, key, base in [("보통주식", SAMSUNG, common_base), ("1우선주", SAMSUNG_PREF, preferred_base)]:
        filing, body = _price_notice(day, [(label, f"{base:,}")])
        facts, = parse_notice(filing, "99301", body)
        notice = match_notice(filing, "99301", facts, body, (), SAMSUNG_UNIVERSE)
        assert (notice.security, notice.facts.effective, notice.facts.base) == (key, day, base)


def test_ambiguous_jw_class_stays_unresolved_with_one_selected_security():
    company = "JW중외제약"
    generic = NoticeSection(1, "bonus_terms", company, "종류주식", "2017-01-19", "무상증자결정")
    filing, body = _price_notice(generic.effective, [("종류주식", "1,000")])
    filing = replace(filing, company_id="00106")
    with pytest.raises(DisclosureError, match="does not identify one KRX security"):
        match_notice(filing, "11307", generic, body, (), {JW_PREF: JW_UNIVERSE[JW_PREF]}, identity_universe=JW_UNIVERSE)

    second = replace(generic, share_label="2우선주B")
    assert resolve_notice_security("00106", second, JW_UNIVERSE) == JW_SECOND
    with pytest.raises(DisclosureError):
        resolve_notice_security("00106", replace(second, share_label="2우선주C"), JW_UNIVERSE)
    with pytest.raises(DisclosureError):
        resolve_notice_security("00106", replace(second, share_label="1우선주B"), JW_UNIVERSE)


def test_explicit_identifiers_require_the_same_issuer_class_and_listing_date():
    facts = NoticeSection(1, "ex_price", "삼성중공업", "1우선주", "2018-03-07", "유상증자",
                          code=SAMSUNG_PREF.code, isin=SAMSUNG_PREF.isin)
    assert resolve_notice_security("01014", facts, SAMSUNG_UNIVERSE) == SAMSUNG_PREF
    assert resolve_notice_security("010145", replace(facts, code=None), SAMSUNG_UNIVERSE) == SAMSUNG_PREF
    for issuer, altered in [("010", facts), ("010140", facts), ("00106", facts),
                            ("01014", replace(facts, isin=SAMSUNG.isin)),
                            ("01014", replace(facts, share_label="보통주")),
                            ("01014", replace(facts, effective="2023-07-17"))]:
        with pytest.raises(DisclosureError):
            resolve_notice_security(issuer, altered, SAMSUNG_UNIVERSE)


@pytest.mark.parametrize("identifier", [{"code": JW_PREF.code}, {"isin": JW_PREF.isin}])
def test_explicit_identifier_does_not_override_a_conflicting_series(identifier):
    facts = NoticeSection(1, "ex_price", "JW중외제약", "2우선주B", "2017-01-19", "유상증자", **identifier)
    with pytest.raises(DisclosureError):
        resolve_notice_security("00106", facts, JW_UNIVERSE)
    with pytest.raises(DisclosureError):
        resolve_notice_security("00106", replace(facts, share_label="1우선주B"), JW_UNIVERSE)
    assert resolve_notice_security("00106", replace(facts, share_label="1우선주"), JW_UNIVERSE) == JW_PREF


def test_six_character_issuer_does_not_make_a_generic_preferred_class_unique():
    facts = NoticeSection(1, "bonus_terms", "JW중외제약", "종류주식", "2017-01-19", "무상증자")
    with pytest.raises(DisclosureError):
        resolve_notice_security(JW_PREF.code, facts, JW_UNIVERSE)
    named = replace(facts, share_label="2우선주B")
    assert resolve_notice_security(JW_SECOND.code, named, JW_UNIVERSE) == JW_SECOND
    with pytest.raises(DisclosureError):
        resolve_notice_security(JW_PREF.code, named, JW_UNIVERSE)


def test_security_resolution_rejects_an_invalid_session_date():
    facts = NoticeSection(1, "ex_price", "JW중외제약", "2우선주B", "2016-02-31", "유상증자",
                          code=JW_SECOND.code)
    with pytest.raises(DisclosureError, match="does not identify one KRX security"):
        resolve_notice_security("00106", facts, JW_UNIVERSE)


def test_coded_preference_uses_a_known_series_even_with_an_unnumbered_alias():
    facts = NoticeSection(1, "ex_price", "JW중외제약", "1우선주", "2017-01-19", "유상증자", code=JW_SECOND.code)
    universe = {**JW_UNIVERSE, JW_SECOND: {*JW_UNIVERSE[JW_SECOND], "jw중외제약우"}}
    with pytest.raises(DisclosureError):
        resolve_notice_security("00106", facts, universe)


def test_notice_without_issuer_matches_in_full_universe_before_the_selected_window():
    filing, body = _price_notice("2018-03-07", [("보통주", "7,510")])
    filing = replace(filing, company_id="")
    facts, = parse_notice(filing, "99301", body)
    other = SecurityKey("002900", "KR7002900009", "1973-06-26", None, "KOSPI", "common")
    selected = {SAMSUNG: {"삼성중공업"}}
    universe = {**selected, other: {"삼성중공업"}}
    with pytest.raises(DisclosureError):
        match_notice(filing, "99301", facts, body, (), selected, identity_universe=universe)
    assert match_notice(filing, "99301", facts, body, (), selected).security == SAMSUNG


def test_notice_without_issuer_cannot_bind_an_unknown_explicit_share_class():
    filing, body = _price_notice("2018-03-07", [("1우선주", "39,150")])
    filing = replace(filing, company_id="")
    facts, = parse_notice(filing, "99301", body)
    coded = replace(facts, code=SAMSUNG_PREF.code)
    assert match_notice(filing, "99301", coded, body, (), SAMSUNG_UNIVERSE).security == SAMSUNG_PREF
    with pytest.raises(DisclosureError):
        match_notice(filing, "99301", replace(coded, share_label="알 수 없음"), body, (), SAMSUNG_UNIVERSE)


def test_price_table_cannot_discard_an_unknown_security_row():
    filing, body = _price_notice("2018-03-07", [("보통주", "7,510"), ("알 수 없음", "39,150")])
    with pytest.raises(DisclosureError):
        parse_notice(filing, "99301", body)
    filing, body = _price_notice("2018-03-07", [("보통주권", "7,510"), ("1우선주", "39,150")])
    rows = parse_notice(filing, "99301", body)
    assert [row.share_label for row in rows] == ["보통주권", "1우선주"]
    assert notice_security_scope(filing, "99301", body, SAMSUNG_UNIVERSE) == {
        (SAMSUNG, "2018-03-07"), (SAMSUNG_PREF, "2018-03-07"),
    }


@pytest.mark.parametrize("extra_column, extra_value", [
    ("단축코드", "A001067"),
    ("표준코드", JW_SECOND.isin),
])
def test_price_table_rejects_conflicting_identity_columns(extra_column, extra_value):
    filing, body = _price_notice(
        "2017-01-19", [("1우선주", "A001065", extra_value, "1,000")],
        columns=("주권종류", "단축코드", extra_column, "기준가격(원)"),
    )
    with pytest.raises(DisclosureError):
        parse_notice(filing, "99301", body)


def test_company_alias_applies_only_to_its_issuer():
    tym = SecurityKey("002900", "KR7002900009", "1973-06-26", None, "KOSPI", "common")
    facts = NoticeSection(1, "ex_price", "주식회사 티와이엠", "보통주", "2023-03-30", "유상증자")
    universe = {tym: {"tym"}, SAMSUNG: {"tym"}}
    assert resolve_notice_security("00290", facts, universe) == tym
    with pytest.raises(DisclosureError):
        resolve_notice_security("01014", facts, universe)


def test_failed_price_keeps_verified_security_and_date_scope():
    day = "2016-09-30"
    filing, body = _price_notice(day, [("1우선주", "오류")])
    with pytest.raises(DisclosureError, match="Unsupported KIND quantity"):
        parse_notice(filing, "99301", body)
    assert notice_security_scope(filing, "99301", body, SAMSUNG_UNIVERSE) == {(SAMSUNG_PREF, day)}
    _, body = _price_notice(day, [("1우선주", "오류"), ("보통주", "9,200")])
    assert notice_security_scope(filing, "99301", body, SAMSUNG_UNIVERSE) == {(SAMSUNG_PREF, day), (SAMSUNG, day)}
    _, body = _price_notice(day, [("1우선주", "오류"), ("알 수 없음", "9,200")])
    with pytest.raises(DisclosureError):
        notice_security_scope(filing, "99301", body, SAMSUNG_UNIVERSE)
    with pytest.raises(DisclosureError):
        notice_security_scope(filing, "99301", replace(body, final=False), SAMSUNG_UNIVERSE)


@pytest.mark.parametrize("accession,code,isin,listing,names", [
    ("20220408000415", "263050", "KR7263050007", "2018-12-24", {"유틸렉스"}),
    ("20171103000029", "006730", "KR7006730006", "1995-10-06", {"서부티엔디", "서부t&d"}),
])
def test_verified_bilingual_issuer_names_keep_the_exact_security_interval(accession, code, isin, listing, names):
    from shared.tests.test_market_resolutions import official_body
    filing, form, body = official_body(accession)
    facts, = parse_notice(filing, form, body)
    key = SecurityKey(code, isin, listing, None, "KOSDAQ", "common")
    assert resolve_notice_security(code[:5], facts, {key: names}) == key
    for issuer, altered in [("01014", key), (code[:5], replace(key, listing="2026-01-01")),
                            (code[:5], replace(key, delisting=facts.effective))]:
        with pytest.raises(DisclosureError, match="does not identify one KRX security"):
            resolve_notice_security(issuer, facts, {altered: names})
    # The same spelling under another issuer cannot use this issuer's aliases.
    other = replace(SAMSUNG, listing="1975-01-01")
    with pytest.raises(DisclosureError):
        resolve_notice_security("01014", facts, {other: names})


def test_actual_yuyu_aggregated_other_shares_do_not_select_one_preferred_series():
    from shared.tests.test_market_resolutions import official_body
    filing, form, body = official_body("20210316000101")
    common, preferred = parse_notice(filing, form, body)
    universe = {
        SecurityKey("000220", "KR7000220004", "1975-11-18", None, "KOSPI", "common"): {"유유제약"},
        SecurityKey("000225", "KR7000221002", "1990-01-05", None, "KOSPI", "preferred"): {"유유제약1우"},
        SecurityKey("000227", "KR7000222000", "2000-06-20", None, "KOSPI", "preferred"): {"유유제약2우b"},
    }
    assert resolve_notice_security("00022", common, universe).code == "000220"
    assert preferred.added_shares == 1_294_945
    with pytest.raises(DisclosureError, match="does not identify one KRX security"):
        resolve_notice_security("00022", preferred, universe)
