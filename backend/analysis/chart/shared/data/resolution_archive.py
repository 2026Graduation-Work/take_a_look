"""Check the request and content of the official responses behind a resolution ledger."""

import csv
import json
import re
from datetime import date

from .disclosures import (
    KIND_SEARCH,
    PAGE_SIZE,
    Evidence,
    Response,
    collect_pages,
    kind_page,
    require,
)
from .kind_market import (
    COMPANY_SIZE,
    COMPANY_URL,
    DAILY_SIZE,
    DAILY_URL,
    KindBody,
    MarketFiling,
    company_page,
    daily_form,
    daily_page,
    kind_route,
)
from .market_notices import Notice, SecurityKey, parse_notice


def _response(archive, ref):
    paper = json.loads((archive / "receipts" / f"{ref.receipt}.json").read_bytes())
    return paper["request"], Response((archive / "objects" / ref.sha256).read_bytes(), paper["charset"], ref)


def _publication(archive, entry, code=None):
    start, end = (date.fromisoformat(entry[k]) for k in ("start", "end"))
    source = entry["source"]
    if source == "KIND daily disclosure list" and code is None and start == end:
        url, size, expected = DAILY_URL, DAILY_SIZE, {}
    elif source == "KIND company disclosure list" and code is not None:
        url, size = COMPANY_URL, COMPANY_SIZE
        expected = {"method": "searchDetailsSub", "searchCorpName": code, "repIsuSrtCd": f"A{code}",
                    "fromDate": str(start), "toDate": str(end)}
    elif source == "Archived KIND market actions" and code is not None:
        url, size = KIND_SEARCH, PAGE_SIZE
        expected = {"method": "searchDetailsMktactSubExt", "searchCorpName": code, "repIsuSrtCd": f"A{code}",
                    "fromData": str(start), "toData": str(end)}
    else:
        raise ValueError("Unsupported resolution publication archive source")
    refs = [Evidence(**row) for row in entry["pages"]]

    def get(page):
        require(page <= len(refs), "Official publication pages are incomplete")
        request, body = _response(archive, refs[page - 1])
        form = request.get("form") or {}
        required = daily_form(start, page) if source == "KIND daily disclosure list" else {
            **expected, "currentPageSize": str(size), "pageIndex": str(page),
        }
        require(request["url"] == url and all(form.get(key) == value for key, value in required.items()),
                "Official listing receipt is for a different scope or page")
        if source == "KIND daily disclosure list":
            return daily_page(body, start, page)
        if source == "KIND company disclosure list":
            return company_page(body, code, start, end, page)
        return kind_page(body, start, end, page)

    rows, span = collect_pages(source, start, end, size, get)
    require(span.rows == entry["rows"] and list(span.pages) == refs, "Official publication count differs from archive")
    if source == "Archived KIND market actions":
        return [MarketFiling(**{**vars(row), "stock_code": code}, displayed=row.published, submitter="한국거래소")
                for row in rows]
    return rows


def notice_facts_columns(facts):
    fields = {"Section": "section", "AppliedDate": "effective", "Kind": "kind", "Reason": "reason",
              "BasePrice": "base", "EvaluationPrice": "evaluation", "Low": "low", "High": "high",
              "ParBefore": "par_before", "ParAfter": "par_after", "SharesBefore": "shares_before",
              "SharesAfter": "shares_after", "AddedShares": "added_shares", "Ratio": "ratio",
              "Listing": "listing", "PreviousMarket": "previous_market", "PreviousClose": "previous_close"}
    return {key: getattr(facts, attribute) for key, attribute in fields.items()}


def _official_sections(archive, filing, document, form, refs):
    accession = filing.accession
    viewer = f"https://kind.krx.co.kr/common/disclsviewer.do?method=search&acptno={accession}"
    selection = f"https://kind.krx.co.kr/common/disclsviewer.do?method=searchContents&docNo={document}"
    viewer_request, shell = _response(archive, refs[-3])
    route_request, route = _response(archive, refs[-2])
    options = re.search(r"""<select\b[^>]*\bid=['"]mainDoc['"][^>]*>(.*?)</select>""", shell.text(), re.S)
    require(options and viewer_request["url"] == viewer and route_request["url"] == selection
            and route_request.get("referer") == viewer, "KIND notice viewer differs from official receipt")
    selected = re.search(r"""value=['"]""" + document + r"""\|([YN])['"]\s*selected""", options[1])
    expected_url, expected_form = kind_route(accession, route)
    body_request, body = _response(archive, refs[-1])
    require(selected and expected_form == form and f"/{document}/" in expected_url
            and body_request["url"] == expected_url and body_request.get("referer") == viewer,
            "KIND notice body receipt differs from its official document or form")
    family = tuple(re.findall(r"""value=['"]([0-9]{14})\|[YN]['"]""", options[1]))
    response = KindBody(body.body, body.charset, body.evidence, document, family, selected[1] == "Y")
    return {facts.section: facts for facts in parse_notice(filing, form, response)}, family, response.final



def verify_archive_bindings(folder, coverage, archive):
    with (folder / "notices.csv").open(encoding="utf-8", newline="") as stream:
        notices = [(row, tuple(Evidence(**raw) for raw in json.loads(row["Evidence"]))) for row in csv.DictReader(stream)]
    needed = {(row["AcptNo"], refs[0]) for row, refs in notices}
    filings = {}

    def add(rows):
        for row in rows:
            key = row.accession, row.evidence
            if key in needed:
                filings[key] = row

    for entry in coverage["daily"]:
        add(_publication(archive, entry))
    for table in ("company", "archived_market_actions"):
        for code, entries in coverage[table].items():
            for entry in entries:
                add(_publication(archive, entry, code))
    documents, official = {}, []
    for row, refs in notices:
        accession, document, form = (row[key] for key in ("AcptNo", "DocNo", "FormId"))
        filing = filings.get((accession, refs[0]))
        require(len(refs) == 4 and filing and filing.published.isoformat() == row["Published"]
                and filing.title == row["Title"], "KIND notice is not in its pinned publication list")
        key = (accession, document, form, refs)
        if key not in documents:
            documents[key] = _official_sections(archive, filing, document, form, refs)
        sections, family, final = documents[key]
        facts = sections.get(int(row["Section"]))
        security = SecurityKey(row["Code"], row["ISIN"], row["ListingDate"], row["DelistingDate"] or None,
                               row["Market"], row["ShareClass"])
        issuer = (filing.company_id or filing.stock_code)[:5]
        require(facts is not None and (not issuer or security.code.startswith(issuer))
                and (facts.code is None or facts.code == security.code)
                and (facts.isin is None or facts.isin == security.isin)
                and (facts.share_label in {"보통주", "보통주식"}) == (security.share_class == "common")
                and list(family) == json.loads(row["Family"]) and str(final) == row["Final"]
                and all(row[field] == (str(value) if value is not None else "")
                        for field, value in notice_facts_columns(facts).items()),
                "KIND notice facts or identity differ from the official body")
        official.append(Notice(security, accession, form, row["Published"], filing.company_id, filing.title,
                               facts, refs, document, family, final))
    return official
