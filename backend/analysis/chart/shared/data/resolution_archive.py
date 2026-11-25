"""Check the request and content of the official responses behind a resolution ledger."""

import csv
import json
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
    document_route,
    final_document_number,
    viewer_documents,
)
from .market_notices import Notice, SecurityKey, kind_topic, parse_notice
from .market_resolutions import structural_closure


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


def _official_body(archive, filing, document, form, refs):
    accession = filing.accession
    viewer = f"https://kind.krx.co.kr/common/disclsviewer.do?method=search&acptno={accession}"
    selection = f"https://kind.krx.co.kr/common/disclsviewer.do?method=searchContents&docNo={document}"
    viewer_request, shell = _response(archive, refs[-3])
    route_request, route = _response(archive, refs[-2])
    require(viewer_request["url"] == viewer and route_request["url"] == selection
            and route_request.get("referer") == viewer, "KIND notice viewer differs from official receipt")
    (number, flag), family = viewer_documents(accession, shell)
    target = document_route(route)
    body_request, body = _response(archive, refs[-1])
    require(number == target.document_no == document and target.accession == accession and target.form == form
            and body_request["url"] == target.url and body_request.get("referer") == viewer,
            "KIND notice body receipt differs from its official document or form")
    response = KindBody(body.body, body.charset, body.evidence, document, tuple(number for number, _ in family), flag == "Y")
    return response, target, family


def _official_sections(archive, filing, document, form, refs):
    response, _, _ = _official_body(archive, filing, document, form, refs)
    return {facts.section: facts for facts in parse_notice(filing, form, response)}, response.family, response.final


def _security(row):
    return SecurityKey(row["Code"], row["ISIN"], row["ListingDate"], row["DelistingDate"] or None,
                       row["Market"], row["ShareClass"])


def _verify_final_family(archive, row, refs, filings, daily_targets, windows, final_notices, has_session):
    accession, target = row["AcptNo"], row["FinalAcptNo"]
    original = filings.get((accession, refs[0]))
    matches = daily_targets.get(target, ())
    require(original and len(matches) == 1 and matches[0].evidence == refs[3],
            "KIND correction family is absent from its pinned publication lists")
    final, = matches
    issuer = (original.company_id or original.stock_code)[:5]
    require(issuer and issuer == (final.company_id or final.stock_code)[:5], "KIND correction family issuer differs")
    viewer = f"https://kind.krx.co.kr/common/disclsviewer.do?method=search&acptno={accession}"
    viewer_request, shell = _response(archive, refs[1])
    selected, family = viewer_documents(accession, shell)
    require(viewer_request["url"] == viewer and selected == (row["DocNo"], "N"), "KIND correction source viewer differs")
    number = final_document_number(selected, family)
    route_request, response = _response(archive, refs[2])
    lookup = f"https://kind.krx.co.kr/common/disclsviewer.do?method=searchContents&docNo={number}"
    require(route_request["url"] == lookup and route_request.get("referer") == viewer,
            "KIND correction discovery receipt differs")
    discovered = document_route(response)
    final_body, final_route, final_family = _official_body(archive, final, row["FinalDocNo"], row["FormId"], refs[3:])
    require(discovered == final_route and discovered.document_no == number and final_body.final and set(family) == set(final_family),
            "KIND correction destination route or family differs")
    matched = [notice for notice in final_notices.get((target, number, row["FormId"]), ())
               if notice.evidence[1:] == refs[4:]]
    require(matched, "KIND correction target has no verified stock facts")
    closed = {_security(item) for item in row["ClosedWindows"]}
    keys = {key for key in windows if key.code.startswith(issuer)}
    confirmed, affected = structural_closure(matched, keys, has_session)
    require(closed <= confirmed,
            "KIND correction closure lacks an affected structural fact")
    if kind_topic(original) == "structural":
        require(closed and closed == affected,
                "KIND structural correction leaves an affected window unconfirmed")
    return closed


def verify_archive_bindings(folder, coverage, archive, session_dates):
    with (folder / "notices.csv").open(encoding="utf-8", newline="") as stream:
        notices = [(row, tuple(Evidence(**raw) for raw in json.loads(row["Evidence"]))) for row in csv.DictReader(stream)]
    nonstock = [(row, tuple(Evidence(**raw) for raw in row["Evidence"])) for row in coverage.get("nonstock_notices", ())]
    families = [(row, tuple(Evidence(**raw) for raw in row["Evidence"])) for row in coverage.get("kind_final_families", ())]
    needed = {(row["AcptNo"], refs[0]) for row, refs in (*notices, *nonstock)}
    needed.update((row["AcptNo"], refs[0]) for row, refs in families)
    windows = {_security(row): row for row in coverage["windows"]}

    def has_session(key, day):
        return (key in windows and day in session_dates
                and windows[key]["first_session"] <= day <= windows[key]["last_session"])

    issuers = {key.code[:5] for key in windows}
    expected, proved, daily_targets = {}, set(), {}
    final_accessions = {row["FinalAcptNo"] for row, _ in families}
    filings = {}

    def add(rows):
        for row in rows:
            key = row.accession, row.evidence
            if key in needed:
                filings[key] = row

    for entry in coverage["daily"]:
        rows = _publication(archive, entry)
        add(rows)
        for row in rows:
            if row.accession in final_accessions:
                daily_targets.setdefault(row.accession, []).append(row)
            if row.company_id[:5] in issuers and kind_topic(row) == "structural":
                expected.setdefault(row.accession, row)
    for table in ("company", "archived_market_actions"):
        for code, entries in coverage[table].items():
            for entry in entries:
                add(_publication(archive, entry, code))
    for row, refs in nonstock:
        filing = filings.get((row["AcptNo"], refs[0]))
        require(filing is not None, "KIND non-stock notice is not in its pinned publication list")
        sections, _, final = _official_sections(archive, filing, row["DocNo"], row["FormId"], refs)
        require(not sections and final, "KIND non-stock notice does not verify as an exclusive warrant change")
        proved.add((filing.accession, filing.evidence))
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
        security = _security(row)
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
        if final:
            proved.add((filing.accession, filing.evidence))
    final_notices = {}
    for notice in official:
        if notice.final:
            final_notices.setdefault((notice.accession, notice.document_no, notice.form), []).append(notice)
    for row, refs in families:
        if _verify_final_family(archive, row, refs, filings, daily_targets, windows, final_notices, has_session):
            proved.add((row["AcptNo"], refs[0]))
    missing = sorted(f"{row.accession} ({row.published})" for row in expected.values()
                     if (row.accession, row.evidence) not in proved)
    require(not missing, f"Missing official structural notice evidence: {', '.join(missing[:10])}")
    return official
