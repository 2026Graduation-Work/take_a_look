"""Collect and verify the public KIND market-wide disclosure inventory."""

import hashlib
import json
import re
import time
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from urllib.parse import urlencode, urlsplit

import requests

from shared.io import atomic_json, canonical_hash, sha256

from .disclosures import (
    BODY_LIMIT,
    KIND_MAIN,
    KIND_SEARCH,
    KIND_VIEWER,
    PAGE_SIZE,
    DisclosureError,
    DocumentFormatError,
    Evidence,
    Filing,
    PageConsistencyError,
    Response,
    TableRows,
    collect_pages,
    kind_page,
    one,
    put_immutable,
    require,
)

DAILY_URL = "https://kind.krx.co.kr/disclosure/todaydisclosure.do"
DAILY_MAIN = DAILY_URL + "?method=searchTodayDisclosureMain"
DAILY_SIZE = 3000
COMPANY_URL = "https://kind.krx.co.kr/disclosure/details.do"
COMPANY_MAIN = COMPANY_URL + "?method=searchDetailsMain"
COMPANY_SIZE = 100
EXCHANGE = frozenset({"유가증권시장본부", "코스닥시장본부", "코넥스시장", "코넥스시장본부", "한국거래소"})


class KindUnavailable(DisclosureError):
    """The KIND request is incomplete and can be resumed."""


class CorrectionError(DisclosureError):
    failed_check = "correction_final_unresolved"

    def __init__(self, message, evidence=()):
        super().__init__(message)
        self.evidence = evidence


@dataclass(frozen=True)
class MarketFiling(Filing):
    displayed: date | None = None
    company_id: str = ""
    submitter: str = ""
    withdrawn: bool = False


@dataclass(frozen=True)
class KindBody(Response):
    document_no: str
    family: tuple[str, ...]
    final: bool


@dataclass(frozen=True)
class DocumentRoute:
    accession: str
    document_no: str
    url: str
    form: str


@dataclass(frozen=True)
class FinalReferral:
    route: DocumentRoute
    family: tuple[tuple[str, str], ...]
    evidence: Evidence


class DailyRows(TableRows):
    def __init__(self):
        super().__init__()
        self.company_id = ""
        self.caption = ""
        self.filings = []

    def handle_starttag(self, tag, attrs):
        super().handle_starttag(tag, attrs)
        if tag == "tr":
            self.company_id = self.caption = ""
        if tag == "a":
            attributes = dict(attrs)
            onclick = attributes.get("onclick", "")
            if match := re.search(r"companysummary_open\('([0-9A-Z]{5,6})'\)", onclick):
                self.company_id = match[1]
            if self.accession and "openDisclsViewer(" in onclick:
                self.caption = attributes.get("title", "")

    def handle_endtag(self, tag):
        if tag == "tr" and self.accession:
            self.filings.append((self.accession, self.cells, self.company_id, self.caption))
        super().handle_endtag(tag)


def kind_withdrawal(title):
    title = re.sub(r"\s+", "", title)
    return bool(re.match(r"^(?:\[[^\[\]]+\])*\[(?:철회|취소)\]", title)
                or re.search(r"\((?:철회|취소)\)\Z", title))


def daily_form(day, page):
    return {"method": "searchTodayDisclosureSub", "forward": "todaydisclosure_sub",
            "currentPageSize": str(DAILY_SIZE), "pageIndex": str(page), "orderMode": "", "orderStat": "D",
            "marketType": "", "searchMode": "", "chose": "", "selDate": day.isoformat(), "todayFlag": "N"}


