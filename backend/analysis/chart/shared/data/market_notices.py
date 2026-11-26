"""Normalize supported KIND forms before resolving price observations."""

import json
import re
from collections import defaultdict
from dataclasses import dataclass, replace
from datetime import date
from fractions import Fraction
from functools import lru_cache
from html import unescape
from pathlib import Path

from .actions import deal_table, official_date, valid_isin
from .disclosures import DisclosureError, Evidence, one, require
from .kind_market import EXCHANGE

CLASS = r"(?:보통주식?|[0-9]*우선주식?[A-Z]?|종류주식[0-9]*)"
OTHER_INSTRUMENT = re.compile(r"\b(?:ETF|ETN|ELW)\b|상장지수(?:펀드|증권)|주식워런트증권|신주인수권증[서권]", re.I)
DAY = r"(?:\d{4}년\s*\d{1,2}월\s*\d{1,2}일|\d{4}[.-]\d{2}[.-]\d{2})"
NUMBER = r"[+-]?[\d,]+"
IDENTITY = (
    rf"(?:(?P<class>{CLASS})\s+)?표준코드\s*:\s*(?P<isin>[A-Z]{{2}}[0-9A-Z]{{9}}[0-9])"
    r"\s*\(\s*단축코드\s*:\s*A(?P<code>[0-9A-Z]{6})\s*\)"
)
CLASS_RELISTING = (
    r"^◎\s*(.+?)\s+(?:보통)?주권\s+재상장(?:\s+내역\((?:재상장-)?인적분할\)"
    r"|\(재상장-인적분할\)\s+및\s+종류주권\s+신규상장\s+내역"
    r"|\s+및\s+(?:종류주권\s+)?신규상장\s+내역\s*\(재상장-인적분할\))\s*(?=\(1\))"
)


@dataclass(frozen=True)
class FormSpec:
    kind: str
    layout: str
    labels: tuple[str, ...] = ()


_PRICE_DATE = r"[456]\.(?:적용일|거래재개일)"
_FIXED_REFERENCE = FormSpec("listing_price", "fixed_reference", (r"3\.적용일",))
_EX_PRICE = FormSpec("ex_price", "price_table", (_PRICE_DATE,))
_LISTING_PRICE = FormSpec("listing_price", "price_table", (_PRICE_DATE,))
_FLAT_RIGHTS = FormSpec("ex_price", "flat_rights")
_TABLE_LISTING = FormSpec("listing", "listed_table")
_TEXT_LISTING = FormSpec("listing", "listed_text")
_BONUS_LABELS = (r"5\.1주당신주배정주식수", r"3\.증자전발행주식총수", r"1\.신주의종류와수")
_DIVIDEND_ALLOCATION = r"1\.1주당배당주식수\(주\)"
_DIVIDEND_QUANTITY = r"2\.배당주식총수\(주\)"

FORMS = {
    "11307": FormSpec("bonus_terms", "terms", _BONUS_LABELS),
    "61474": FormSpec("dividend_terms", "terms", (_DIVIDEND_ALLOCATION, r"3\.발행주식총수", _DIVIDEND_QUANTITY)),
    "71474": FormSpec("dividend_terms", "terms", (_DIVIDEND_ALLOCATION, r"3\.발행주식총수\(주\)", _DIVIDEND_QUANTITY)),
    "68151": _TEXT_LISTING,
    "68152": FormSpec("listing", "numbered_listing"),
    "68154": _TEXT_LISTING,
    "68155": FormSpec("listing", "hangul_listing"),
    "68156": FormSpec("new_listing", "relisting"),
    "68157": FormSpec("new_listing", "preferred_initial_listing"),
    "70780": FormSpec("auction", "halted_division_auction"),
    **dict.fromkeys(("32101", "70766", "70767"), _FLAT_RIGHTS),
    **dict.fromkeys(("32103", "70795"), _FIXED_REFERENCE),
    **dict.fromkeys(("99301", "99302", "99311"), _EX_PRICE),
    **dict.fromkeys(("32002", "32003", "32004", "32005", "32006", "70760", "70763", "70764", "70765",
                     "70779", "70791"), _TABLE_LISTING),
    **dict.fromkeys(("32108", "70718", "70793", "72100", "99321", "99322", "99323", "99326", "99328", "99331",
                     "99332", "99334", "99335", "99336", "99343", "99360", "99362", "99409"), _LISTING_PRICE),
}


class NoticeError(DisclosureError):
    def __init__(self, failed_check, message):
        super().__init__(message)
        self.failed_check = failed_check


@dataclass(frozen=True)
class SecurityKey:
    code: str
    isin: str
    listing: str
    delisting: str | None
    market: str
    share_class: str

    def __post_init__(self):
        require(re.fullmatch(r"[0-9A-Z]{6}", self.code) and valid_isin(self.isin)
                and self.market in {"KOSPI", "KOSDAQ", "KONEX"}
                and self.share_class in {"common", "preferred"}, "Invalid KRX security key")
        require(official_date(self.listing) == self.listing and
                (self.delisting is None or self.listing < self.delisting == official_date(self.delisting)),
                "Invalid KRX listing interval")

    def active(self, day):
        return self.listing <= day and (self.delisting is None or day < self.delisting)


@dataclass(frozen=True)
class NoticeSection:
    section: int
    kind: str
    company: str
    share_label: str
    effective: str
    reason: str
    code: str | None = None
    isin: str | None = None
    base: int | None = None
    evaluation: int | None = None
    low: int | None = None
    high: int | None = None
    par_before: int | None = None
    par_after: int | None = None
    shares_before: int | None = None
    shares_after: int | None = None
    added_shares: int | None = None
    ratio: Fraction | None = None
    listing: str | None = None
    previous_market: str | None = None
    previous_close: int | None = None
    renamed_company: str | None = None


@dataclass(frozen=True)
class Notice:
    security: SecurityKey
    accession: str
    form: str
    published: str
    company_id: str
    title: str
    facts: NoticeSection
    evidence: tuple[Evidence, ...]
    document_no: str
    family: tuple[str, ...]
    final: bool


def normal_company(value):
    return re.sub(r"\s+|\(주\)|㈜|주식회사", "", value).casefold()


def share_identity(label):
    label = re.sub(r"\s+", "", label)
    if label in {"보통주", "보통주식", "보통주권"}:
        return "common", "", ""
    if match := re.fullmatch(r"([0-9]*)우선주(?:식)?([A-Z]?)", label):
        return "preferred", *match.groups()
    if match := re.fullmatch(r"종류주(?:식|권)([0-9]*)", label):
        return "preferred", match[1], ""
    return None


def kind_topic(filing):
    title = re.sub(r"\s+", "", filing.title)
    if OTHER_INSTRUMENT.search(filing.title) or re.match(r"(?:\[정정\])?(?:주식선물|주식옵션)", title):
        return None
    if filing.submitter in EXCHANGE:
        operative = re.sub(r"^(?:\[[^]]+\])+", "", title)
        if re.match(r"조회공시|상장예비심사", operative):
            return None
        if re.match(r"(?:주권|주식)?매매거래(?:정지|재개)", operative) and not re.match(
            r"(?:주권|주식)?매매거래(?:정지해제|재개)(?:시(?:의)?|에따른)?기준가", operative
        ):
            return None
        if not re.search(r"상장안내|추가상장|변경상장|신규상장|재상장|권리락|배당락|권배락|기준가|평가가격", operative):
            return None
        if re.search(r"회사분할|인적분할|합병|재상장", operative):
            return "structural"
        if "이전상장" in operative:
            return "transfer"
        if "신규상장" in operative:
            return "new_listing"
        if "상호변경" in operative:
            return "rename"
        return "candidate"
    elif re.search(r"주식배당(?:결정|예고)|무상증자결정", title):
        return "terms"
    return None


def _integer(value, *, signed=False):
    require(re.fullmatch(NUMBER, value.removesuffix("원").strip()), "Unsupported KIND quantity")
    amount = int(value.removesuffix("원").replace(",", "").strip())
    require(signed or amount > 0, "Nonpositive KIND price or quantity")
    return amount


