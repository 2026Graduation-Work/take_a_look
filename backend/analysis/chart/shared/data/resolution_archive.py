"""Check the request and content of the official responses behind a resolution ledger."""

import csv
import json
from collections import defaultdict
from datetime import date

from .disclosures import (
    KIND_SEARCH,
    KIND_VIEWER,
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
    kind_withdrawal,
    viewer_documents,
)
from .market_notices import (
    Notice,
    SecurityKey,
    auction_identity_links,
    auction_listing_index,
    can_join_auction_identity,
    kind_topic,
    notice_section_key,
    parse_notice,
    superseded_merger_facts,
)
from .market_resolutions import (
    role_correction_windows,
    structural_closure,
    structural_review_evidence,
    superseded_merger_review,
)


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
              "Listing": "listing", "PreviousMarket": "previous_market", "PreviousClose": "previous_close",
              "PaidRecordDate": "paid_record_date", "PaidListing": "paid_listing"}
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
    require(not response.final or not (filing.withdrawn or kind_withdrawal(filing.title)),
            "KIND final disclosure is withdrawn or cancelled")
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
    if witness := row.get("ReviewWitness"):
        original_body_refs = tuple(Evidence(**ref) for ref in witness["OriginalNoticeEvidence"])
        source, _, _ = _official_body(archive, original, row["DocNo"], witness["OriginalFormId"],
                                      (*refs[:2], *original_body_refs))
        evidence = structural_review_evidence(accession, target, refs, original_body_refs)
        review = superseded_merger_review(original, witness["OriginalFormId"], source, matched,
                                          keys, has_session, evidence)
        require(not closed and (_security(witness["Security"]), witness["Date"]) == (review.security, review.date),
                "KIND superseded implementation review identity or date differs from the archived source")
        return closed, review
    if "OriginalNoticeEvidence" in row:
        original_refs = (*refs[:2], *(Evidence(**ref) for ref in row["OriginalNoticeEvidence"]))
        sections, _, source_final = _official_sections(archive, original, row["DocNo"], row["FormId"], original_refs)
        require(not source_final and closed == role_correction_windows(original, row["FormId"],
                list(sections.values()), matched, keys, has_session), "KIND source role closure differs")
        return closed, None
    confirmed, affected = structural_closure(matched, keys, has_session)
    require(closed <= confirmed,
            "KIND correction closure lacks an affected structural fact")
    if kind_topic(original) == "structural":
        require(closed and closed == affected,
                "KIND structural correction leaves an affected window unconfirmed")
    return closed, None


def _verify_auction_identities(coverage, windows, official, documents, filings):
    scopes = {(notice.company_id, notice.facts.effective) for notice in official
              if can_join_auction_identity(notice.form, notice.facts, notice.final)}
    windows_by_code = defaultdict(list)
    for key in windows:
        windows_by_code[key.code].append(key)
    # Use all the original sections of each verified listing body, including any missing from notices.csv.
    listings = []
    for (accession, document, form, refs), (sections, family, final) in documents.items():
        filing = filings[accession, refs[0]]
        if not final or not filing.company_id:
            continue
        for facts in sections.values():
            if ((filing.company_id, facts.effective) not in scopes or facts.kind not in {"listing", "new_listing"}
                    or not facts.code or not facts.isin):
                continue
            keys = [key for key in windows_by_code[facts.code] if key.isin == facts.isin and key.active(facts.effective)
                    and key.code.startswith(filing.company_id)
                    and (facts.share_label in {"보통주", "보통주식"}) == (key.share_class == "common")]
            require(len(keys) <= 1, "KIND auction witness matches ambiguous KRX listing intervals")
            for key in keys:
                listings.append(Notice(key, accession, form, filing.published.isoformat(), filing.company_id,
                                       filing.title, facts, refs, document, family, final))
    links = auction_identity_links(official, auction_listing_index(listings))
    retained = {notice_section_key(notice) for notice in official}
    require(links == coverage.get("kind_auction_identity_links", [])
            and all(tuple(witness) in retained for row in links for witness in row["Witnesses"]),
            "KIND auction identity links are missing or differ from official evidence")