def _list_page(response, page):
    html = response.text()
    total, current, last = one(
        r"전체\s*<em>([\d,]+)</em>건\s*:\s*<strong>(\d+)</strong>/(\d+)",
        html, "KIND total/page footer missing",
    )
    require(int(current) == page, "Unexpected KIND list page")
    table = DailyRows()
    table.feed(html)
    require(len(re.findall(r"openDisclsViewer\('[0-9]{14}'", html)) == len(table.filings),
            "KIND daily filings fall outside the list rows")
    total = int(total.replace(",", ""))
    require(total != 0 or "조회된 결과값이 없습니다." in html, "KIND empty result marker missing")
    return total, int(last), table.filings


def daily_page(response, day, page):
    total, last, filings = _list_page(response, page)
    rows = []
    for accession, cells, company_id, caption in filings:
        require(len(cells) == 5 and re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", cells[0]),
                "Invalid KIND daily filing row")
        _, company, title, submitter, _ = cells
        rows.append(MarketFiling(accession, day, caption or title, response.evidence,
                                 company=company, displayed=day, company_id=company_id, submitter=submitter,
                                 withdrawn=kind_withdrawal(title) or kind_withdrawal(caption)))
    return total, last, rows, response.evidence


def company_page(response, code, start, end, page):
    total, last, filings = _list_page(response, page)
    rows = []
    for accession, cells, company_id, caption in filings:
        require(len(cells) == 6 and re.fullmatch(r"\d{4}-\d\d-\d\d \d\d:\d\d", cells[1]),
                "Invalid KIND company filing row")
        displayed = date.fromisoformat(cells[1][:10])
        require(start <= displayed <= end, "KIND company filing is outside search")
        require(not company_id or code.startswith(company_id),
                "KIND company result lacks a verified issuer-code binding")
        _, _, company, title, submitter, _ = cells
        rows.append(MarketFiling(accession, displayed, caption or title, response.evidence, stock_code=code,
                                 company=company, displayed=displayed, company_id=company_id, submitter=submitter,
                                 withdrawn=kind_withdrawal(title) or kind_withdrawal(caption)))
    return total, last, rows, response.evidence


def document_route(lookup):
    source = one(r"parent\.setPath\(\s*'[^']*'\s*,\s*'([^']+)'", lookup.text(), "KIND document path missing")
    parsed = urlsplit(source)
    match = re.fullmatch(r"/external/(\d{4})/(\d{2})/(\d{2})/(\d{6})/(\d{14})/(\d+)\.htm", parsed.path)
    require(parsed.scheme == "https" and parsed.netloc == "kind.krx.co.kr" and not parsed.query
            and not parsed.fragment and match, "KIND document route does not identify the selected accession")
    return DocumentRoute("".join(match.groups()[:4]), match[5], source, match[6])


def kind_route(accession, lookup):
    route = document_route(lookup)
    require(route.accession == accession, "KIND document route does not identify the selected accession")
    return route.url, route.form


def viewer_documents(accession, shell):
    text = shell.text()
    require(set(re.findall(r'name="acptNo"\s+id="acptNo"\s+value="([0-9]{14})"', text)) == {accession},
            "KIND viewer does not identify the requested accession")
    options = one(r'<select\b[^>]*\bid=[\'"]mainDoc[\'"][^>]*>(.*?)</select>', text, "KIND viewer main document missing")
    selections = re.findall(r"value=['\"]([0-9]{14})\|([YN])['\"]\s*selected", options)
    if len(selections) != 1:
        raise CorrectionError("KIND selected document is ambiguous", (shell.evidence,))
    selected, = selections
    family = tuple(re.findall(r"value=['\"]([0-9]{14})\|([YN])['\"]", options))
    if len(family) != len({number for number, _ in family}):
        raise CorrectionError("KIND document family is ambiguous", (shell.evidence,))
    if selected[1] == "Y" and [number for number, flag in family if flag == "Y"] != [selected[0]]:
        raise CorrectionError("KIND viewer does not identify one selected final document", (shell.evidence,))
    return selected, family


def final_document_number(selected, family):
    require(selected[1] == "N", "KIND final referral requires a non-final selection")
    finals = [number for number, flag in family if flag == "Y"]
    if len(finals) != 1:
        raise CorrectionError("KIND correction family does not identify one final document")
    return finals[0]


