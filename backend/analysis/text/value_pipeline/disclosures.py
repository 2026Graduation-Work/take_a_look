"""DART 공시 목록을 접수일별로 수집해 종목 마스터와 연결한다."""
from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from http.client import HTTPException
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import HTTPRedirectHandler, build_opener
from zoneinfo import ZoneInfo

from .config import SETTINGS
from .supabase_store import SupabaseWriteError

LIST_URL = "https://opendart.fss.or.kr/api/list.json"
LOOKBACK_DAYS = 7
MAX_RANGE_DAYS = 120
PAGE_SIZE = 100
MAX_PAGES = 100
MAX_HTTP_ATTEMPTS = 2_000
REQUEST_ATTEMPTS = 3
WRITE_BATCH_SIZE = 500
KST = ZoneInfo("Asia/Seoul")

# (유형, 제목 규칙). 위에서부터 처음 맞는 것.
KIND_RULES: tuple[tuple[str, str], ...] = (
    ("market_action", r"관리종목|상장폐지|불성실공시|투자주의|투자경고|투자위험|매매거래정지"),
    ("business_risk", r"횡령|배임|자본잠식|생산중단|회생절차|부도"),
    ("inquiry", r"조회공시|풍문"),
    ("periodic", r"사업보고서|반기보고서|분기보고서"),
    ("earnings", r"잠정\)?실적|영업실적|매출액또는손익구조"),
    ("contract", r"단일판매|공급계약"),
    ("capital_raise", r"유상증자"),
    ("bonus_issue", r"무상증자"),
    ("bond", r"전환사채|신주인수권부사채|교환사채"),
    ("buyback", r"자기주식|주식소각"),
    ("dividend", r"배당"),
    ("restructure", r"합병|분할|영업양수|영업양도|주식교환"),
    ("ownership", r"최대주주|주요주주|대량보유"),
    ("lawsuit", r"소송"),
    ("investment", r"타법인주식|출자증권|채무보증"),
    ("shareholder_meeting", r"주주총회|의결권|주주명부"),
    ("investor_relations", r"기업설명회|실적공시예고"),
    ("securities_filing", r"증권발행실적|일괄신고|투자설명서|증권신고서"),
)


def classify(title: str) -> str:
    for kind, pattern in KIND_RULES:
        if re.search(pattern, title):
            return kind
    return "other"


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


open_dart = build_opener(NoRedirect()).open

class DartError(RuntimeError):
    def __init__(self, code: str, *, stop_run: bool = False) -> None:
        super().__init__(code)
        self.stop_run = stop_run


@dataclass
class RequestBudget:
    limit: int = MAX_HTTP_ATTEMPTS
    used: int = 0

    def __post_init__(self) -> None:
        if not 1 <= self.limit <= MAX_HTTP_ATTEMPTS:
            raise ValueError(f"HTTP 시도 상한은 1~{MAX_HTTP_ATTEMPTS}이어야 합니다")

    def take(self) -> None:
        if self.used >= self.limit:
            raise DartError("attempt_budget_exhausted", stop_run=True)
        self.used += 1


def filing_days(
    start: str | None, end: str | None, *, today: date | None = None,
) -> list[date]:
    today = today or datetime.now(KST).date()
    if (start is None) != (end is None):
        raise ValueError("--start와 --end는 함께 지정해야 합니다")
    if start is None:
        return [today - timedelta(days=offset) for offset in range(LOOKBACK_DAYS)]
    if not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", start) or not re.fullmatch(
        r"[0-9]{4}-[0-9]{2}-[0-9]{2}", end,
    ):
        raise ValueError("날짜는 YYYY-MM-DD 형식이어야 합니다")
    try:
        first, last = date.fromisoformat(start), date.fromisoformat(end)
    except ValueError:
        raise ValueError("유효한 날짜를 지정해야 합니다") from None
    days = (last - first).days + 1
    if not 1 <= days <= MAX_RANGE_DAYS or last > today:
        raise ValueError("과거 또는 오늘까지, 시작일부터 종료일까지 최대 120일을 지정해야 합니다")
    return [first + timedelta(days=offset) for offset in range(days)]


def _get(url: str, budget: RequestBudget | None = None) -> dict:
    budget = budget or RequestBudget()
    for attempt in range(REQUEST_ATTEMPTS):
        budget.take()
        try:
            with open_dart(url, timeout=30) as response:
                data = json.loads(response.read())
        except HTTPError as exc:
            exc.close()
            if exc.code != 429 and not 500 <= exc.code <= 599:
                raise DartError(f"http_{exc.code}", stop_run=exc.code in {401, 403}) from None
            error = DartError(f"http_{exc.code}", stop_run=exc.code == 429)
        except (OSError, HTTPException):
            error = DartError("dart_network_error")
        except (UnicodeError, ValueError):
            raise DartError("invalid_response") from None
        else:
            if not isinstance(data, dict):
                raise DartError("invalid_response")
            return data
        if attempt == REQUEST_ATTEMPTS - 1:
            raise error
        if budget.used < budget.limit:
            time.sleep(10 * (attempt + 1))
    raise AssertionError("unreachable")