def _compact(value):
    return re.sub(r"\s+", "", value)


def _field(rows, label, *, required=True):
    found = [row[1] for row in rows if len(row) == 2 and re.fullmatch(label, _compact(row[0]))]
    require(len(found) == 1 or (not found and not required), f"KIND field missing or ambiguous: {label}")
    return found[0] if found else ""


def _short(value):
    require(re.fullmatch(r"A[0-9A-Z]{6}", value), "Invalid KIND security short code")
    return value[1:]


def _flat_rights(rows):
    require(len(rows) >= 2 and
            [_compact(item) for item in rows[0]][:4] == ["1.회사명", "2.주권종류", "3.단축코드", "4.기준가(원)"]
            and _compact(rows[0][-2]) in {"5.권리락실시일", "5.배당락실시일", "5.권배락실시일"}
            and _compact(rows[0][-1]) == "6.사유", "Unsupported KIND rights/dividend table")
    sections = []
    for index, row in enumerate(rows[1:], 1):
        require(len(row) == 6 and re.fullmatch(CLASS, row[1]), "Invalid KIND rights/dividend row")
        company, share_class, raw_code, base, effective, reason = row
        sections.append(NoticeSection(index, "ex_price", company, share_class, official_date(effective), reason,
                                      code=_short(raw_code), base=_integer(base)))
    return sections


def _price_table_day(spec, rows):
    return official_date(_field(rows, spec.labels[0]))


def _price_table_rows(rows):
    header = [row for row in rows if row[0].startswith("2.") and "주권종류" in row]
    require(len(header) == 1, "KIND price table header missing")
    columns = [_compact(cell) for cell in header[0][1:]]
    require(columns[0] == "주권종류", "Invalid KIND price class header")
    require(len(set(columns)) == len(columns) and not any(
        "표준코드" in column or "ISIN" in column.upper() for column in columns
    ), "Invalid KIND price table identity columns")
    after = rows[rows.index(header[0]) + 1:]
    end = next((index for index, row in enumerate(after) if re.match(r"\d+\.", row[0])), len(after))
    require(end and all(len(row) == len(columns) and share_identity(row[0]) for row in after[:end])
            and not any(share_identity(row[0]) for row in after[end:]),
            "Invalid KIND price table identity rows")
    return columns, after[:end]


def _price_table(form, spec, rows):
    company = _field(rows, r"1\.회사명")
    day = _price_table_day(spec, rows)
    fixed = spec.layout == "fixed_reference"
    if fixed:
        reasons = [row[1] for row in rows if len(row) in {2, 3} and _compact(row[0]) == "4.사유"]
        require(len(reasons) == 1, "KIND fixed-reference reason is missing or ambiguous")
        reason = reasons[0]
    else:
        reason = _field(rows, r"[345]\.사유", required=form != "99409") or "장기간 매매거래정지 후 재개"
    note = _field(rows, r"[678]\.기타", required=False)
    if fixed and re.search(r"무상증자|권리락|주식배당", note):
        reason += f" · {note}"
    if form == "99409" and re.search(r"감자|자본감소|분할|합병", note):
        reason = "재개 관련 종전 회사 조치 검토"
    previous_prices = re.findall(r"(코넥스|코스닥|유가증권)시장에서의\s*최종.*?종가\s*\(([\d,]+)원\)", note)
    require(len(previous_prices) <= 1, "KIND former market reference is ambiguous")
    previous_market = previous_close = None
    if previous_prices:
        market, close = previous_prices[0]
        previous_market = {"코넥스": "KONEX", "코스닥": "KOSDAQ", "유가증권": "KOSPI"}[market]
        previous_close = _integer(close)
    columns, securities = _price_table_rows(rows)
    if form == "70718":
        require("단축코드" in columns and "평가가격(원)" not in columns,
                "KIND new-listing reference lacks a coded fixed price")
    sections = []
    for index, values in enumerate(securities, 1):
        fields = dict(zip(columns, values))
        identity = {"code": _short(fields["단축코드"])} if "단축코드" in fields else {}
        if "평가가격(원)" in fields:
            price_columns = ("평가가격(원)", "최고호가(원)", "최저호가(원)")
            require(all(label in fields for label in price_columns), "KIND opening auction price column missing")
            evaluation, high, low = [_integer(fields[label]) for label in price_columns]
            require(low <= evaluation <= high and any("최초가격이기준가격이됨" in _compact(" ".join(row)) for row in rows),
                    "Invalid KIND opening auction range or method")
            sections.append(NoticeSection(index, "auction", company, values[0], day, reason,
                                          evaluation=evaluation, low=low, high=high, **identity))
        else:
            require(form not in {"99323", "99360", "99362"}, "KIND opening auction fields are missing")
            base = fields.get("기준가격(원)") or fields.get("기준가격")
            if fixed:
                base = fields.get("기준가(원)")
            require(base is not None, "KIND fixed reference price missing")
            sections.append(NoticeSection(index, spec.kind, company, values[0], day, reason,
                                          base=_integer(base), previous_market=previous_market,
                                          previous_close=previous_close, **identity))
    return sections


def _combined_additional_listing(rows, securities):
    identities = {(row[0], row[1]) for row in securities}
    require(len(identities) == 1 and all(len(row) == 3 for row in securities),
            "KIND additional listing tranches mix securities or quantities")
    share_class, code = next(iter(identities))
    amounts = [_integer(row[2]) for row in securities]
    start = [i for i, row in enumerate(rows)
             if len(row) == 4 and _compact(row[0]) in {"4.추가상장후총발행주식수", "4.추가상장후상장주식총수"}
             and [_compact(field) for field in row[1:]] == ["주권종류", "주식수(주)", "배당기산일"]]
    require(len(start) == 1, "KIND additional listing tranche totals are missing")
    offset = start[0] + 1
    totals_rows = rows[offset:offset + len(amounts)]
    require(len(totals_rows) == len(amounts) and all(
        len(row) == 3 and row[0] == share_class and re.fullmatch(DAY, row[2]) for row in totals_rows
    ) and offset + len(amounts) < len(rows) and _compact(rows[offset + len(amounts)][0]) == "5.상장일",
            "KIND additional listing tranche totals are ambiguous")
    totals = [_integer(row[1]) for row in totals_rows]
    require(totals[0] > amounts[0] and all(
        current - previous == added for previous, current, added in zip(totals, totals[1:], amounts[1:])
    ), "KIND additional listing tranche totals do not reconcile")
    return (share_class, code, str(sum(amounts))), totals[-1]


