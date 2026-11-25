"""Normalize supported KIND forms before resolving price observations."""

import re
from dataclasses import dataclass, replace
from datetime import date
from fractions import Fraction
from html import unescape

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
FIXED_REFERENCE_FORMS = frozenset({"70795", "32103"})
PRICE_FORMS = FIXED_REFERENCE_FORMS | {"70793", "72100", "99301", "99302", "99311", "99321", "99322", "99326", "99328",
                                         "99331", "99332", "99334", "99336", "99343", "99409", "32108"}
TABLE_LISTINGS = frozenset({"32002", "32003", "32004", "32005", "32006", "70760", "70763", "70764", "70765", "70779", "70791"})
TEXT_LISTINGS = frozenset({"68151", "68152", "68154", "68155"})


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


def _price_table(form, rows):
    company = _field(rows, r"1\.회사명")
    if form in FIXED_REFERENCE_FORMS:
        day = official_date(_field(rows, r"3\.적용일"))
        reasons = [row[1] for row in rows if len(row) in {2, 3} and _compact(row[0]) == "4.사유"]
        require(len(reasons) == 1, "KIND fixed-reference reason is missing or ambiguous")
        reason = reasons[0]
    else:
        day = official_date(_field(rows, r"[456]\.(?:적용일|거래재개일)"))
        reason = _field(rows, r"[345]\.사유", required=form != "99409") or "장기간 매매거래정지 후 재개"
    note = _field(rows, r"[678]\.기타", required=False)
    if form in FIXED_REFERENCE_FORMS and re.search(r"무상증자|권리락|주식배당", note):
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
    header = [row for row in rows if row[0].startswith("2.") and "주권종류" in row]
    require(len(header) == 1, "KIND price table header missing")
    columns = [_compact(cell) for cell in header[0][1:]]
    require(columns[0] == "주권종류", "Invalid KIND price class header")
    after = rows[rows.index(header[0]) + 1:]
    securities = [row for row in after if re.fullmatch(CLASS, row[0])]
    require(securities, "KIND price table identifies no ordinary or preferred shares")
    sections = []
    for index, values in enumerate(securities, 1):
        require(len(values) == len(columns), "Invalid KIND price table row")
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
            base = fields.get("기준가격(원)") or fields.get("기준가격")
            if form in FIXED_REFERENCE_FORMS:
                base = fields.get("기준가(원)")
            require(base is not None, "KIND fixed reference price missing")
            kind = "ex_price" if form in {"99301", "99302", "99311"} else "listing_price"
            sections.append(NoticeSection(index, kind, company, values[0], day, reason,
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
             if [_compact(field) for field in row] == ["4.추가상장후총발행주식수", "주권종류", "주식수(주)", "배당기산일"]]
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
    relisting = form == "68156"
    heading = "재상장" if relisting else "신규상장"
    company = one(rf"^[-◎]\s*(.+?)\s+주권\s+{heading}\s+내역", text,
                  "KIND numbered listing company is missing")
    named_class = one(rf"①\s*상장종목명\s*-\s*한글종목명\s*:\s*\S+?({CLASS})(?=\s|\()",
                      text, "KIND numbered listing share class is missing")
    effective = one(rf"②\s*상장일\s*:\s*({DAY})(?=\s+③)", text, "KIND numbered listing date is missing")
    identifiers = (r"(?:종목코드|표준코드)\s*:\s*" if relisting else r"종목코드\s*:\s*표준코드\s+")
    short = r"단축코드(?:\s+|\s*:\s*)" if relisting else r"단축코드\s*:\s*"
    isin, code = one(
        rf"④\s*{identifiers}([A-Z0-9]{{12}})\s*\({short}(A[0-9A-Z]{{6}})\)(?=\s+⑤)",
        text, "KIND numbered listing identifiers are missing",
    )
    registered = r"(?:기명식\s*|-\s*)" if relisting else r"(?:기명식\s*)?"
    label, shares = one(
        rf"⑤\s*주식의\s*종류와\s*수\s*:\s*{registered}({CLASS})\s*({NUMBER})주(?=\s+⑥)",
        text, "KIND numbered listing share quantity is missing",
    )
    require(valid_isin(isin) and named_class.removesuffix("식") == label.removesuffix("식"),
            "KIND numbered listing security identity differs")
    return [NoticeSection(1, "new_listing", company, label, official_date(effective), filing.title,
                          code=_short(code), isin=isin, shares_after=_integer(shares))]


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


def _class_relisting_text(filing, text):
    marker = r"\((\d+)\)\s*(보통주|종류주식)\s*(?=①\s*상장종목명)"
    company = one(r"^◎\s*(.+?)\s+주권\s+재상장\s+내역\(인적분할\)\s*(?=\(1\))",
                  text, "KIND class relisting company is missing")
    spans = list(re.finditer(marker, text))
    require([match.groups() for match in spans] == [("1", "보통주"), ("2", "종류주식")],
            "KIND class relisting sections do not reconcile")
    sections = []
    for index, match in enumerate(spans):
        block = text[match.end():spans[index + 1].start() if index + 1 < len(spans) else len(text)]
        label = match[2]
        name_class = label if label == "보통주" else r"[0-9]+우선주"
        one(rf"①\s*상장종목명\s*-\s*한글종목명\s*:\s*\S+?{name_class}(?=\s+-)", block,
            "KIND class relisting share name is missing")
        day = one(rf"②\s*상장일\s*:\s*({DAY})(?=\s+③)", block, "KIND class relisting date is missing")
        isin, code = one(r"④\s*표준코드\s*:\s*([A-Z0-9]{12})\s*\(단축코드\s*:\s*(A[0-9A-Z]{6})\)(?=\s+⑤)",
                         block, "KIND class relisting identifiers are missing")
        shares = one(rf"⑤\s*주식의\s*종류와\s*수\s*:\s*기명식\s*{label}\s*({NUMBER})주(?=\s+⑥)",
                     block, "KIND class relisting share quantity differs")
        require(valid_isin(isin), "KIND class relisting ISIN is invalid")
        sections.append(NoticeSection(index + 1, "new_listing", company, label, official_date(day), filing.title,
                                      code=_short(code), isin=isin, shares_after=_integer(shares)))
    require(len({row.isin for row in sections}) == len({row.code for row in sections}) == len(sections),
            "KIND class relisting identifiers are duplicated")
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


def _merger_quantity_total(field, label):
    lot = rf"-\s*기명식\s*{re.escape(label)}\s*({NUMBER})주\s*\(제(\d+)회\)"
    match = re.fullmatch(rf"({NUMBER})주((?:\s*{lot})+)", field)
    require(match is not None, "Invalid KIND merger quantity lots")
    lots = re.findall(lot, match[2])
    total = _integer(match[1])
    quantities = [_integer(quantity) for quantity, _ in lots]
    require(len({round_no for _, round_no in lots}) == len(lots) and all(quantity > 0 for quantity in quantities)
            and sum(quantities) == total, "KIND merger quantity total does not reconcile")
    return total


def _listed_text(html, form):
    text = _document_text(html)
    sections = []
    for block in text.split("◎")[1:]:
        segment = re.match(rf"(.+?)\s+(?:(?:{CLASS})\s+)?(?:주권\s*)?(추가상장|변경상장|신규상장|재상장)", block)
        if not segment:
            continue
        company, section_type = segment.groups()
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
        quantity_field = (one(r"①\s*주식의\s*종류와\s*수\s*:\s*(.+?)\s+②", block,
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
            if len(quantities) > 1 and form == "68154" and reason == "합병" and len(identities) == 1:
                delta = _merger_quantity_total(quantity_field, label)
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
            sections.append(NoticeSection(len(sections) + 1, kind, company, label, day, reason,
                                          code=identity["code"], isin=identity["isin"], shares_before=before,
                                          shares_after=after, added_shares=delta,
                                          par_before=_integer(par[0][0]) if par and par[0][1] else None,
                                          par_after=_integer(par[0][1] or par[0][0]) if par else None))
    require(sections, "KIND document has no supported listing section")
    return sections


def _terms(filing, form, rows):
    bonus = form == "11307"
    company = _field(rows, r"회사명:", required=bonus) or filing.company
    day = official_date(_field(rows, r"4\.(?:신주배정기준일|배당기준일)"))
    listed = _field(rows, r"8\.신주의상장예정일", required=False) if bonus else ""
    listed = official_date(listed) if listed not in {"", "-"} else None
    sections = []
    labels = (r"5\.1주당신주배정주식수", r"3\.증자전발행주식총수", r"1\.신주의종류와수") if bonus else (
        r"1\.1주당배당주식수\(주\)", r"3\.발행주식총수\(주\)", r"2\.배당주식총수\(주\)")
    for share_label in ("보통주식", "종류주식"):
        values = []
        for label in labels:
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
        sections.append(NoticeSection(len(sections) + 1, "bonus_terms" if bonus else "dividend_terms",
                                      company, share_label, day, filing.title, shares_before=_integer(shares),
                                      added_shares=_integer(added), ratio=Fraction(ratio), listing=listed))
    require(sections, "KIND terms contain no positive per-share allocation")
    return sections


def parse_notice(filing, form, body):
    text = body.text()
    if form in {"68152", "68156"}:
        flattened = _document_text(text)
        if form == "68156" and re.search(r"재상장\s+내역\(인적분할\)\s+\(1\)\s*보통주\s*①", flattened):
            return _class_relisting_text(filing, flattened)
        circled = (r"①\s*상장종목명" if form == "68156"
                   else r"④\s*종목코드\s*:\s*표준코드\s+(?=[A-Z]{2})")
        if re.search(circled, flattened):
            return _circled_listing_text(filing, flattened, form)
    if form in TEXT_LISTINGS:
        return _listed_text(text, form)
    if form == "68156":
        return _relisting_text(filing, text)
    rows = deal_table(text)
    if form in {"70766", "70767", "32101"}:
        return _flat_rights(rows)
    if form in PRICE_FORMS:
        return _price_table(form, rows)
    if form in TABLE_LISTINGS:
        return _listed_table(filing, form, rows)
    if form in {"71474", "11307"}:
        return _terms(filing, form, [row for row in rows if any(row)])
    raise DisclosureError(f"Unsupported KIND market-action form {form}")


def _preferred_name_matches(facts, company, names):
    parsed = re.fullmatch(r"([0-9]+)우선주식?([A-Z]?)", facts.share_label)
    if not parsed:
        return False
    series, suffix = parsed.groups()
    candidates = {f"{name}{series}{label}{suffix.casefold()}"
                  for name in {company, company.removesuffix("공업")}
                  for label in ("우", "우선주")}
    return bool(candidates & names)


def match_notice(filing, form, facts, body, evidence, securities):
    """Bind by explicit identifiers or by a unique issuer and disclosed share class."""
    company = normal_company(facts.company)
    share_class = "common" if facts.share_label in {"보통주", "보통주식"} else "preferred"
    matches = [key for key, names in securities.items()
               if key.active(facts.effective) and key.share_class == share_class
               and (facts.code is None or facts.code == key.code)
               and (facts.isin is None or facts.isin == key.isin)
               and (facts.code or share_class == "common" and company in names
                    or share_class == "preferred" and _preferred_name_matches(facts, company, names) or facts.kind == "rename" and any(
                   normal_company(name) in names for name in facts.reason.split(" · ")))]
    if len(matches) != 1:
        raise DisclosureError(f"KIND notice does not identify one KRX security: {facts.company} {facts.share_label}")
    return Notice(matches[0], filing.accession, form, filing.published.isoformat(), filing.company_id,
                  filing.title, replace(facts, company=facts.company.strip()), (filing.evidence, *evidence),
                  body.document_no, body.family, body.final)
