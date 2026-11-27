"""Bounded official disclosure queries and content-addressed response storage."""

import hashlib
import io
import json
import re
import tempfile
import zipfile
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from html import unescape
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlencode, urlsplit
from xml.etree import ElementTree

import requests

from shared.io import atomic_json, canonical_hash, sha256

DART_API = "https://opendart.fss.or.kr/api/"
DART_MAIN = "https://dart.fss.or.kr/dsaf001/main.do"
KIND_SEARCH = "https://kind.krx.co.kr/disclosure/detailsExt.do"
KIND_MAIN = KIND_SEARCH + "?ext=y&method=searchDetailsMktactMainExt"
KIND_VIEWER = "https://kind.krx.co.kr/common/disclsviewer.do"
PAGE_SIZE = 15
BODY_LIMIT = 20 * 1024 * 1024


class DisclosureError(ValueError):
    """An official query or supported document could not be verified."""


class PageConsistencyError(DisclosureError):
    """Individually valid pages cannot describe a single result set."""


class DocumentFormatError(DisclosureError):
    """A retrieved official document has no supported route or structure."""

    def __init__(self, reason, evidence):
        super().__init__(reason)
        self.evidence = evidence


def require(condition, reason):
    if not condition:
        raise DisclosureError(reason)


def one(pattern, body, reason):
    matches = re.findall(pattern, body, re.DOTALL)
    require(len(matches) == 1, reason)
    return matches[0]


def chunks(start, end):
    """Query at most two years per request window, inside both providers' limits."""
    while start <= end:
        stop = min(start + timedelta(days=729), end)
        yield start, stop
        start = stop + timedelta(days=1)


def put_immutable(path, body):
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        with tempfile.TemporaryDirectory(dir=path.parent) as stage:
            staged = Path(stage) / path.name
            staged.write_bytes(body)
            try:
                path.hardlink_to(staged)
            except FileExistsError:
                pass
    require(sha256(path) == hashlib.sha256(body).hexdigest(), "Archived bytes differ")


@dataclass(frozen=True)
class Evidence:
    sha256: str
    receipt: str


@dataclass(frozen=True)
class Response:
    body: bytes
    charset: str
    evidence: Evidence

    def text(self):
        try:
            return self.body.decode(self.charset)
        except (LookupError, UnicodeError):
            raise DisclosureError("Official response encoding is invalid") from None


@dataclass(frozen=True)
class Filing:
    accession: str
    published: date
    title: str
    evidence: Evidence
    stock_code: str = ""
    company: str = ""
    note: str = ""


@dataclass(frozen=True)
class Coverage:
    source: str
    start: date
    end: date
    rows: int
    pages: tuple[Evidence, ...]