def _listed_table(filing, form, rows):
    if any(row[0].startswith("1.변경전 상호") for row in rows):
        company = _field(rows, r"1\.변경전상호")
        day = official_date(_field(rows, r"4\.상장일"))
        new_names = [row[-1] for row in rows if len(row) >= 3 and row[-2] == "한글"]
        require(new_names, "KIND name change lacks the new issuer name")
        return [NoticeSection(1, "rename", company, "보통주", day, " · ".join(new_names))]
    new_listings = [row for row in rows if len(row) == 4 and re.fullmatch(CLASS, row[0])
                    and valid_isin(row[1]) and re.fullmatch(r"A[0-9A-Z]{6}", row[2])]
    if new_listings:
        company = [row[-1] for row in rows if len(row) == 4 and _compact(row[0]) == "1.회사명" and row[2] == "한글"]
        require(len(company) == 1, "KIND new listing company is ambiguous")
        day = official_date(_field(rows, r"\d+\.상장일\(매매개시일\)"))
        return [NoticeSection(i, "new_listing", company[0], label, day, filing.title, code=_short(code),
                              isin=isin, shares_after=_integer(shares))
                for i, (label, isin, code, shares) in enumerate(new_listings, 1)]
    company = _field(rows, r"1\.회사명")
    day = official_date(_field(rows, r"[456]\.(?:상장일|변경상장일|상장일\(매매개시일\))"))
    securities = [row for row in rows if len(row) in {2, 3} and re.fullmatch(CLASS, row[0])
                  and re.fullmatch(r"A[0-9A-Z]{6}", row[1])]
    require(securities, "KIND listing table lacks security codes")
    combined_total = None
    if form == "70791" and len({(row[0], row[1]) for row in securities}) < len(securities):
        tranche, combined_total = _combined_additional_listing(rows, securities)
        securities = [tranche]
    par = [row for row in rows if len(row) == 5 and row[1] == "변경전액면가(원)" and row[3] == "변경후액면가(원)"]
    require(len(par) <= 1, "KIND listing face values are ambiguous")
    listing_reason = _field(rows, r"[34]\.변경상장사유", required=False)
    sections = []
    for index, (share_class, code, *added) in enumerate(securities, 1):
        after = [combined_total] if combined_total is not None else [
            _integer(row[1]) for row in rows if len(row) == 3 and row[0] == share_class
            and re.fullmatch(NUMBER, row[1]) and re.fullmatch(DAY, row[2])
        ]
        require(len(after) <= 1, "KIND listing total is ambiguous")
        reason = sorted({row[1] for row in rows if len(row) >= 5 and row[0] == share_class})
        sections.append(NoticeSection(index, "listing", company, share_class, day,
                                      " · ".join(reason) or listing_reason or filing.title,
                                      code=_short(code), shares_after=after[0] if after else None,
                                      added_shares=_integer(added[0], signed=True) if added else None,
                                      par_before=_integer(par[0][2]) if par else None,
                                      par_after=_integer(par[0][4]) if par else None))
    return sections


def _document_text(html):
    html = re.sub(r"(?is)<(?:script|style)\b[^>]*>.*?</(?:script|style)>", " ", html)
    return " ".join(unescape(re.sub(r"<[^>]+>", " ", html)).split())


def _circled_listing_text(filing, text, form):
    headingless = form == "68152" and text.startswith("①")
    heading = "재상장" if form == "68156" else "신규상장"
    company = None if headingless else one(
        rf"^[-◎]\s*(.+?)\s+주권\s+{heading}\s+내역", text, "KIND numbered listing company is missing",
    )
    return [_circled_listing_section(filing, text, company, 1)]


def _circled_listing_section(filing, text, company, section, declared_class=None):
    name, named_class = one(rf"①\s*상장종목(?:명)?\s*-\s*한글종목명\s*:\s*(\S+?)({CLASS})(?=\s|\()",
                            text, "KIND numbered listing share class is missing")
    if company is None:
        require(filing.company and normal_company(name) == normal_company(filing.company),
                "KIND headingless listing issuer differs from the publication list")
        company = name
    elif declared_class is not None:
        named_issuer, heading_issuer = normal_company(name), normal_company(company)
        listed_alias = (heading_issuer == "디엘이앤씨" and named_issuer == normal_company(filing.company) == "dl이앤씨")
        require(named_issuer == heading_issuer or listed_alias,
                "KIND numbered relisting issuer differs from the heading and publication list")
    effective = one(rf"②\s*상장일\s*:\s*({DAY})(?=\s+③)", text, "KIND numbered listing date is missing")
    identifiers = r"(?:종목코드\s*:\s*(?:표준코드\s+)?|표준코드\s*:\s*)"
    isin, code = one(
        rf"④\s*{identifiers}([A-Z0-9]{{12}})\s*\(단축코드(?:\s*:\s*|\s+)(A[0-9A-Z]{{6}})\)(?=\s+⑤)",
        text, "KIND numbered listing identifiers are missing",
    )
    label, shares = one(
        rf"⑤\s*주식의\s*종류와\s*수\s*(?::\s*(?:기명식\s*|-\s*)?|-\s*)({CLASS})\s*({NUMBER})주(?=\s+⑥)",
        text, "KIND numbered listing share quantity is missing",
    )
    if declared_class == "종류주식":
        consistent = label == declared_class and re.fullmatch(r"\d+우선주", named_class)
    elif declared_class and declared_class != "보통주":
        named_preferred = re.fullmatch(r"\d*우선주", named_class) if declared_class == "종류주권" else declared_class == named_class
        consistent = named_preferred and label in {"우선주", named_class}
        label = named_class
    else:
        consistent = named_class.removesuffix("식") == label.removesuffix("식") and declared_class in {None, label}
    require(valid_isin(isin) and consistent, "KIND numbered listing security identity differs")
    return NoticeSection(section, "new_listing", company, label, official_date(effective), filing.title,
                         code=_short(code), isin=isin, shares_after=_integer(shares))


def _relisting_text(filing, html):
    text = _document_text(html)
    company = one(r"(?:^|-)\s*(.+?)\s+주권\s+재상장\s+내역", text, "KIND relisting company is missing")
    label, shares = one(rf"2\.\s*주식의\s*종류와\s*수\s*:\s*기명식\s*({CLASS})\s*({NUMBER})주",
                        text, "KIND relisting share quantity is missing")
    isin, code = one(r"8\.\s*종목코드\s*:\s*([A-Z0-9]{12})\s*\(단축코드\s*:?\s*(A[0-9A-Z]{6})\)",
                     text, "KIND relisting identifiers are missing")
    year, month, day = one(r"9\.\s*상\s*장\s*일\s*:\s*(\d{4})\.\s*(\d{1,2})\.\s*(\d{1,2})",
                            text, "KIND relisting date is missing")
    require(valid_isin(isin), "KIND relisting ISIN is invalid")
    return [NoticeSection(1, "new_listing", company, label, date(int(year), int(month), int(day)).isoformat(),
                          filing.title, code=_short(code), isin=isin, shares_after=_integer(shares))]


def _class_relisting_text(filing, text, company):
    marker = (r"\((\d+)\)\s*(보통주권?|종류주식|종류주권(?:\((\d+우선주)(?:\(신형\))?\))?)"
              r"\s*(?=①\s*상장종목(?:명)?\s*-)")
    spans = list(re.finditer(marker, text))
    classes = [match[3] or ("보통주" if match[2] == "보통주권" else match[2]) for match in spans]
    require(len(spans) >= 2 and len(spans) == len(re.findall(r"①\s*상장종목(?:명)?\s*-", text))
            and [int(match[1]) for match in spans] == list(range(1, len(spans) + 1))
            and classes[0] == "보통주" and len(set(classes)) == len(classes),
            "KIND class relisting sections do not reconcile")
    sections = []
    end_points = [match.start() for match in spans[1:]] + [len(text)]
    for section, (match, stop, label) in enumerate(zip(spans, end_points, classes), 1):
        sections.append(_circled_listing_section(filing, text[match.end():stop], company, section, label))
    require(len({row.share_label for row in sections}) == len(sections), "KIND class relisting share classes are duplicated")
    require(len({row.isin for row in sections}) == len({row.code for row in sections}) == len(sections),
            "KIND class relisting identifiers are duplicated")
    require(len({row.effective for row in sections}) == 1, "KIND class relisting effective dates differ")
    return sections