class KindMarket:
    def __init__(self, root, *, budget=0, daily_cache=None, company_cache=None, legacy_docs=(), archives=(), session=None):
        require(budget >= 0, "KIND request budget must be nonnegative")
        self.root = Path(root)
        self.daily_cache = Path(daily_cache) if daily_cache else None
        self.company_cache = Path(company_cache) if company_cache else None
        self.legacy_docs = tuple(map(Path, legacy_docs))
        self.archives = tuple((Path(archive), Path(run)) for archive, run in archives)
        self.legacy_times = {}
        for folder in (*self.legacy_docs, *((self.company_cache,) if self.company_cache else ())):
            log = folder.parent.parent / "calls.log"
            if log.exists():
                for line in log.read_text().splitlines():
                    at, status, size, file = line.split()
                    if status == "200":
                        self.legacy_times[folder / file] = (at, int(size))
        self.session = requests.Session() if session is None else session
        self.remaining = budget
        self.calls = 0
        self._last_request_started = -float("inf")
        self._stopped = False
        self._transport_failures = 0

    def _store(self, request, body, charset, received_at, origin):
        digest = hashlib.sha256(body).hexdigest()
        record = {"request": request, "sha256": digest, "bytes": len(body),
                  "charset": charset, "received_at": received_at, "origin": origin}
        serialized = (json.dumps(record, sort_keys=True) + "\n").encode()
        receipt = hashlib.sha256(serialized).hexdigest()
        put_immutable(self.root / "objects" / digest, body)
        put_immutable(self.root / "receipts" / f"{receipt}.json", serialized)
        return Response(body, charset, Evidence(digest, receipt))

    def _cached(self, path, request, archive, *, copy=False):
        evidence = Evidence(**json.loads(path.read_text()))
        return self._verified_response(evidence, request, archive, copy=copy)

    def _verified_response(self, evidence, request, archive, *, copy=False):
        require(all(re.fullmatch(r"[0-9a-f]{64}", digest) for digest in vars(evidence).values()),
                "Invalid KIND evidence identifier")
        receipt = archive / "receipts" / f"{evidence.receipt}.json"
        blob = archive / "objects" / evidence.sha256
        require(sha256(receipt) == evidence.receipt and sha256(blob) == evidence.sha256,
                "Archived KIND response or receipt changed")
        metadata = json.loads(receipt.read_text())
        require(metadata["request"] in self._request_variants(request) and metadata["sha256"] == evidence.sha256,
                "Archived KIND request does not match")
        body = blob.read_bytes()
        require(metadata["bytes"] == len(body) <= BODY_LIMIT, "Archived KIND size differs")
        if copy:
            put_immutable(self.root / "objects" / evidence.sha256, body)
            put_immutable(self.root / "receipts" / receipt.name, receipt.read_bytes())
        return Response(body, metadata["charset"], evidence)

    @staticmethod
    def _request_variants(request):
        yield request
        yield {**request, "query": {}}
        if request["url"].startswith(KIND_VIEWER + "?method=search&") and request["referer"] == DAILY_MAIN:
            yield {**request, "query": {}, "referer": KIND_MAIN}

    def _prior_response(self, request):
        for archive, run in self.archives:
            for variant in self._request_variants(request):
                pointer = run / "requests" / f"{canonical_hash(variant)}.json"
                if pointer.exists():
                    return self._cached(pointer, request, archive, copy=True)
        return None

    def _import_daily(self, path, request):
        receipt = path.with_suffix(".json")
        if not receipt.exists():
            return None
        info = json.loads(receipt.read_text())
        body = path.read_bytes()
        received = datetime.fromisoformat(info["received_at"])
        require(info["url"] == request["url"] and info["form"] == request["form"] and received.tzinfo
                and info["bytes"] == len(body) <= BODY_LIMIT and info["sha256"] == hashlib.sha256(body).hexdigest(),
                "Imported KIND daily receipt does not match request or bytes")
        return self._store(request, body, info["charset"], info["received_at"], "daily_cache")

    def _import_document(self, path, request):
        body = path.read_bytes()
        require(0 < len(body) <= BODY_LIMIT, "Invalid KIND legacy document size")
        recorded = self.legacy_times.get(path)
        require(not recorded or recorded[1] == len(body), "KIND legacy response length changed")
        for charset in ("utf-8", "cp949"):
            try:
                body.decode(charset)
                break
            except UnicodeError:
                continue
        else:
            raise DisclosureError("Invalid KIND legacy response encoding")
        return self._store(request, body, charset, recorded[0] if recorded else None, "legacy_cache")

    def _request(self, request):
        if self._stopped or self.remaining == 0:
            raise KindUnavailable("KIND requests stopped or budget exhausted; resume collection")
        wait = 0.6 - (time.monotonic() - self._last_request_started)
        if wait > 0:
            time.sleep(wait)
        self.remaining -= 1
        self.calls += 1
        url, form, referer = (request[key] for key in ("url", "form", "referer"))
        headers = {"User-Agent": "Mozilla/5.0", "Referer": referer}
        if form is not None:
            headers["X-Requested-With"] = "XMLHttpRequest"
        call = {**request, "status": None}
        try:
            self._last_request_started = time.monotonic()
            with self.session.request("POST" if form else "GET", url, data=form, headers=headers,
                                      timeout=(10, 40), stream=True, allow_redirects=False) as response:
                status = response.status_code
                call["status"] = status
                if status in {403, 429}:
                    self._stopped = True
                if status != 200:
                    raise KindUnavailable(f"KIND HTTP status {status}")
                charset = requests.utils.get_encoding_from_headers(response.headers)
                if not charset or charset.lower() == "iso-8859-1":
                    charset = "utf-8"
                body = bytearray()
                for block in response.iter_content(64 * 1024):
                    body.extend(block)
                    require(len(body) <= BODY_LIMIT, "KIND response exceeds body limit")
        except requests.RequestException as exc:
            self._transport_failures += 1
            if self._transport_failures >= 3:
                self._stopped = True
            call["error_type"] = type(exc).__name__
            raise KindUnavailable("KIND network request failed") from None
        else:
            self._transport_failures = 0
        finally:
            self.root.mkdir(parents=True, exist_ok=True)
            at = datetime.now(UTC).isoformat()
            with (self.root / "calls.jsonl").open("a") as log:
                log.write(json.dumps({**call, "received_at": at}) + "\n")
        return self._store(request, bytes(body), charset, at, "http")

    def _get(self, url, *, referer, form=None, daily=None, legacy=None, parse=lambda response: response, page_caches=None,
             cache_only=False):
        request = {"url": url, "form": form, "referer": referer}
        pointer = self.root / "requests" / f"{canonical_hash(request)}.json"
        if page_caches is not None:
            page_caches.append(pointer)
        response = None
        if pointer.exists():
            cached = self._cached(pointer, request, self.root)
            try:
                return parse(cached)
            except DisclosureError:
                if cache_only:
                    raise
                pointer.unlink()
                response = self._request(request)
        if response is None:
            response = self._prior_response(request)
        if response is None and daily:
            response = self._import_daily(daily, request)
        if response is None and legacy and legacy.is_file():
            response = self._import_document(legacy, request)
        if response is None:
            if cache_only:
                raise KindUnavailable("KIND supplemental response is unavailable in cache")
            response = self._request(request)
        result = parse(response)
        atomic_json(pointer, vars(response.evidence))
        return result

    def day(self, day):
        page_caches = []

        def page_at(page):
            cached = self.daily_cache / f"{day}_p{page}.html" if self.daily_cache else None
            return self._get(DAILY_URL, form=daily_form(day, page), referer=DAILY_MAIN, daily=cached,
                             parse=lambda response: daily_page(response, day, page), page_caches=page_caches)

        try:
            return collect_pages("KIND daily disclosure list", day, day, DAILY_SIZE, page_at)
        except PageConsistencyError:
            for path in page_caches:
                path.unlink(missing_ok=True)
            raise

    def company(self, code, start, end, *, cache_only=False):
        require(re.fullmatch(r"[0-9A-Z]{6}", code) and 0 <= (end - start).days <= 729,
                "Invalid or unbounded KIND issuer search")
        page_caches = []

        def page_at(page):
            form = {"method": "searchDetailsSub", "currentPageSize": str(COMPANY_SIZE), "pageIndex": str(page),
                    "orderMode": "1", "orderStat": "D", "forward": "details_sub", "searchCodeType": "number",
                    "searchCorpName": code, "repIsuSrtCd": "A" + code, "fromDate": start.isoformat(),
                    "toDate": end.isoformat(), "reportNm": "", "reportNmTemp": ""}
            cached = self.company_cache / f"{code}_{start}_{end}_p{page}.html" if self.company_cache else None
            return self._get(COMPANY_URL, form=form, referer=COMPANY_MAIN, legacy=cached, cache_only=cache_only,
                             parse=lambda response: company_page(response, code, start, end, page),
                             page_caches=page_caches)

        try:
            return collect_pages("KIND company disclosure list", start, end, COMPANY_SIZE, page_at)
        except PageConsistencyError:
            for path in page_caches:
                path.unlink(missing_ok=True)
            raise

    def cached_company(self, code, start, end):
        return self.company(code, start, end, cache_only=True)

    def archived_market_lists(self, from_day, to_day, codes):
        queries = set()
        for archive, run in self.archives:
            for pointer in sorted((run / "requests").glob("*.json")):
                reference = Evidence(**json.loads(pointer.read_text()))
                require(re.fullmatch(r"[0-9a-f]{64}", reference.receipt), "Invalid KIND evidence identifier")
                receipt = archive / "receipts" / f"{reference.receipt}.json"
                require(sha256(receipt) == reference.receipt, "Archived KIND receipt changed")
                request = json.loads(receipt.read_text())["request"]
                form = request["form"]
                if request["url"] != KIND_SEARCH or not form or form["pageIndex"] != "1":
                    continue
                code = form["searchCorpName"]
                start, end = date.fromisoformat(form["fromData"]), date.fromisoformat(form["toData"])
                if start <= to_day and from_day <= end and (not codes or code in codes):
                    queries.add((code, start, end))
        for code, start, end in sorted(queries):
            rows, span = self.market_actions(code, start, end, cache_only=True)
            yield code, rows, span

    def market_actions(self, code, start, end, *, cache_only=False):
        require(re.fullmatch(r"[0-9A-Z]{6}", code) and 0 <= (end - start).days <= 729,
                "Invalid or unbounded KIND market-action search")
        page_caches = []

        def page_at(page):
            form = {"method": "searchDetailsMktactSubExt", "forward": "details_mktact_sub_ext",
                    "searchCodeType": "number", "repIsuSrtCd": f"A{code}", "searchCorpName": code,
                    "searchCorpNameTmp": code, "fromData": start.isoformat(), "toData": end.isoformat(),
                    "currentPageSize": str(PAGE_SIZE), "pageIndex": str(page)}
            return self._get(KIND_SEARCH, form=form, referer=KIND_MAIN, cache_only=cache_only,
                             parse=lambda response: kind_page(response, start, end, page), page_caches=page_caches)

        try:
            rows, span = collect_pages("Archived KIND market actions", start, end, PAGE_SIZE, page_at)
        except PageConsistencyError:
            for path in page_caches:
                path.unlink(missing_ok=True)
            raise
        return [MarketFiling(**{**vars(row), "stock_code": code}, displayed=row.published,
                             submitter="한국거래소") for row in rows], span

    def dated_filing(self, span, accession):
        day = span.start
        require(span.source == "KIND daily disclosure list" and day == span.end,
                "KIND correction requires a complete daily list")

        def page_at(page):
            require(page <= len(span.pages), "KIND correction daily list lacks a page")
            request = {"url": DAILY_URL, "form": daily_form(day, page), "referer": DAILY_MAIN}
            return daily_page(self._verified_response(span.pages[page - 1], request, self.root), day, page)

        rows, audited = collect_pages(span.source, day, day, DAILY_SIZE, page_at)
        matches = [row for row in rows if row.accession == accession]
        require(audited == span and len(matches) <= 1, "KIND correction is duplicated in the verified daily list")
        return matches[0] if matches else None

    def final_referral(self, filing, body, refs, *, cache_only=False):
        viewer = KIND_VIEWER + "?" + urlencode({"method": "search", "acptno": filing.accession})
        shell = self._verified_response(refs[0], {"url": viewer, "form": None, "referer": DAILY_MAIN}, self.root)
        selected, family = viewer_documents(filing.accession, shell)
        require(selected == (body.document_no, "N") and not body.final, "KIND correction source selection differs")
        final_no = final_document_number(selected, family)
        lookup = KIND_VIEWER + "?" + urlencode({"method": "searchContents", "docNo": final_no})
        def parse(response):
            route = document_route(response)
            require(route.document_no == final_no and route.accession != filing.accession, "KIND correction route differs")
            return FinalReferral(route, family, response.evidence)

        return self._get(lookup, referer=viewer, cache_only=cache_only, parse=parse)

    def document(self, filing, *, expected=None, cache_only=False):
        accession = filing.accession
        require(re.fullmatch(r"[0-9]{14}", accession), "Invalid KIND accession")
        folder = next((path for path in self.legacy_docs if all((path / f"{accession}_{name}").is_file()
                       for name in ("viewer.html", "contents.html", "doc.htm"))), None)

        def cached(suffix):
            return folder / f"{accession}_{suffix}" if folder else None

        viewer = KIND_VIEWER + "?" + urlencode({"method": "search", "acptno": accession})
        def parse_viewer(response):
            try:
                return response.evidence, viewer_documents(accession, response)
            except CorrectionError:
                raise
            except DisclosureError as exc:
                raise DocumentFormatError(str(exc), (response.evidence,)) from None

        shell, ((doc_no, final), family) = self._get(
            viewer, referer=DAILY_MAIN, legacy=cached("viewer.html"), cache_only=cache_only, parse=parse_viewer)
        if expected and ((doc_no, final) != (expected.route.document_no, "Y") or set(family) != set(expected.family)):
            raise CorrectionError("KIND final viewer selection or correction family differs", (shell,))
        lookup = KIND_VIEWER + "?" + urlencode({"method": "searchContents", "docNo": doc_no})

        def parse_route(response):
            try:
                source, form = kind_route(accession, response)
                require(f"/{doc_no}/" in urlsplit(source).path, "KIND route document identifier changed")
            except DisclosureError as exc:
                raise DocumentFormatError(str(exc), (shell, response.evidence)) from None
            return response.evidence, source, form

        route, source, form = self._get(
            lookup, referer=viewer, legacy=cached("contents.html"), cache_only=cache_only, parse=parse_route)
        if expected and (source, form) != (expected.route.url, expected.route.form):
            raise DocumentFormatError("KIND final route differs from referral", (shell, route))
        body = self._get(source, referer=viewer, legacy=cached("doc.htm"), cache_only=cache_only)
        family_numbers = tuple(number for number, _ in family)
        return form, KindBody(body.body, body.charset, body.evidence, doc_no, family_numbers, final == "Y"), (shell, route, body.evidence)