class OfficialDisclosures:
    def __init__(self, archive, run, key, request_budget, *, session=None):
        require(bool(key), "OPEN_DART_API is required")
        require(request_budget > 0, "A positive request budget is required")
        self.archive = Path(archive)
        self.run = Path(run)
        self._key = key
        self.remaining = request_budget
        self.session = requests.Session() if session is None else session

    def _fetch(self, url, *, params=None, form=None, referer=None, parse=lambda r: r, page_caches=None):
        query = params or {}
        request = {"url": url, "query": query, "form": form, "referer": referer}
        cache = self.run / "requests" / (canonical_hash(request) + ".json")
        if page_caches is not None:
            page_caches.append(cache)
        if cache.exists():
            evidence = Evidence(**json.loads(cache.read_text()))
            receipt = self.archive / "receipts" / f"{evidence.receipt}.json"
            require(sha256(receipt) == evidence.receipt, "Archived receipt changed")
            metadata = json.loads(receipt.read_text())
            require(metadata["request"] == request and metadata["sha256"] == evidence.sha256,
                    "Archived request does not match")
            blob = self.archive / "objects" / evidence.sha256
            require(sha256(blob) == evidence.sha256, "Archived response changed")
            return parse(Response(blob.read_bytes(), metadata["charset"], evidence))

        require(self.remaining > 0, "Official request budget exhausted; resume this run")
        self.remaining -= 1
        headers = {"User-Agent": "Mozilla/5.0"}
        if referer:
            headers["Referer"] = referer
        if form is not None:
            headers["X-Requested-With"] = "XMLHttpRequest"
        wire_params = {**query, "crtfc_key": self._key} if url.startswith(DART_API) else query
        try:
            with self.session.request(
                "POST" if form is not None else "GET", url, params=wire_params, data=form,
                headers=headers, timeout=(10, 30), stream=True, allow_redirects=False,
            ) as response:
                require(response.status_code == 200, f"Official HTTP status {response.status_code}")
                charset = requests.utils.get_encoding_from_headers(response.headers)
                if not charset or charset.lower() == "iso-8859-1":
                    charset = "utf-8"
                body = bytearray()
                for block in response.iter_content(64 * 1024):
                    body.extend(block)
                    require(len(body) <= BODY_LIMIT, "Official response exceeds body limit")
        except requests.RequestException:
            raise DisclosureError("Official HTTP request failed") from None
        require(self._key.encode() not in body and self._key not in charset,
                "Official response reflected credential")
        digest = hashlib.sha256(body).hexdigest()
        metadata = {"request": request, "sha256": digest, "bytes": len(body),
                    "charset": charset, "received_at": datetime.now(UTC).isoformat()}
        serialized = (json.dumps(metadata, sort_keys=True) + "\n").encode()
        receipt = hashlib.sha256(serialized).hexdigest()
        put_immutable(self.archive / "objects" / digest, bytes(body))
        put_immutable(self.archive / "receipts" / f"{receipt}.json", serialized)
        evidence = Evidence(digest, receipt)
        result = parse(Response(bytes(body), charset, evidence))
        atomic_json(cache, vars(evidence))
        return result

    def corporations(self):
        def parse(response):
            if not zipfile.is_zipfile(io.BytesIO(response.body)):
                try:
                    status = ElementTree.fromstring(response.body).findtext("status")
                except ElementTree.ParseError:
                    raise DisclosureError("Invalid OpenDART corporation archive") from None
                raise DisclosureError(f"OpenDART corporation index unavailable ({api_status(status)})")
            try:
                root = ElementTree.fromstring(zip_document(response.body))
            except (ElementTree.ParseError, zipfile.BadZipFile, OSError):
                raise DisclosureError("Invalid OpenDART corporation archive") from None
            result = {}
            for item in root.findall("list"):
                code, corporation = item.findtext("stock_code", "").strip(), item.findtext("corp_code", "")
                if re.fullmatch(r"[0-9A-Z]{6}", code) and re.fullmatch(r"[0-9]{8}", corporation):
                    result.setdefault(code, set()).add(corporation)
            require(result, "DART corporation index is empty")
            return result, response.evidence

        return self._fetch(DART_API + "corpCode.xml", parse=parse)

    def dart_list(self, corporation, start, end):
        def get(page, page_caches):
            query = {"corp_code": corporation, "bgn_de": start.strftime("%Y%m%d"),
                     "end_de": end.strftime("%Y%m%d"), "last_reprt_at": "N",
                     "page_count": 100, "page_no": page}

            def parse(response):
                data = dart_json(response)
                if data["status"] == "013":
                    require(page == 1 and not data.get("list"), "Unexpected empty DART page")
                    return 0, 1, [], response.evidence
                require(int(data["page_no"]) == page and int(data["page_count"]) == 100,
                        "Unexpected DART page number or size")
                rows = []
                for row in data["list"]:
                    published = datetime.strptime(row["rcept_dt"], "%Y%m%d").date()
                    require(row["corp_code"] == corporation and start <= published <= end,
                            "DART filing outside query")
                    accession = row["rcept_no"]
                    require(re.fullmatch(r"[0-9]{14}", accession),
                            "Invalid DART filing identifier")
                    rows.append(Filing(accession, published, row["report_nm"], response.evidence,
                                       row.get("stock_code", "").strip(), row["corp_name"], row.get("rm", "")))
                return int(data["total_count"]), int(data["total_page"]), rows, response.evidence

            return self._fetch(DART_API + "list.json", params=query, parse=parse, page_caches=page_caches)

        return self._paged("OpenDART list", start, end, 100, get)

    def dart_details(self, endpoint, corporation, start, end):
        require(endpoint in {"fricDecsn.json", "crDecsn.json"}, "Unsupported DART detail query")
        query = {"corp_code": corporation, "bgn_de": start.strftime("%Y%m%d"),
                 "end_de": end.strftime("%Y%m%d")}

        def parse(response):
            data = dart_json(response)
            rows = data.get("list", []) if data["status"] == "000" else []
            seen = set()
            for row in rows:
                accession = row["rcept_no"]
                require(row["corp_code"] == corporation and re.fullmatch(r"[0-9]{14}", accession)
                        and accession not in seen, "Invalid DART detail row")
                seen.add(accession)
            return rows, Coverage(endpoint, start, end, len(rows), (response.evidence,))

        return self._fetch(DART_API + endpoint, params=query, parse=parse)

    def dart_document(self, accession, *, structured=False):
        require(re.fullmatch(r"[0-9]{14}", accession), "Invalid DART receipt")
        main = DART_MAIN + "?" + urlencode({"rcpNo": accession})
        shell = self._fetch(main)
        try:
            family = dart_family(accession, shell.text())
        except DisclosureError as exc:
            raise DocumentFormatError(str(exc), (shell.evidence,)) from None

        def document(response):
            if zipfile.is_zipfile(io.BytesIO(response.body)):
                return response
            status = ElementTree.fromstring(response.body).findtext("status")
            require(status == "014", f"DART original unavailable ({api_status(status)})")
            return response

        original = self._fetch(DART_API + "document.xml", params={"rcept_no": accession}, parse=document)

        if structured and zipfile.is_zipfile(io.BytesIO(original.body)):
            return original, family, (shell.evidence, original.evidence)
        try:
            body_url, _ = dart_route(accession, shell.text())
        except DisclosureError as exc:
            raise DocumentFormatError(str(exc), (shell.evidence, original.evidence)) from None

        body = self._fetch(body_url, referer=main)
        if not re.search(r"<table\b", body.text(), re.I):
            raise DocumentFormatError("DART viewer document has no disclosure table",
                                      (shell.evidence, original.evidence, body.evidence))
        return body, family, (shell.evidence, original.evidence, body.evidence)

    def kind_list(self, code, start, end):
        require(re.fullmatch(r"[0-9A-Z]{6}", code), "Invalid KRX short code")

        def get(page, page_caches):
            form = {"method": "searchDetailsMktactSubExt", "forward": "details_mktact_sub_ext",
                    "searchCodeType": "number", "repIsuSrtCd": f"A{code}",
                    "searchCorpName": code, "searchCorpNameTmp": code,
                    "fromData": start.isoformat(), "toData": end.isoformat(),
                    "currentPageSize": str(PAGE_SIZE), "pageIndex": str(page)}
            return self._fetch(KIND_SEARCH, form=form, referer=KIND_MAIN,
                               parse=lambda response: kind_page(response, start, end, page),
                               page_caches=page_caches)

        return self._paged("KIND market actions", start, end, PAGE_SIZE, get)

    def _paged(self, source, start, end, size, get):
        page_caches = []
        try:
            return collect_pages(source, start, end, size, lambda page: get(page, page_caches))
        except PageConsistencyError:
            for cache in page_caches:
                cache.unlink(missing_ok=True)
            raise

    def kind_document(self, filing):
        accession = filing.accession
        viewer = KIND_VIEWER + "?" + urlencode({"method": "search", "acptno": accession})

        def selected(response):
            options = one(r'<select\b[^>]*\bid=[\'"]mainDoc[\'"][^>]*>(.*?)</select>',
                          response.text(), "KIND viewer main document missing")
            return response, one(r"value=['\"]([0-9]{14})\|[YN]['\"]\s*selected", options,
                                 "KIND selected document is ambiguous")

        shell = self._fetch(viewer, referer=KIND_MAIN)
        try:
            _, doc_no = selected(shell)
        except DisclosureError as exc:
            raise DocumentFormatError(str(exc), (shell.evidence,)) from None
        lookup = KIND_VIEWER + "?" + urlencode({"method": "searchContents", "docNo": doc_no})

        def routed(response):
            source = one(r"parent\.setPath\(\s*'[^']*'\s*,\s*'([^']+)'",
                         response.text(), "KIND document path missing")
            parsed = urlsplit(source)
            require(parsed.scheme == "https" and parsed.netloc == "kind.krx.co.kr"
                    and parsed.path.startswith("/external/") and not parsed.query and not parsed.fragment,
                    "KIND document origin or path is invalid")
            return response, source

        route = self._fetch(lookup, referer=viewer)
        try:
            _, source = routed(route)
        except DisclosureError as exc:
            raise DocumentFormatError(str(exc), (shell.evidence, route.evidence)) from None
        body = self._fetch(source, referer=viewer)
        return body, (shell.evidence, route.evidence, body.evidence)