def _numbered_merger_listing(block, first_section):
    company = one(rf"^(.+?)\s+{CLASS}\s+및\s+{CLASS}\s+추가상장\s+①", block,
                  "KIND numbered merger listing company is missing")
    quantities = one(r"①\s*주식의\s*종류와\s*수\s*(.+?)\s+②", block,
                     "KIND numbered merger listing share quantities are missing")
    share_row = rf"-\s*기명식\s*({CLASS})\s*({NUMBER})주\s*\(제(\d+)회\)"
    require(re.fullmatch(rf"(?:\s*{share_row})+", quantities), "Invalid KIND numbered merger quantity rows")
    shares = re.findall(share_row, quantities)
    methods = one(r"⑤\s*증자방법\s+(.+?)\s+⑥", block, "KIND numbered merger listing methods are missing")
    schedule = one(r"⑥\s*상장일\s+(.+?)\s+⑦", block, "KIND numbered merger listing dates are missing")
    round_field = r"-\s*제(\d+)회\s*:\s*"
    require(re.fullmatch(rf"(?:\s*{round_field}합병)+", methods)
            and re.fullmatch(rf"(?:\s*{round_field}{DAY})+", schedule), "Invalid KIND numbered merger methods or dates")
    merger_rounds = re.findall(round_field + "합병", methods)
    dates = re.findall(round_field + f"({DAY})", schedule)
    rounds = {entry[2] for entry in shares}
    require(len(shares) == len(rounds) == len(merger_rounds) == len(dates)
            and rounds == set(merger_rounds) == {entry[0] for entry in dates},
            "KIND numbered merger listing rounds do not reconcile")
    codes = one(r"⑦\s*코드\s+(.+)", block, "KIND numbered merger listing codes are missing")
    identities = list(re.finditer(IDENTITY, codes))
    labels = {entry[0] for entry in shares}
    require(len(identities) == len(shares) == len(labels) and labels == {entry["class"] for entry in identities}
            and len({entry["isin"] for entry in identities}) == len(labels)
            and len({entry["code"] for entry in identities}) == len(labels)
            and all(valid_isin(entry["isin"]) for entry in identities),
            "KIND numbered merger listing identities do not reconcile")
    by_class, by_round = {entry["class"]: entry for entry in identities}, dict(dates)
    return [
        NoticeSection(section, "listing", company, label, official_date(by_round[round_no]), "합병",
                      code=by_class[label]["code"], isin=by_class[label]["isin"], added_shares=_integer(quantity))
        for section, (label, quantity, round_no) in enumerate(shares, first_section)
    ]


def _additional_quantity_total(field, label):
    name = rf"기명식\s*{re.escape(label)}\s*"
    lot = rf"[-▶]\s*(?:제\s*(\d+)회\s*:\s*)?{name}({NUMBER})주(?:\s*\(제\s*(\d+)회\))?"
    match = re.fullmatch(rf"(?:(?:{name})?({NUMBER})주\s*)?((?:\s*{lot})+)", field)
    require(match is not None, "Invalid KIND additional listing quantity lots")
    lots = re.findall(lot, match[2])
    rounds = [before or after for before, _, after in lots]
    total = sum(_integer(quantity) for _, quantity, _ in lots)
    require(len(lots) > 1 and all(bool(before) != bool(after) for before, _, after in lots)
            and len(set(rounds)) == len(lots) and (not match[1] or _integer(match[1]) == total),
            "KIND additional listing quantity total does not reconcile")
    return total


def _split_round_listing(block):
    company = one(r"^(.+?)\s+변경상장\(액면분할\)\s+①", block, "KIND round split company is missing")
    field = one(r"㉯\s*주식의\s*종류와\s*수\s+(.+?)\s+㉰", block, "KIND round split quantities are missing")
    lot = (rf"▶\s*기명식\s*({CLASS})\s*({NUMBER})주\s*\(제\s*\d+(?:\s*~\s*\d+)?회\)\s*→\s*"
           rf"({NUMBER})주\s*\(제\s*(\d+)회\)\s*▶\s*변경주식수\s*:\s*({NUMBER})주")
    require(re.fullmatch(rf"(?:\s*{lot})+", field), "Invalid KIND round split quantities")
    quantities = re.findall(lot, field)
    par_before, par_after = one(rf"㉰\s*1주의\s*금액\s*:\s*({NUMBER})원\s*→\s*({NUMBER})원(?=\s+②)",
                               block, "KIND round split par values are missing")
    schedule = one(r"⑤\s*변경상장일\s+(.+?)\s+⑥\s*변경사유\s*:\s*액면분할\s+⑦", block,
                   "KIND round split schedule or reason is missing")
    scheduled = rf"-\s*제(\d+)회\s*:\s*({DAY})"
    require(re.fullmatch(rf"(?:\s*{scheduled})+", schedule), "Invalid KIND round split calendar")
    days = re.findall(scheduled, schedule)
    identities = list(re.finditer(IDENTITY, block.split("⑦", 1)[1]))
    labels = {entry[0] for entry in quantities}
    rounds = {entry[3] for entry in quantities}
    require(len(quantities) == len(labels) == len(rounds) == len(days) == len(identities)
            and rounds == {entry[0] for entry in days} and labels == {entry['class'] for entry in identities}
            and len({entry['code'] for entry in identities}) == len(labels)
            and len({entry['isin'] for entry in identities}) == len(labels)
            and all(valid_isin(entry['isin']) for entry in identities), "KIND round split identities or dates differ")
    by_class, by_round = {entry['class']: entry for entry in identities}, dict(days)
    sections = []
    for label, prior, current, round_no, change in quantities:
        before, after, delta = _integer(prior), _integer(current), _integer(change, signed=True)
        require(after - before == delta, "KIND round split change does not reconcile")
        sections.append(NoticeSection(len(sections) + 1, "listing", company, label, official_date(by_round[round_no]),
                                      "액면분할", code=by_class[label]['code'], isin=by_class[label]['isin'],
                                      shares_before=before, shares_after=after, added_shares=delta,
                                      par_before=_integer(par_before), par_after=_integer(par_after)))
    return sections


def _division_common_listing(common, blocks):
    company = one(r"^(.+?)\s+변경상장\([^①]*회사분할\(존속\)[^①]*\)\s+관련\s+공통사항\s+①",
                  common, "KIND division common issuer is missing")
    applied = one(rf"[④⑤]\s*변경상장일\s*:\s*({DAY})(?=\s+[⑤⑥]\s*코드)", common,
                  "KIND division common effective date is missing")
    identities = list(re.finditer(IDENTITY, common))
    require(len(identities) == 1 and valid_isin(identities[0]['isin']), "KIND division common identity is ambiguous")
    identity = identities[0]
    division = [block.strip() for block in blocks if block.strip().startswith("회사분할(존속)에 따른 자본감소 내용")]
    require(len(division) == 1 and not any(re.search(IDENTITY, block) for block in blocks),
            "KIND division section is ambiguous")
    label = one(rf"▶\s*기명식\s*({CLASS})\s*{NUMBER}주", division[0], "KIND division share class is missing")
    require(label == "보통주" and identity['class'] in {None, label}
            and len(re.findall(r"③\s*변경사유\s*:\s*회사분할\(존속\)\s*$", division[0])) == 1,
            "KIND division common share or reason differs")
    return [NoticeSection(1, "listing", company, label, official_date(applied), "회사분할(존속)",
                          code=identity['code'], isin=identity['isin'])]


def _preferred_initial_listing(filing, text):
    company = one(r"^◎\s*(.+?)\s+종류주식\s+신규상장\s+내역\s+①", text, "KIND preferred listing company is missing")
    label = one(r"①\s*상장종목\s*-\s*한글종목명\s*:\s*\S+?(\d+우선주)(?=\s+\()", text,
                "KIND preferred listing class is missing")
    shares = one(rf"②\s*주식의\s*종류와\s*수\s*:\s*기명식\s*우선주\s*({NUMBER})주(?=\s+③)", text,
                  "KIND preferred listing quantity does not match its class")
    require(re.search(r"⑥\s*증자방법\s*:\s*합병에\s*따른\s*우선주\s*신주\s*발행\s+⑦", text),
            "KIND preferred listing method is unsupported")
    isin, code = one(r"⑦\s*종목코드\s*:\s*표준코드\s+([A-Z0-9]{12})\s*\(단축코드\s*:\s*(A[0-9A-Z]{6})\)(?=\s+⑧)",
                     text, "KIND preferred listing identifiers are missing")
    day = one(rf"⑧\s*상장일\s*:\s*({DAY})(?=\s+⑨)", text, "KIND preferred listing date is missing")
    require(valid_isin(isin), "KIND preferred listing ISIN is invalid")
    return [NoticeSection(1, "new_listing", company, label, official_date(day), filing.title,
                          code=_short(code), isin=isin, shares_after=_integer(shares))]