def _page_number(data: dict, field: str) -> int:
    value = data.get(field)
    if type(value) is int:
        return value
    if isinstance(value, str) and re.fullmatch(r"[0-9]{1,9}", value):
        return int(value)
    raise DartError("invalid_pagination")


def _validate_filing(item: dict, day: date) -> None:
    if not isinstance(item, dict):
        raise DartError("invalid_filing")
    receipt, title, code = (item.get(field) for field in ("rcept_no", "report_nm", "stock_code"))
    if (
        not isinstance(receipt, str) or not re.fullmatch(r"[0-9]{14}", receipt)
        or not isinstance(title, str) or not title.strip()
        or not isinstance(code, str)
        or item.get("rcept_dt") != day.strftime("%Y%m%d")
    ):
        raise DartError("invalid_filing")


def fetch_day(day: date, api_key: str, budget: RequestBudget) -> list[dict]:
    filings: list[dict] = []
    expected_total = None
    for page in range(1, MAX_PAGES + 1):
        date_param = day.strftime("%Y%m%d")
        query = urlencode({
            "crtfc_key": api_key, "bgn_de": date_param, "end_de": date_param,
            "last_reprt_at": "N", "page_no": page, "page_count": PAGE_SIZE,
        })
        data = _get(f"{LIST_URL}?{query}", budget)
        status = data.get("status")
        if status == "013" and page == 1:
            if data.get("list"):
                raise DartError("invalid_pagination")
            return []
        if isinstance(status, str) and status in {"010", "011", "012", "020", "101", "901"}:
            raise DartError(f"dart_{status}", stop_run=True)
        if status != "000":
            code = status if isinstance(status, str) and re.fullmatch(r"[0-9]{3}", status) else "unknown"
            raise DartError(f"dart_{code}")

        total = _page_number(data, "total_count")
        pages = _page_number(data, "total_page")
        if pages > MAX_PAGES:
            raise DartError("page_budget_exhausted", stop_run=True)
        if expected_total is None:
            expected_total = total
        page_rows = data.get("list")
        limit = min(PAGE_SIZE, total - len(filings))
        if (
            total != expected_total or pages != (total + PAGE_SIZE - 1) // PAGE_SIZE
            or _page_number(data, "page_no") != page or _page_number(data, "page_count") != PAGE_SIZE
            or limit <= 0 or not isinstance(page_rows, list) or len(page_rows) != limit
        ):
            raise DartError("invalid_pagination")
        for filing in page_rows:
            _validate_filing(filing, day)
        filings.extend(page_rows)
        if page == pages:
            if len({filing["rcept_no"] for filing in filings}) != total:
                raise DartError("duplicate_receipts_in_pages")
            return filings
    raise AssertionError("unreachable")


def to_rows(filings: list[dict], codes: set[str]) -> list[dict]:
    rows = {}
    for item in filings:
        code = (item.get("stock_code") or "").strip()
        if code not in codes:
            continue
        title = " ".join(item["report_nm"].split())[:300]
        receipt = item["rcept_no"]
        rows[receipt] = {
            "rcept_no": receipt, "stock_code": code, "title": title,
            "kind": classify(title), "filed_on": date.fromisoformat(item["rcept_dt"]).isoformat(),
        }
    return list(rows.values())


@dataclass
class DayResult:
    day: date
    status: str
    fetched: int = 0
    matched: int = 0
    written: int = 0
    reason: str | None = None


def sync(client, *, days: list[date], budget: RequestBudget) -> list[DayResult]:
    api_key = SETTINGS.dart_api_key
    if not api_key:
        raise RuntimeError("DART_API_KEY가 필요합니다")
    codes = {row["code"] for row in client.select("stocks", params={"select": "code", "order": "code"})}
    if not codes:
        raise RuntimeError("종목 마스터가 비어 있습니다")

    results = []
    stop_reason = None
    for day in days:
        result = DayResult(day, "not_attempted")
        results.append(result)
        if stop_reason:
            result.reason = stop_reason
            continue
        try:
            filings = fetch_day(day, api_key, budget)
        except DartError as exc:
            result.status = "incomplete"
            result.reason = str(exc)
            if exc.stop_run:
                stop_reason = result.reason
            continue
        rows = to_rows(filings, codes)
        result.fetched, result.matched = len(filings), len(rows)
        try:
            for offset in range(0, len(rows), WRITE_BATCH_SIZE):
                batch = rows[offset:offset + WRITE_BATCH_SIZE]
                client.upsert("disclosures", batch, on_conflict="rcept_no")
                result.written += len(batch)
        except SupabaseWriteError:
            result.status = "incomplete"
            result.reason = "supabase_write_failed"
        else:
            result.status = "complete"
    return results
