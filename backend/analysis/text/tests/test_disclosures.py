from analysis.text.value_pipeline.disclosures import classify, to_rows


def test_classify_titles():
    assert classify("반기보고서 (2026.06)") == "periodic"
    assert classify("[기재정정]단일판매ㆍ공급계약체결") == "contract"
    assert classify("기타주요경영사항 (제10회차 전환사채권 발행 결정 철회)") == "bond"
    assert classify("연결재무제표기준영업(잠정)실적(공정공시)") == "earnings"
    assert classify("투자주의환기종목지정") == "market_action"
    assert classify("주식등의대량보유상황보고서(일반)") == "ownership"
    assert classify("임시주주총회결과") == "shareholder_meeting"
    assert classify("증권발행실적보고서") == "securities_filing"
    assert classify("횡령ㆍ배임사실확인") == "business_risk"
    assert classify("동일인등출자계열회사와의상품ㆍ용역거래변경") == "other"


def test_rows_match_master_and_dedupe():
    filings = [
        {"stock_code": "005930", "report_nm": "현금ㆍ현물배당결정", "rcept_no": "20261006000001", "rcept_dt": "20261006"},
        {"stock_code": "005930", "report_nm": "현금ㆍ현물배당결정", "rcept_no": "20261006000001", "rcept_dt": "20261006"},
        {"stock_code": "", "report_nm": "일괄신고서", "rcept_no": "20261006000002", "rcept_dt": "20261006"},
        {"stock_code": "999999", "report_nm": "유상증자결정", "rcept_no": "20261006000003", "rcept_dt": "20261006"},
    ]
    assert to_rows(filings, {"005930"}) == [{"rcept_no": "20261006000001", "stock_code": "005930",
                                             "title": "현금ㆍ현물배당결정", "kind": "dividend", "filed_on": "2026-10-06"}]


def test_dynamic_targets_cap_and_rotation():
    from datetime import date

    from analysis.text.value_pipeline.supabase_sync import (
        DEFAULT_TARGETS,
        NEWSAPI_DAILY_CALLS,
        dynamic_targets,
    )

    holdings = [{"stock_code": f"{i:06d}", "created_at": f"2026-10-{i % 28 + 1:02d}T00:00:00"} for i in range(1, 31)]
    holdings.append({"stock_code": "005930", "created_at": "2026-10-07T00:00:00"})  # 기본 종목은 중복으로 세지 않음

    class Client:
        def select(self, table, params):
            if table == "portfolio_holdings":
                return holdings
            if table == "watchlist":
                return [{"stock_code": "000660", "created_at": "2026-10-30T00:00:00"}]
            codes = params["code"][4:-1].split(",")
            return [{"code": code, "name": f"종목{code}"} for code in codes]

    first = dynamic_targets(Client(), date(2026, 10, 8))
    second = dynamic_targets(Client(), date(2026, 10, 9))
    assert len(first) == NEWSAPI_DAILY_CALLS and set(DEFAULT_TARGETS) <= set(first)
    assert "000660" in first and "000660" in second  # 가장 최근 등록은 매일 포함
    assert set(first) != set(second)  # 남는 종목은 순환