def _unchanged_shares_par_change(block):
    company = one(r"^(.+?)\s+변경상장\(자본감소\)\s+①", block, "KIND per-class par change issuer is missing")
    quantities = one(r"②\s*주식의\s*종류와\s*수\s*:\s*변경사항\s*없음\s+(.+?)\s+③", block,
                     "KIND per-class par change share counts are missing")
    share = rf"-\s*(\S+?)({CLASS})\s*:\s*({NUMBER})주\s*\(제\s*\d+회\)"
    require(re.fullmatch(rf"(?:\s*{share})+", quantities), "Invalid KIND unchanged share counts")
    shares = re.findall(share, quantities)
    par = one(r"③\s*1주의\s*액면가액\s+및\s+총자본금\(변경전\s*→\s*변경후\)\s+(.+?)\s+④", block,
              "KIND per-class par change values are missing")
    capital = (rf"-\s*기명식\s*({CLASS})\s*▶\s*액면가액\s*:\s*({NUMBER})원\s*→\s*({NUMBER})원\s*"
               rf"▶\s*총자본금\s*:\s*({NUMBER})원\s*→\s*({NUMBER})원")
    require(re.fullmatch(rf"(?:\s*{capital})+", par), "Invalid KIND per-class par values")
    changes = re.findall(capital, par)
    day = one(rf"⑦\s*변경상장일\s*:\s*({DAY})\s+⑧\s*변경사유\s*:\s*액면가액\s*감액\s+⑨\s*코드", block,
              "KIND per-class par change date or reason is missing")
    identities = list(re.finditer(IDENTITY, block.split("⑨", 1)[1]))
    labels = {label for name, label, _ in shares if normal_company(name) == normal_company(company)}
    require(len(shares) == len(labels) == len(changes) == len(identities)
            and labels == {row[0] for row in changes} == {row['class'] for row in identities}
            and len({row['code'] for row in identities}) == len({row['isin'] for row in identities}) == len(labels)
            and all(valid_isin(row['isin']) for row in identities), "KIND per-class par change identities differ")
    amounts = {label: _integer(quantity) for _, label, quantity in shares}
    by_class = {row['class']: row for row in identities}
    sections = []
    for label, old, new, capital_before, capital_after in changes:
        shares = amounts[label]
        before, after = _integer(old), _integer(new)
        require(before > after and before * shares == _integer(capital_before) and after * shares == _integer(capital_after),
                "KIND per-class par change capital does not reconcile")
        sections.append(NoticeSection(len(sections) + 1, "listing", company, label, official_date(day), "액면가액 감액",
                                      code=by_class[label]['code'], isin=by_class[label]['isin'], shares_before=shares,
                                      shares_after=shares, par_before=before, par_after=after))
    return sections


def _verify_warrant_change(text):
    require(text.count("◎") == 1, "KIND warrant change mixes listing blocks")
    name = r"[^▶→:()]+?\s+\d+WR"
    original, resized, destination = one(
        rf"②\s*상장신주인수권\s*증권의\s*수\s*\(변경전\s*→\s*변경후\)\s*▶\s*({name})\s+{NUMBER}증권\s*→"
        rf"\s*\(수량\s*변경\)\s*({name})\s+{NUMBER}증권\s*→\s*\(목적주권\s*변경\)\s*({name})\s+{NUMBER}증권(?=\s+③)",
        text, "KIND warrant changed instruments are missing or ambiguous",
    )
    listed = one(rf"①\s*상장종목\s*:\s*({name})(?=\s+②)", text, "KIND warrant listing lacks its subject")
    require(original == listed == resized and destination != original, "KIND warrant listing subject differs")
    exercises = one(
        r"③\s*변경후\s*신주인수권\s*행사로\s*발행할\s*주식의\s*종류\s*및\s*수\s+(.+?)\s+④", text,
        "KIND warrant underlying shares are missing",
    )
    prices = one(r"⑥\s*변경후\s*신주인수권\s*행사가격\s+(.+?)\s+⑦", text, "KIND warrant exercise prices are missing")
    periods = one(r"⑦\s*변경후\s*신주인수권\s*행사기간\s+(.+?)\s+⑧", text, "KIND warrant exercise periods are missing")
    identifiers = one(r"⑧\s*표준코드\s+(.+)\Z", text, "KIND warrant identifiers are missing")
    require(re.findall(r"[①-⑳]", text) == list("①②③④⑤⑥⑦⑧"),
            "KIND warrant listing fields differ")
    effective = one(rf"④\s*변경상장일\s*:\s*({DAY})\s+⑤\s*변경사유\s*:\s*회사분할합병\s+⑥", text,
                    "KIND warrant date or reason is missing")
    official_date(effective)
    for field, value in (
        (exercises, rf"[^▶]+?\s+기명식\s*보통주\s*{NUMBER}주"),
        (prices, rf"{NUMBER}원"),
        (periods, rf"{DAY}\s*~\s*{DAY}"),
        (identifiers, r"KRA[0-9A-Z]{8}[0-9]\s*\(단축코드\s+J[0-9A-Z]{8}\)"),
    ):
        expected = r"\s*".join(rf"▶\s*{re.escape(subject)}\s*:\s*{value}" for subject in (original, destination))
        require(re.fullmatch(expected, field), "KIND warrant-only fields do not cover both instruments")
    isins, codes = zip(*re.findall(r"(KRA[0-9A-Z]{8}[0-9])\s*\(단축코드\s+(J[0-9A-Z]{8})\)", identifiers), strict=True)
    require(len(set(isins)) == len(set(codes)) == 2, "KIND warrant-only identifiers are duplicated")