def zip_document(body):
    with zipfile.ZipFile(io.BytesIO(body)) as archive:
        members = archive.infolist()
        require(len(members) == 1 and members[0].file_size <= 100 * 1024 * 1024,
                "Unsupported DART ZIP contents")
        return archive.read(members[0])


def api_status(status):
    return status if isinstance(status, str) and re.fullmatch(r"[0-9]{3}", status) else "unknown"


def dart_json(response):
    data = json.loads(response.body)
    status = data.get("status")
    if status not in {"000", "013"}:
        raise DisclosureError(f"DART query incomplete ({api_status(status)})")
    return data


def collect_pages(source, start, end, page_size, get):
    total, last, first, evidence = get(1)
    if total < 0 or last != max(1, (total + page_size - 1) // page_size):
        raise PageConsistencyError("Official page count does not match total")
    if len(first) != min(total, page_size):
        raise PageConsistencyError("Official first page has unexpected row count")
    rows, pages = list(first), [evidence]
    for page in range(2, last + 1):
        new_total, new_last, more, evidence = get(page)
        if (new_total, new_last) != (total, last) or len(more) != min(total - len(rows), page_size):
            raise PageConsistencyError("Official page totals changed or page is missing rows")
        rows.extend(more)
        pages.append(evidence)
    if len(rows) != len({row.accession for row in rows}) or len(rows) != total:
        raise PageConsistencyError("Official query has duplicate or missing receipts")
    return rows, Coverage(source, start, end, total, tuple(pages))


def dart_route(accession, html):
    params = one(r'viewDoc\("([0-9]{14})",\s*"([0-9]+)",\s*"([0-9]+)",\s*"([0-9]+)",\s*"([0-9]+)",\s*"(HTML|dart3[.]xsd)",\s*""\)',
                 html, "Unsupported DART viewer route")
    require(params[0] == accession, "DART viewer selected another receipt")
    one(r'document\.getElementById\("ifrm"\)\.src\s*=\s*"/report/viewer\.do"\s*\+\s*params',
        html, "DART iframe route missing")
    url = "https://dart.fss.or.kr/report/viewer.do?" + urlencode(dict(zip(
        ("rcpNo", "dcmNo", "eleId", "offset", "length", "dtd"), params,
    )))
    return url, dart_family(accession, html)


def dart_family(accession, html):
    family = one(r'<select\b[^>]*\bid="family"[^>]*>(.*?)</select>', html, "DART document family missing")
    options = re.findall(r'<option value="rcpNo=([0-9]{14})"([^>]*)>(.*?)</option>', family, re.DOTALL)
    require([found for found, attrs, _ in options if re.search(r"\bselected\b", attrs)] == [accession],
            "DART document family selected another receipt")
    return tuple((found, " ".join(unescape(title).split())) for found, _, title in options)


class TableRows(HTMLParser):
    def __init__(self):
        super().__init__()
        self.rows = []
        self.cells = []
        self.cell = None
        self.accession = None
        self.accessions = []

    def handle_starttag(self, tag, attrs):
        if tag == "tr":
            self.cells, self.accession = [], None
        elif tag in {"td", "th"}:
            self.cell = []
        elif tag == "br" and self.cell is not None:
            self.cell.append(" ")
        elif tag == "a":
            match = re.search(r"openDisclsViewer\('([0-9]{14})','[^']*'\)", dict(attrs).get("onclick", ""))
            if match:
                self.accession = match[1]

    def handle_data(self, data):
        if self.cell is not None:
            self.cell.append(data)

    def handle_endtag(self, tag):
        if tag in {"td", "th"} and self.cell is not None:
            self.cells.append(" ".join("".join(self.cell).split()))
            self.cell = None
        elif tag == "tr" and self.cells:
            self.rows.append(self.cells)
            if self.accession:
                self.accessions.append((self.accession, self.cells))


def kind_page(response, start, end, page, page_size=PAGE_SIZE):
    html = response.text()
    total, current, last = one(r"전체\s*<em>([\d,]+)</em>건\s*:\s*<strong>(\d+)</strong>/(\d+)",
                               html, "KIND total/page footer missing")
    total, current, last = int(total.replace(",", "")), int(current), int(last)
    require(current == page or (total == last == current == 0 and page == 1), "Unexpected KIND page number")
    table = TableRows()
    table.feed(html)
    rows = []
    for accession, cells in table.accessions:
        _, company, title, _, disclosure_date = cells
        published = date.fromisoformat(disclosure_date)
        require(start <= published <= end,
                "KIND filing outside query")
        rows.append(Filing(accession, published, title, response.evidence, company=company))
    if total == 0:
        require("조회된 결과값이 없습니다." in html, "KIND empty result marker missing")
    listed_pages = {int(item) for item in re.findall(r'href="#page_link_(\d+)"', html)}
    calculated = max(1, (total + page_size - 1) // page_size)
    require(not listed_pages or max(listed_pages) <= calculated, "KIND page links exceed reported total")
    return total, calculated, rows, response.evidence
