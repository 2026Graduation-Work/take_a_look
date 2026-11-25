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


@dataclass(frozen=True)
class MarketFiling(Filing):
    displayed: date | None = None
    company_id: str = ""
    submitter: str = ""


@dataclass(frozen=True)
class KindBody(Response):
    document_no: str
    family: tuple[str, ...]
    final: bool


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
                                 company=company, displayed=day, company_id=company_id, submitter=submitter))
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
                "KIND company result identifies another company")
        _, _, company, title, submitter, _ = cells
        rows.append(MarketFiling(accession, displayed, caption or title, response.evidence, stock_code=code,
                                 company=company, displayed=displayed, company_id=company_id, submitter=submitter))
    return total, last, rows, response.evidence


def kind_route(accession, lookup):
    source = one(r"parent\.setPath\(\s*'[^']*'\s*,\s*'([^']+)'", lookup.text(), "KIND document path missing")
    parsed = urlsplit(source)
    match = re.fullmatch(r"/external/(\d{4})/(\d{2})/(\d{2})/(\d{6})/(\d{14})/(\d+)\.htm", parsed.path)
    require(parsed.scheme == "https" and parsed.netloc == "kind.krx.co.kr" and not parsed.query
            and not parsed.fragment and match and "".join(match.groups()[:4]) == accession,
            "KIND document route does not identify the selected accession")
    return source, match[6]


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

    def _get(self, url, *, referer, form=None, daily=None, legacy=None, parse=lambda response: response, page_caches=None):
        request = {"url": url, "form": form, "referer": referer}
        pointer = self.root / "requests" / f"{canonical_hash(request)}.json"
        if page_caches is not None:
            page_caches.append(pointer)
        if pointer.exists():
            return parse(self._cached(pointer, request, self.root))
        response = self._prior_response(request)
        if response is None and daily:
            response = self._import_daily(daily, request)
        if response is None and legacy and legacy.is_file():
            response = self._import_document(legacy, request)
        if response is None:
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

    def cached_company(self, code, start, end):
        """Import a bounded issuer search. Daily market coverage remains independent."""
        require(self.company_cache and re.fullmatch(r"[0-9A-Z]{6}", code), "Invalid KIND company cache or code")

        def page_at(page):
            form = {"method": "searchDetailsSub", "currentPageSize": str(COMPANY_SIZE), "pageIndex": str(page),
                    "orderMode": "1", "orderStat": "D", "forward": "details_sub", "searchCodeType": "number",
                    "searchCorpName": code, "repIsuSrtCd": "A" + code, "fromDate": start.isoformat(),
                    "toDate": end.isoformat(), "reportNm": "", "reportNmTemp": ""}
            cached = self.company_cache / f"{code}_{start}_{end}_p{page}.html"
            if not cached.is_file():
                raise KindUnavailable("Cached KIND company page is missing")
            return self._get(COMPANY_URL, form=form, referer=COMPANY_MAIN, legacy=cached,
                             parse=lambda response: company_page(response, code, start, end, page))

        return collect_pages("KIND company disclosure list", start, end, COMPANY_SIZE, page_at)

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
            rows, span = self._archived_market_list(code, start, end)
            yield code, rows, span

    def _archived_market_list(self, code, start, end):
        def page_at(page):
            form = {"method": "searchDetailsMktactSubExt", "forward": "details_mktact_sub_ext",
                    "searchCodeType": "number", "repIsuSrtCd": f"A{code}", "searchCorpName": code,
                    "searchCorpNameTmp": code, "fromData": start.isoformat(), "toData": end.isoformat(),
                    "currentPageSize": str(PAGE_SIZE), "pageIndex": str(page)}
            request = {"url": KIND_SEARCH, "form": form, "referer": KIND_MAIN}
            response = self._prior_response(request)
            if response is None:
                raise KindUnavailable("Archived KIND market-action page is missing")
            return kind_page(response, start, end, page)

        rows, span = collect_pages("Archived KIND market actions", start, end, PAGE_SIZE, page_at)
        return [MarketFiling(**{**vars(row), "stock_code": code}, displayed=row.published,
                             submitter="한국거래소") for row in rows], span

    def document(self, filing):
        accession = filing.accession
        require(re.fullmatch(r"[0-9]{14}", accession), "Invalid KIND accession")
        folder = next((path for path in self.legacy_docs if all((path / f"{accession}_{name}").is_file()
                       for name in ("viewer.html", "contents.html", "doc.htm"))), None)

        def cached(suffix):
            return folder / f"{accession}_{suffix}" if folder else None

        viewer = KIND_VIEWER + "?" + urlencode({"method": "search", "acptno": accession})
        shell = self._get(viewer, referer=DAILY_MAIN, legacy=cached("viewer.html"))
        refs = [shell.evidence]
        try:
            require(set(re.findall(r'name="acptNo"\s+id="acptNo"\s+value="([0-9]{14})"', shell.text()))
                    == {accession}, "KIND viewer does not identify the requested accession")
            options = one(r'<select\b[^>]*\bid=[\'"]mainDoc[\'"][^>]*>(.*?)</select>',
                          shell.text(), "KIND viewer main document missing")
            doc_no, final = one(r"value=['\"]([0-9]{14})\|([YN])['\"]\s*selected", options,
                                "KIND selected document is ambiguous")
            family = tuple(re.findall(r"value=['\"]([0-9]{14})\|[YN]['\"]", options))
            require(len(family) == len(set(family)), "KIND document family is ambiguous")
            lookup = KIND_VIEWER + "?" + urlencode({"method": "searchContents", "docNo": doc_no})
            route = self._get(lookup, referer=viewer, legacy=cached("contents.html"))
            refs.append(route.evidence)
            source, form = kind_route(accession, route)
            require(f"/{doc_no}/" in urlsplit(source).path, "KIND route document identifier changed")
        except KindUnavailable:
            raise
        except DisclosureError as exc:
            raise DocumentFormatError(str(exc), tuple(refs)) from None
        body = self._get(source, referer=viewer, legacy=cached("doc.htm"))
        return form, KindBody(body.body, body.charset, body.evidence, doc_no, family, final == "Y"), (*refs, body.evidence)