def _listed_text(html, form, *, final):
    text = _document_text(html)
    if form == "68155" and re.match(r"^◎\s*[^◎]+?\s+신주인수권증권\s+변경상장\s+①", text):
        require(final, "KIND warrant change requires the final document")
        _verify_warrant_change(text)
        return []
    correction = None
    if form == "68154" and text.startswith("[정정]"):
        correction = re.fullmatch(
            rf"\[정정\]\s+◎\s*(.+?)\s+정정항목\s*:\s*상장일\s+정정전\s*:\s*{DAY}\s*→\s*({DAY})\s+-{{8,}}\s+◎\s*(.+)", text,
        )
        if correction:
            require(correction[3].startswith(correction[1] + " ①"), "KIND corrected listing issuer or class differs")
            text = "◎ " + correction[3]
    blocks = [block.strip() for block in text.split("◎")[1:]]
    if form == "68151" and blocks and re.search(r"회사분할\(존속\)[^①]*관련\s+공통사항\s+①", blocks[0]):
        return _division_common_listing(blocks[0], blocks[1:])
    if form == "68155" and len(blocks) == 1 and re.search(r"⑤\s*변경상장일\s+-\s*제", blocks[0]):
        return _split_round_listing(blocks[0])
    if (form == "68151" and len(blocks) == 1
            and len(re.findall(r"▶\s*액면가액\s*:", blocks[0])) > 1
            and re.search(r"③\s*1주의\s*액면가액\s+및\s+총자본금", blocks[0])):
        return _unchanged_shares_par_change(blocks[0])
    sections = []
    for block in blocks:
        segment = re.match(rf"(.+?)\s+(?:(?:{CLASS})\s+)?(?:주권\s*)?(추가상장|변경상장|신규상장|재상장)", block)
        if not segment:
            continue
        company, section_type = segment.groups()
        if form == "68155" and re.match(r".+?\s+변경상장\(영문상호변경\)", block):
            changed = one(
                rf"\A.+?\s+변경상장\(영문상호변경\)\s+1\.\s*변경내역\(변경전\s*→\s*변경후\)\s*-\s*영문종목명\s+o\s+"
                rf"[A-Za-z0-9 &.()-]+?\s*→\s*[A-Za-z0-9 &.()-]+?\s+2\.\s*변경일자\s*:\s*({DAY})\s+"
                r"3\.\s*변경사유\s*:\s*영문상호\s*변경(?:\s+※ 변경상장일에 매매거래정지 해제됨)?\Z",
                block, "KIND English name change block is ambiguous",
            )
            require(len(sections) == 1 and sections[0].reason == "액면분할"
                    and normal_company(company) == normal_company(sections[0].company)
                    and official_date(changed) == sections[0].effective,
                    "KIND English name change differs from the preceding split listing")
            continue
        if form == "68154" and section_type == "추가상장" and re.search(r"⑥\s*상장일\s+-\s*제", block):
            sections.extend(_numbered_merger_listing(block, len(sections) + 1))
            continue
        dates = set(re.findall(rf"(?<![신])(?:변경상장일|상장일)\s*:\s*({DAY})", block))
        require(len(dates) == 1, "KIND text listing effective date is ambiguous")
        day = official_date(dates.pop())
        reason = re.findall(r"(?:증자방법|변경사유)\s*:\s*(.+?)(?=\s+[①-⑳▶◎]|$)", block)
        reason = " · ".join(reason) or block[:block.find("①")].strip()
        par = re.findall(rf"(?:1주의\s*금액|(?:1주의\s*)?액면가액)\s*:\s*({NUMBER})원(?:\s*→\s*({NUMBER})원)?", block)
        require(len(par) <= 1, "KIND listing face value is ambiguous")
        identities = list(re.finditer(IDENTITY, block))
        require(identities, "KIND text listing lacks exact security identifiers")
        quantity_field = (one(r"①\s*주식의\s*종류와\s*수\s*:?\s*(.+?)\s+②", block,
                              "KIND additional listing share quantities are missing") if form == "68154" else block)
        for identity in identities:
            label = identity["class"]
            if label is None and len(identities) == 1:
                labels = set(re.findall(rf"기명식\s*({CLASS})\s*[\d,]+주", quantity_field))
                if not labels:
                    ticker_name = re.search(r"상장종목\s*:\s*(\S+)", block)
                    if ticker_name and (match := re.search(rf"{CLASS}$", ticker_name[1])):
                        labels.add(match[0])
                require(len(labels) == 1, "KIND text listing share class is ambiguous")
                label = labels.pop()
            require(label is not None and valid_isin(identity["isin"]), "KIND text listing security identity differs")
            quantities = re.findall(
                rf"기명식\s*{re.escape(label)}\s*({NUMBER})주(?:\s*\([^)]*\))?\s*(?:→\s*({NUMBER})주)?", quantity_field)
            before = after = delta = None
            if (len(quantities) > 1 and form == "68154" and section_type == "추가상장" and len(identities) == 1
                    and reason in {"합병", "국내CB전환", "유상증자(제3자배정)"}):
                delta = _additional_quantity_total(quantity_field, label)
            elif quantities:
                require(len(quantities) == 1, "KIND text listing quantities are ambiguous")
                left, right = quantities[0]
                if right:
                    before, after = _integer(left), _integer(right)
                    delta = after - before
                elif section_type == "추가상장":
                    delta = _integer(left)
                else:
                    after = _integer(left)
            kind = "new_listing" if section_type == "신규상장" else "listing"
            renamed = None
            if form == "68151" and kind == "listing" and reason == "상호변경":
                names = re.findall(r"㉯\s*상장종목약명\(영문약명\)\s*-\s*([^()]+)\(영문약명:[^()]+(?:\([^()]+\))?\)\s*→\s*"
                                   r"([^()]+)\(영문약명:[^()]+(?:\([^()]+\))?\)\s*㉰", block)
                if len(names) == 1:
                    old, new = (normal_company(value) for value in names[0])
                    if label not in {"보통주", "보통주식"} and old.endswith("우") and new.endswith("우"):
                        old, new = old[:-1], new[:-1]
                    if old == normal_company(company) and old != new:
                        renamed = new
            sections.append(NoticeSection(len(sections) + 1, kind, company, label, day, reason,
                                          code=identity["code"], isin=identity["isin"], shares_before=before,
                                          shares_after=after, added_shares=delta,
                                          par_before=_integer(par[0][0]) if par and par[0][1] else None,
                                          par_after=_integer(par[0][1] or par[0][0]) if par else None,
                                          renamed_company=renamed))
    require(sections, "KIND document has no supported listing section")
    if correction:
        require(len(sections) == 1 and sections[0].effective == official_date(correction[2]),
                "KIND corrected listing date differs from the operative section")
    return sections


def _terms(filing, spec, rows):
    bonus = spec.kind == "bonus_terms"
    company = _field(rows, r"회사명:", required=bonus) or filing.company
    day = official_date(_field(rows, r"4\.(?:신주배정기준일|배당기준일)"))
    listed = _field(rows, r"8\.신주의상장예정일", required=False) if bonus else ""
    listed = official_date(listed) if listed not in {"", "-"} else None
    sections = []
    for share_label in ("보통주식", "종류주식"):
        values = []
        for label in spec.labels:
            start = [i for i, row in enumerate(rows) if len(row) == 3 and re.fullmatch(label, _compact(row[0]))]
            require(len(start) == 1, f"KIND dividend or bonus terms lack: {label}")
            first, following = rows[start[0]:start[0] + 2]
            if share_label == "보통주식":
                require(_compact(first[1]).removesuffix("(주)") == share_label, "KIND terms class differs")
                values.append(first[2])
            else:
                require(len(following) == 2 and
                        _compact(following[0]).removesuffix("(주)") in {"종류주식", "기타주식"}, "KIND terms class differs")
                values.append(following[1])
        ratio, shares, added = values
        if ratio in {"", "-", "0"}:
            continue
        require(re.fullmatch(r"\d+(?:\.\d+)?", ratio) and Fraction(ratio) > 0,
                "Invalid KIND per-share allocation")
        sections.append(NoticeSection(len(sections) + 1, spec.kind,
                                      company, share_label, day, filing.title, shares_before=_integer(shares),
                                      added_shares=_integer(added), ratio=Fraction(ratio), listing=listed))
    require(sections, "KIND terms contain no positive per-share allocation")
    return sections


def _final_bonus_terms_rows(rows):
    comparison = [index for index, row in enumerate(rows)
                  if list(map(_compact, row)) == ["항목", "정정사유", "정정전", "정정후"]]
    # One older comparison layout repeats the exact three-cell quantity field of the operative table.
    quantity_rows = [index for index, row in enumerate(rows)
                     if len(row) == 3 and _compact(row[0]) == "3.증자전발행주식총수"]
    if not comparison or len(quantity_rows) < 2:
        return rows
    declarations = [index for index, row in enumerate(rows)
                    if len(row) == 2 and _compact(row[0]) == "금융위원회/한국거래소귀중"]
    require(len(comparison) == len(declarations) == 1 and len(quantity_rows) == 2
            and comparison[0] < quantity_rows[0] < declarations[0] < quantity_rows[1],
            "KIND bonus correction lacks a unique operative declaration")
    return rows[declarations[0]:]


def _halted_division_auction(text, final):
    require(final and re.search(r"기준가 산정 등에 관한 안내\(회사분할\(인적분할\)\)", text),
            "KIND market announcement lacks a final division auction")
    company, label = one(rf"1\.\s*회사명\s*:\s*(.+?)\s+2\.\s*주권종류\s*:\s*({CLASS})\s+3\.\s*가격",
                         text, "KIND division auction issuer or share class is ambiguous")
    evaluation, high, low = map(_integer, one(
        rf"3\.\s*가격\s*:\s*-\s*평가가격\s*:\s*({NUMBER})원\s*-\s*최고호가\s*:\s*({NUMBER})원\s*"
        rf"-\s*최저호가\s*:\s*({NUMBER})원\s+4\.\s*기준가격결정", text, "KIND division auction range is ambiguous",
    ))
    reason, day = one(rf"6\.\s*사유\s*:\s*(회사분할\(인적분할\))\s+7\.\s*적용일\s*:\s*({DAY})\s+8\.\s*근거규정",
                      text, "KIND division auction reason or effective date is ambiguous")
    require(low <= evaluation <= high and "최초가격이기준가격이됨" in _compact(text)
            and re.search(r"9\.\s*기타\s*:\s*해당\s*주권은\s*향후\s*매매거래정지\s*해제에\s*대한\s*추가\s*안내시점까지\s*정지가\s*계속됨\Z", text),
            "KIND division auction range, method, or suspension terms differ")
    return [NoticeSection(1, "auction", company, label, official_date(day), reason,
                          evaluation=evaluation, low=low, high=high)]


