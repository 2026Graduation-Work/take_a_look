"""Normalize supported KIND forms before resolving price observations."""

import re
from dataclasses import dataclass, replace
from fractions import Fraction
from html import unescape

from .actions import deal_table, official_date, valid_isin
from .disclosures import DisclosureError, Evidence, require
from .kind_market import EXCHANGE

CLASS = r"(?:보통주식?|[0-9]*우선주식?|종류주식[0-9]*)"
OTHER_INSTRUMENT = re.compile(r"\b(?:ETF|ETN|ELW)\b|상장지수(?:펀드|증권)|주식워런트증권|신주인수권증[서권]", re.I)
DAY = r"(?:\d{4}년\s*\d{1,2}월\s*\d{1,2}일|\d{4}[.-]\d{2}[.-]\d{2})"
NUMBER = r"[+-]?[\d,]+"
IDENTITY = (
    rf"(?:(?P<class>{CLASS})\s+)?표준코드\s*:\s*(?P<isin>[A-Z]{{2}}[0-9A-Z]{{9}}[0-9])"
    r"\s*\(\s*단축코드\s*:\s*A(?P<code>[0-9A-Z]{6})\s*\)"
)
PRICE_FORMS = frozenset({"70793", "72100", "99301", "99302", "99321", "99322", "99328",
                         "99331", "99332", "99343", "99409"})
TABLE_LISTINGS = frozenset({"32003", "32004", "32005", "70760", "70763", "70764", "70765", "70791", "70795"})
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
        if re.search(r"회사분할|인적분할|합병|재상장", title):
            return "structural"
        if "이전상장" in title:
            return "transfer"
        if "신규상장" in title:
            return "new_listing"
        if "상호변경" in title:
            return "rename"
        if re.search(r"권리락|배당락|권배락|기준가|추가상장|변경상장|상장안내", title):
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
    day = official_date(_field(rows, r"[456]\.(?:적용일|거래재개일)"))
    reason = _field(rows, r"[345]\.사유", required=form != "99409") or "장기간 매매거래정지 후 재개"
    note = _field(rows, r"[678]\.기타", required=False)
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
            require(base is not None, "KIND fixed reference price missing")
            kind = "ex_price" if form in {"99301", "99302"} else "listing_price"
            sections.append(NoticeSection(index, kind, company, values[0], day, reason,
                                          base=_integer(base), previous_market=previous_market,
                                          previous_close=previous_close, **identity))
    return sections


def _listed_table(filing, rows):
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
    par = [row for row in rows if len(row) == 5 and row[1] == "변경전액면가(원)" and row[3] == "변경후액면가(원)"]
    require(len(par) <= 1, "KIND listing face values are ambiguous")
    listing_reason = _field(rows, r"[34]\.변경상장사유", required=False)
    sections = []
    for index, (share_class, code, *added) in enumerate(securities, 1):
        after = [_integer(row[1]) for row in rows if len(row) == 3 and row[0] == share_class
                 and re.fullmatch(NUMBER, row[1]) and re.fullmatch(DAY, row[2])]
        require(len(after) <= 1, "KIND listing total is ambiguous")
        reason = sorted({row[1] for row in rows if len(row) >= 5 and row[0] == share_class})
        sections.append(NoticeSection(index, "listing", company, share_class, day,
                                      " · ".join(reason) or listing_reason or filing.title,
                                      code=_short(code), shares_after=after[0] if after else None,
                                      added_shares=_integer(added[0], signed=True) if added else None,
                                      par_before=_integer(par[0][2]) if par else None,
                                      par_after=_integer(par[0][4]) if par else None))
    return sections