def verify_archive_bindings(folder, coverage, archive, session_dates):
    with (folder / "notices.csv").open(encoding="utf-8", newline="") as stream:
        notices = [(row, tuple(Evidence(**raw) for raw in json.loads(row["Evidence"]))) for row in csv.DictReader(stream)]
    nonstock = [(row, tuple(Evidence(**raw) for raw in row["Evidence"])) for row in coverage.get("nonstock_notices", ())]
    families = [(row, tuple(Evidence(**raw) for raw in row["Evidence"])) for row in coverage.get("kind_final_families", ())]
    outside_failures = [(row, tuple(Evidence(**raw) for raw in row["Evidence"]))
                        for row in coverage["failures"] if row.get("OutsidePriceWindows")]
    needed = {(row["AcptNo"], refs[0]) for row, refs in (*notices, *nonstock)}
    needed.update((row["AcptNo"], refs[0]) for row, refs in families)
    needed.update((row["AcptNo"], refs[0]) for row, refs in outside_failures)
    windows = {_security(row): row for row in coverage["windows"]}

    def has_session(key, day):
        return (key in windows and day in session_dates
                and windows[key]["first_session"] <= day <= windows[key]["last_session"])

    issuers = {key.code[:5] for key in windows}
    ordered = sorted(session_dates)
    prior_sessions = dict(zip(ordered[1:], ordered))
    prior_markets = defaultdict(set)
    for key, window in windows.items():
        if key.delisting and prior_sessions.get(key.delisting) == window["last_session"]:
            prior_markets[key.code, key.delisting].add(key.market)
    role_issuers = {
        "rename": {key.code[:5] for key, window in windows.items() if window["spac"]["observations"]},
        "new_listing": {key.code[:5] for key, window in windows.items() if window["first_session"] == key.listing
                        and prior_markets[key.code, key.listing] - {key.market}},
    }
    expected, proved, daily_targets = {}, set(), {}
    final_accessions = {row["FinalAcptNo"] for row, _ in families}
    for _, refs in outside_failures:
        if len(refs) == 9:
            _, response = _response(archive, refs[4])
            final_accessions.add(document_route(response).accession)
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
            topic, issuer = kind_topic(row), row.company_id[:5]
            if issuer in issuers and (topic == "structural" or issuer in role_issuers.get(topic, ())):
                expected.setdefault(row.accession, row)
    for entry in coverage.get("correction_daily", ()):
        rows = [row for row in _publication(archive, entry) if row.accession in final_accessions]
        add(rows)
        for row in rows:
            daily_targets.setdefault(row.accession, []).append(row)
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
                and all(row.get(field, "") == (str(value) if value is not None else "")
                        for field, value in notice_facts_columns(facts).items()),
                "KIND notice facts or identity differ from the official body")
        official.append(Notice(security, accession, form, row["Published"], filing.company_id, filing.title,
                               facts, refs, document, family, final))
        if final:
            proved.add((filing.accession, filing.evidence))
    _verify_auction_identities(coverage, windows, official, documents, filings)
    final_notices = {}
    for notice in official:
        if notice.final:
            final_notices.setdefault((notice.accession, notice.document_no, notice.form), []).append(notice)
    reviews = defaultdict(list)
    for row, refs in families:
        closed, review = _verify_final_family(archive, row, refs, filings, daily_targets, windows, final_notices, has_session)
        if closed or review:
            proved.add((row["AcptNo"], refs[0]))
        if review:
            reviews[review.security].append(review)
    def windows_after_official_facts(filing, facts):
        issuer = (filing.company_id or filing.stock_code)[:5]
        if not issuer or not facts or issuer in role_issuers["rename"] or issuer in role_issuers["new_listing"]:
            return set()
        affected = {key for key in windows if key.code.startswith(issuer)}
        return affected if all(fact.effective < windows[key]["first_session"] for fact in facts for key in affected) else set()

    for row, refs in outside_failures:
        filing = filings.get((row["AcptNo"], refs[0]))
        require(filing and not filing.withdrawn and not kind_withdrawal(filing.title),
                "Out-of-window structural decision lacks a verified list row")
        _, route_response = _response(archive, refs[2])
        route = document_route(route_response)
        original, _, family = _official_body(archive, filing, route.document_no, route.form, refs[:4])
        facts = ([superseded_merger_facts(filing, route.form, original)]
                 if route.form == "68151" and not original.final else parse_notice(filing, route.form, original))
        if not original.final:
            require(len(refs) == 9, "Out-of-window correction lacks original and final evidence")
            request, referral_response = _response(archive, refs[4])
            referral = document_route(referral_response)
            require(final_document_number((original.document_no, "N"), family) == referral.document_no
                    and row.get("FinalAcptNo", referral.accession) == referral.accession
                    and request["url"] == f"{KIND_VIEWER}?method=searchContents&docNo={referral.document_no}"
                    and request["referer"] == f"{KIND_VIEWER}?method=search&acptno={filing.accession}",
                    "Out-of-window correction final route differs")
            targets = daily_targets.get(referral.accession, [])
            require(len(targets) == 1, "Out-of-window correction final list is ambiguous")
            target, = targets
            require(target.evidence == refs[5] and target.company_id == filing.company_id,
                    "Out-of-window correction lacks the verified final listing")
            final, route, final_family = _official_body(archive, target, referral.document_no, referral.form, refs[5:])
            require(route == referral and set(family) == set(final_family)
                    and final.final and not target.withdrawn and not kind_withdrawal(target.title),
                    "Out-of-window correction is not the verified final document")
            facts += parse_notice(target, referral.form, final)
        else:
            require(len(refs) == 4, "Final out-of-window document has unrelated correction evidence")
        require(windows_after_official_facts(filing, facts) == {_security(item) for item in row["OutsidePriceWindows"]}
                and sorted({fact.effective for fact in facts}) == row["VerifiedEffectiveDates"],
                "Archived event dates or affected price windows differ")
        proved.add((filing.accession, filing.evidence))
    for (accession, _document, _form, refs), (sections, _family, final) in documents.items():
        filing = filings[accession, refs[0]]
        if final and windows_after_official_facts(filing, list(sections.values())):
            proved.add((filing.accession, filing.evidence))
    missing = sorted(f"{row.accession} ({row.published})" for row in expected.values()
                     if (row.accession, row.evidence) not in proved)
    require(not missing, f"Missing official structural notice evidence: {', '.join(missing[:10])}")
    return official, reviews