def _hangul_name_change(text):
    company, old, label, old_english, new, new_english, old_short, old_short_en, new_short, new_short_en, day = one(
        rf"\A◎\s*(.+?)\s+변경상장\(한글종목명\s*변경\)\s+①\s*구분\(변경전\s*→\s*변경후\)\s+"
        rf"㉮\s*상장종목\(영문명\)\s*-\s*(\S+?)(?P<label>보통주(?:식)?)\(영문명:\s*([^()]+)\)\s*→\s*"
        rf"(\S+?)(?P=label)\(영문명:\s*([^()]+)\)\s+㉯\s*상장종목약명\(영문약명\)\s*-\s*"
        rf"(\S+)\(영문약명:\s*([^()]+)\)\s*→\s*(\S+)\(영문약명:\s*([^()]+)\)\s+"
        rf"②\s*변경상장\s*적용일\s*:\s*({DAY})\Z", text,
        "KIND Korean security name change is ambiguous",
    )
    require(normal_company(company) == normal_company(old) == normal_company(old_short)
            and normal_company(new) == normal_company(new_short) != normal_company(old)
            and old_english.strip() == new_english.strip() and old_short_en.strip() == new_short_en.strip(),
            "KIND Korean security name change has inconsistent names")
    return [NoticeSection(1, "rename", company, label, official_date(day), f"{new} · {new_short}")]


def superseded_merger_facts(filing, form, body):
    """Read the non-final implementation fields solely as evidence for a review boundary."""
    require(form == "68151" and not body.final and kind_topic(filing) == "structural",
            "KIND structural review requires the original non-final implementation")
    text = _document_text(body.text())
    require(text.startswith("◎") and text.count("◎") == 2, "KIND structural review requires two listing blocks")
    addition, rename = [block.strip() for block in text.split("◎")[1:]]
    company, label, lots = one(r"^(.+?)\s+(보통주)\s+추가상장\s+①\s*주식의\s*종류와\s*수\s*:\s*총\s+(.+?)\s+②",
                                addition, "KIND structural review lacks official additional share quantities")
    added = _additional_quantity_total(lots, label)
    requires_total = re.match(rf"{NUMBER}주\s*[-▶]", lots)
    methods, day = one(rf"⑤\s*증자방법\s*:\s*(.+?)\s+⑥\s*상장일\s*:\s*({DAY})\s+⑦",
                       addition, "KIND structural review lacks the implementation date or method")
    rounds = re.findall(r"\(제\s*(\d+)회\)", lots)
    methods = re.fullmatch(r"분할합병\(제\s*(\d+)회\)\s*,\s*합병\(제\s*(\d+)회\)", methods)
    require(requires_total and methods and rounds == list(methods.groups()),
            "KIND structural review share rounds do not match the merger methods")
    identities = list(re.finditer(IDENTITY, addition))
    require(len(identities) == 1, "KIND structural review additional listing identity is ambiguous")
    identity, = identities

    heading, old_name, interim_name = one(
        r"^(.+?)\s+변경상장\(상호변경\)\s+①.*?㉯\s*상장종목약명\(영문약명\)\s*-\s*"
        r"(\S+)\(영문약명:[^()]+\)\s*→\s*(\S+)\(영문약명:[^()]+\)\s*㉰",
        rename, "KIND structural review lacks the same-day official company rename",
    )
    final_count, = _listed_text(f"◎ {rename}", form, final=False)
    require(normal_company(company) == normal_company(heading) == normal_company(old_name)
            and normal_company(interim_name) != normal_company(old_name)
            and final_count.kind == "listing" and final_count.share_label == label
            and final_count.code == identity["code"] and final_count.isin == identity["isin"]
            and final_count.effective == official_date(day) and final_count.shares_after is not None
            and added < final_count.shares_after and final_count.shares_before is None,
            "KIND structural review listing and effective ownership do not agree")
    return replace(final_count, added_shares=added, renamed_company=normal_company(interim_name))


def parse_notice(filing, form, body):
    text = body.text()
    spec = FORMS.get(form)
    if spec is None:
        raise NoticeError(f"unsupported_form:{form}", f"Unsupported KIND market-action form {form}")
    layout = spec.layout
    if layout == "hangul_listing":
        flattened = _document_text(text)
        if re.match(r"^◎\s*[^◎]+?\s+변경상장\(한글종목명\s*변경\)", flattened):
            return _hangul_name_change(flattened)
    if layout == "halted_division_auction":
        return _halted_division_auction(_document_text(text), getattr(body, "final", False))
    if layout in {"numbered_listing", "relisting"}:
        flattened = _document_text(text)
        if layout == "relisting" and (heading := re.match(CLASS_RELISTING, flattened)):
            return _class_relisting_text(filing, flattened, heading[1])
        circled = (r"①\s*상장종목명" if layout == "relisting" else
                   r"^①\s*상장종목명|④\s*종목코드\s*:\s*표준코드\s+(?=[A-Z]{2})|"
                   r"④\s*표준코드\s*:\s*[A-Z0-9]{12}\s*\([^()]*\)\s+⑤\s*주식의\s*종류와\s*수\s*"
                   r"(?::?\s*-|:\s*(?=보통주))")
        if re.search(circled, flattened):
            return _circled_listing_text(filing, flattened, form)
    if layout in {"listed_text", "numbered_listing", "hangul_listing"}:
        return _listed_text(text, form, final=getattr(body, "final", False))
    if layout == "relisting":
        return _relisting_text(filing, text)
    if layout == "preferred_initial_listing":
        return _preferred_initial_listing(filing, _document_text(text))
    rows = deal_table(text)
    if layout == "flat_rights":
        return _flat_rights(rows)
    if layout in {"price_table", "fixed_reference"}:
        return _price_table(form, spec, rows)
    if layout == "listed_table":
        return _listed_table(filing, form, rows)
    if layout == "terms":
        rows = [row for row in rows if any(row)]
        if spec.kind == "dividend_terms":
            require("자회사의주요경영사항" not in _compact(filing.title)
                    and not any(_compact(row[0]) == "자회사인" for row in rows),
                    "KIND stock dividend terms belong to a subsidiary")
        if spec.kind == "bonus_terms" and getattr(body, "final", False):
            rows = _final_bonus_terms_rows(rows)
        return _terms(filing, spec, rows)
    raise DisclosureError(f"Unsupported KIND market-action layout {layout} for form {form}")


def _preferred_name_matches(facts, company, names):
    parsed = re.fullmatch(r"([0-9]+)우선주식?([A-Z]?)", facts.share_label)
    if not parsed:
        return False
    series, suffix = parsed.groups()
    candidates = {f"{name}{series}{label}{suffix.casefold()}"
                  for name in {company, company.removesuffix("공업")}
                  for label in ("우", "우선주")}
    return bool(candidates & names)


@lru_cache(maxsize=1)
def _issuer_aliases():
    groups = json.loads(Path(__file__).with_name("issuer_aliases.json").read_text(encoding="utf-8"))
    return {issuer: {normal_company(name) for name in names} for issuer, names in groups.items()}


def _reported_company_names(company_id, facts):
    company = normal_company(facts.company)
    aliases = _issuer_aliases().get(company_id[:5], set())
    return {company, *aliases} if company in aliases else {company}


