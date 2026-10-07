"""DART 공시 목록을 하루 단위로 일괄 수집해 종목 마스터(stocks)에 맞추고 제목으로 유형을 나눈다.

회사를 지정하지 않은 list.json은 하루 전체 공시를 100건씩 준다(하루 약 500건 → 5~6회 호출, 일 한도 20,000회).
제목·날짜·유형만 저장하고 원문 본문은 저장하지 않는다. 유형표는 docs/disclosure-kinds.md.
"""
from __future__ import annotations

import json
import re
from datetime import date, timedelta
from urllib.parse import urlencode
from urllib.request import urlopen

from .config import SETTINGS

LIST_URL = "https://opendart.fss.or.kr/api/list.json"
LOOKBACK_DAYS = 3  # 늦게 올라온 공시까지 겹쳐 받는다(같은 접수번호는 덮어씀)

# (유형, 제목 규칙). 위에서부터 처음 맞는 것. 화면 이름·풀이는 frontend/lib/copy-glossary.ts DISCLOSURE_KIND
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


def fetch_day(day: date, api_key: str) -> list[dict]:
    rows, page = [], 1
    while True:
        query = urlencode({"crtfc_key": api_key, "bgn_de": day.strftime("%Y%m%d"), "end_de": day.strftime("%Y%m%d"),
                           "page_no": page, "page_count": 100})
        with urlopen(f"{LIST_URL}?{query}", timeout=30) as response:
            data = json.loads(response.read())
        if data.get("status") == "013":  # 조회된 데이터 없음
            return rows
        if data.get("status") != "000":
            raise RuntimeError(f"DART list.json status {data.get('status')}")
        rows.extend(data["list"])
        if page >= int(data.get("total_page", 1)):
            return rows
        page += 1


def to_rows(filings: list[dict], codes: set[str]) -> list[dict]:
    rows = {}
    for item in filings:
        code = (item.get("stock_code") or "").strip()
        if code not in codes:
            continue
        title = " ".join(str(item["report_nm"]).split())[:300]
        rows[item["rcept_no"]] = {"rcept_no": item["rcept_no"], "stock_code": code, "title": title,
                                  "kind": classify(title), "filed_on": date.fromisoformat(
                                      f"{item['rcept_dt'][:4]}-{item['rcept_dt'][4:6]}-{item['rcept_dt'][6:]}").isoformat()}
    return list(rows.values())


def sync(client, today: date | None = None) -> int:
    api_key = SETTINGS.dart_api_key
    if not api_key:
        raise RuntimeError("DART_API_KEY가 필요합니다")
    today = today or date.today()
    codes = {row["code"] for row in client.select("stocks", params={"select": "code", "order": "code"})}
    filings = [item for back in range(LOOKBACK_DAYS) for item in fetch_day(today - timedelta(days=back), api_key)]
    rows = to_rows(filings, codes)
    if rows:
        client.upsert("disclosures", rows, on_conflict="rcept_no")
    print(json.dumps({"event": "disclosures", "fetched": len(filings), "matched": len(rows)}, ensure_ascii=False))
    return len(rows)