def _listed_text(html):
    html = re.sub(r"(?is)<(?:script|style)\b[^>]*>.*?</(?:script|style)>", " ", html)
    text = " ".join(unescape(re.sub(r"<[^>]+>", " ", html)).split())
    sections = []
    for index, block in enumerate(text.split("◎")[1:], 1):
        segment = re.match(rf"(.+?)\s+(?:(?:{CLASS})\s+)?(?:주권\s*)?(추가상장|변경상장|신규상장|재상장)", block)
        if not segment:
            continue
        company, section_type = segment.groups()
        dates = set(re.findall(rf"(?<![신])(?:변경상장일|상장일)\s*:\s*({DAY})", block))
        require(len(dates) == 1, "KIND text listing effective date is ambiguous")
        day = official_date(dates.pop())
        reason = re.findall(r"(?:증자방법|변경사유)\s*:\s*(.+?)(?=\s+[①-⑳▶◎]|$)", block)
        reason = " · ".join(reason) or block[:block.find("①")].strip()
        par = re.findall(rf"(?:1주의\s*금액|1주의\s*액면가액)\s*:\s*({NUMBER})원(?:\s*→\s*({NUMBER})원)?", block)
        require(len(par) <= 1, "KIND listing face value is ambiguous")
        identities = list(re.finditer(IDENTITY, block))
        require(identities, "KIND text listing lacks exact security identifiers")
        for identity in identities:
            label = identity["class"]
            if label is None and len(identities) == 1:
                labels = set(re.findall(rf"기명식\s*({CLASS})\s*[\d,]+주", block))
                require(len(labels) == 1, "KIND text listing share class is ambiguous")
                label = labels.pop()
            require(label is not None and valid_isin(identity["isin"]), "KIND text listing security identity differs")
            quantities = re.findall(
                rf"기명식\s*{re.escape(label)}\s*({NUMBER})주(?:\s*\([^)]*\))?\s*(?:→\s*({NUMBER})주)?", block)
            require(len(quantities) <= 1, "KIND text listing quantities are ambiguous")
            before = after = delta = None
            if quantities:
                left, right = quantities[0]
                if right:
                    before, after = _integer(left), _integer(right)
                    delta = after - before
                elif section_type == "추가상장":
                    delta = _integer(left)
                else:
                    after = _integer(left)
            kind = "new_listing" if section_type == "신규상장" else "listing"
            sections.append(NoticeSection(index, kind, company, label, day, reason,
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
    if form in TEXT_LISTINGS:
        return _listed_text(text)
    rows = deal_table(text)
    if form in {"70766", "70767"}:
        return _flat_rights(rows)
    if form in PRICE_FORMS:
        return _price_table(form, rows)
    if form in TABLE_LISTINGS:
        return _listed_table(filing, rows)
    if form in {"71474", "11307"}:
        return _terms(filing, form, [row for row in rows if any(row)])
    raise DisclosureError(f"Unsupported KIND market-action form {form}")


def match_notice(filing, form, facts, body, evidence, securities):
    """Bind by explicit identifiers or by a unique issuer and disclosed share class."""
    company = normal_company(facts.company)
    share_class = "common" if facts.share_label in {"보통주", "보통주식"} else "preferred"
    labeled_company = normal_company(facts.company + facts.share_label.removesuffix("식"))
    matches = [key for key, names in securities.items()
               if key.active(facts.effective) and key.share_class == share_class
               and (facts.code is None or facts.code == key.code)
               and (facts.isin is None or facts.isin == key.isin)
               and (facts.code or share_class == "common" and company in names
                    or share_class == "preferred" and re.fullmatch(r"[0-9]+우선주식?", facts.share_label)
                    and labeled_company in names or facts.kind == "rename" and any(
                   normal_company(name) in names for name in facts.reason.split(" · ")))]
    if len(matches) != 1:
        raise DisclosureError(f"KIND notice does not identify one KRX security: {facts.company} {facts.share_label}")
    return Notice(matches[0], filing.accession, form, filing.published.isoformat(), filing.company_id,
                  filing.title, replace(facts, company=facts.company.strip()), (filing.evidence, *evidence),
                  body.document_no, body.family, body.final)