def _preferred_series(company_names, names):
    roots = company_names | {name.removesuffix("공업") for name in company_names}
    return {match.groups() for name in names for root in roots
            if root and name.startswith(root)
            and (match := re.fullmatch(r"([0-9]*)우(?:선주(?:식)?)?([a-z]?)", name[len(root):]))}


def _same_series(series, suffix, known, *, allow_unnumbered_first):
    if series:
        known = {(number, letter) for number, letter in known if number} or known
    return any((not series or number == series or (allow_unnumbered_first and series == "1" and not number))
               and (not suffix or letter == suffix.casefold()) for number, letter in known)


def _coded_matches(facts, active, identity):
    _, series, suffix = identity
    matches = []
    for key, names in active.items():
        if facts.code not in {None, key.code} or facts.isin not in {None, key.isin}:
            continue
        if series or suffix:
            known = _preferred_series(_reported_company_names(key.code, facts), names)
            if known and not _same_series(series, suffix, known, allow_unnumbered_first=True):
                continue
        matches.append(key)
    return matches


def _uncoded_matches(company_id, facts, active, identity):
    share_class, series, suffix = identity
    company_names = _reported_company_names(company_id, facts)
    if share_class == "common":
        if facts.kind == "rename":
            company_names.update(normal_company(name) for name in facts.reason.split(" · "))
        return [key for key, names in active.items() if any(
            name in company_names or re.sub(r"보통주(?:식)?$", "", name) in company_names for name in names
        )]

    matches = []
    for key, names in active.items():
        known = _preferred_series(company_names, names)
        if not series and not suffix:
            if len(active) == 1 and (known or names & company_names):
                matches.append(key)
            continue
        if _same_series(series, suffix, known, allow_unnumbered_first=len(active) == 1):
            matches.append(key)
    return matches


def _identity_failure(facts):
    return NoticeError("notice_security_unresolved",
                       f"KIND notice does not identify one KRX security: {facts.company} {facts.share_label}")


def _notice_identity(facts):
    identity = share_identity(facts.share_label)
    try:
        effective = official_date(facts.effective)
    except ValueError as exc:
        raise _identity_failure(facts) from exc
    if identity is None or effective != facts.effective:
        raise _identity_failure(facts)
    return identity


def resolve_notice_security(company_id, facts, identity_universe):
    """Bind one notice section against all KRX listing intervals for its KIND issuer."""
    identity = _notice_identity(facts)
    if not re.fullmatch(r"[0-9A-Z]{5,6}", company_id):
        raise _identity_failure(facts)
    active = {key: names for key, names in identity_universe.items()
              if key.code.startswith(company_id[:5]) and key.active(facts.effective) and key.share_class == identity[0]}
    if facts.code is not None or facts.isin is not None:
        matches = _coded_matches(facts, active, identity)
    else:
        matches = _uncoded_matches(company_id, facts, active, identity)
    if len(matches) != 1 or len(company_id) == 6 and matches[0].code != company_id:
        raise _identity_failure(facts)
    return matches[0]


def notice_security_scope(filing, form, body, identity_universe):
    """Recover verified price-table identities and dates independently of price fields."""
    spec = FORMS.get(form)
    require(spec is not None and spec.layout in {"price_table", "fixed_reference"} and body.final,
            "KIND notice has no supported identity scope")
    rows = deal_table(body.text())
    company = _field(rows, r"1\.회사명")
    day = _price_table_day(spec, rows)
    columns, securities = _price_table_rows(rows)
    scope = set()
    for index, row in enumerate(securities, 1):
        fields = dict(zip(columns, row))
        code = _short(fields["단축코드"]) if "단축코드" in fields else None
        facts = NoticeSection(index, "", company, row[0], day, "", code=code)
        scope.add((resolve_notice_security(filing.company_id, facts, identity_universe), day))
    require(len(scope) == len(securities), "KIND price table duplicates the same security")
    return scope


def can_join_auction_identity(form, facts, final):
    return (final and form in {"99332", "99334"} and facts.kind == "auction"
            and facts.code is None and facts.isin is None)


def _share_series(label):
    return "보통주" if label == "보통주식" else label


def notice_section_key(notice):
    return notice.accession, notice.form, notice.facts.section


def auction_listing_index(notices):
    listings = defaultdict(list)
    for notice in notices:
        if notice.final and notice.facts.kind in {"listing", "new_listing"} and notice.facts.code and notice.facts.isin:
            listings[notice.company_id, notice.facts.effective].append(notice)
    return listings


def auction_identity_witness(form, facts, issuer, final, listings):
    """Find the unique coded listing and optional exact rename for an uncoded auction."""
    if not can_join_auction_identity(form, facts, final) or not re.fullmatch(r"[0-9A-Z]{5}", issuer):
        return ()
    name = normal_company(facts.company)
    same_issuer_session_class = [
        row for row in listings if row.final and row.company_id == issuer and row.security.code.startswith(issuer)
        and row.security.active(facts.effective) and row.facts.effective == facts.effective
        and _share_series(row.facts.share_label) == _share_series(facts.share_label)
        and row.facts.code == row.security.code and row.facts.isin == row.security.isin
    ]
    choices = []
    for row in same_issuer_session_class:
        section = row.facts
        if not (form == "99334" and section.kind == "new_listing" or form == "99332" and section.kind == "listing"
                and re.search(r"회사분할|인적분할|분할합병", _compact(section.reason))):
            continue
        listed_name = normal_company(section.company)
        if name == listed_name:
            choices.append((row,))
            continue
        aliases = [item for item in same_issuer_session_class if item.security == row.security
                   and item.accession == row.accession and item.document_no == row.document_no
                   and item.facts.kind == "listing" and item.facts.reason == "상호변경"
                   and normal_company(item.facts.company) == name and item.facts.renamed_company == listed_name]
        choices.extend((row, alias) for alias in aliases)
    return choices[0] if len(choices) == 1 else ()


def auction_identity_links(notices, listings):
    links = []
    for notice in notices:
        witness = auction_identity_witness(notice.form, notice.facts, notice.company_id, notice.final,
                                           listings.get((notice.company_id, notice.facts.effective), ()))
        if witness:
            require(notice.security == witness[0].security, "KIND auction differs from its witnessed KRX security")
            links.append({"Auction": list(notice_section_key(notice)),
                          "Witnesses": [list(notice_section_key(row)) for row in witness]})
    return sorted(links, key=lambda row: row["Auction"])


def match_notice(filing, form, facts, body, evidence, securities, *, identity_witness=(), identity_universe=None):
    """Bind by explicit identifiers or by a unique issuer and disclosed share class."""
    universe = securities if identity_universe is None else identity_universe
    if identity_witness:
        share_class, _, _ = _notice_identity(facts)
        witnessed = identity_witness[0].security
        require(can_join_auction_identity(form, facts, body.final) and witnessed in securities
                and witnessed.share_class == share_class and witnessed.active(facts.effective)
                and (not filing.company_id or witnessed.code.startswith(filing.company_id)),
                "KIND auction witness differs from the KRX listing interval")
        match = witnessed
    elif filing.company_id:
        match = resolve_notice_security(filing.company_id, facts, universe)
    else:
        identity = _notice_identity(facts)
        share_class = identity[0]
        active = {key: names for key, names in universe.items()
                  if key.active(facts.effective) and key.share_class == share_class}
        if facts.code is not None or facts.isin is not None:
            matches = _coded_matches(facts, active, identity)
        else:
            company = normal_company(facts.company)
            matches = [key for key, names in active.items()
                       if (share_class == "common" and company in names
                           or share_class == "preferred" and _preferred_name_matches(facts, company, names)
                           or facts.kind == "rename" and any(
                               normal_company(name) in names for name in facts.reason.split(" · ")))]
        if len(matches) != 1:
            raise _identity_failure(facts)
        match, = matches
    if match not in securities:
        raise _identity_failure(facts)
    return Notice(match, filing.accession, form, filing.published.isoformat(), filing.company_id,
                  filing.title, replace(facts, company=facts.company.strip()), (filing.evidence, *evidence),
                  body.document_no, body.family, body.final)
