import io
import json
from datetime import date
from http.client import IncompleteRead, RemoteDisconnected
from types import SimpleNamespace
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlsplit

import pytest
from analysis.text.value_pipeline import disclosures, supabase_sync
from analysis.text.value_pipeline.disclosures import classify, to_rows
from analysis.text.value_pipeline.supabase_store import SupabaseWriteError


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


def test_get_retries_timeout(monkeypatch):
    calls = []

    def fake_urlopen(url, timeout):
        calls.append(url)
        if len(calls) == 1:
            raise URLError("timed out")
        return io.BytesIO(b'{"status": "013"}')

    monkeypatch.setattr(disclosures, "open_dart", fake_urlopen)
    monkeypatch.setattr(disclosures.time, "sleep", lambda s: None)
    assert disclosures._get("u") == {"status": "013"}
    assert len(calls) == 2


MONDAY = date(2026, 11, 23)
FRIDAY = date(2026, 11, 20)


def filing(day, number=1, title="현금ㆍ현물배당결정", stock_code="005930"):
    return {"stock_code": stock_code, "report_nm": title,
            "rcept_no": f"{day:%Y%m%d}{number:06d}", "rcept_dt": f"{day:%Y%m%d}"}


def page(number, total, rows):
    return {"status": "000", "page_no": number, "total_count": total, "page_count": 100,
            "total_page": (total + 99) // 100, "list": rows}


class MemoryDatabase:
    def __init__(self, fail_write=None):
        self.rows = {}
        self.writes = 0
        self.fail_write = fail_write

    def select(self, table, *, params):
        assert table == "stocks"
        return [{"code": "005930"}]

    def upsert(self, table, rows, *, on_conflict):
        assert table == "disclosures" and on_conflict == "rcept_no"
        self.writes += 1
        if self.writes == self.fail_write:
            raise SupabaseWriteError("database unavailable")
        self.rows.update((row[on_conflict], row) for row in rows)


@pytest.fixture
def mock_dart(monkeypatch):
    calls = []

    def install(respond):
        def open_response(url, timeout):
            params = parse_qs(urlsplit(url).query)
            day = date.fromisoformat(params["bgn_de"][0])
            assert params["end_de"] == params["bgn_de"]
            assert params["last_reprt_at"] == ["N"]
            number = int(params["page_no"][0])
            calls.append((day, number))
            return io.BytesIO(json.dumps(respond(day, number)).encode())
        monkeypatch.setattr(disclosures, "open_dart", open_response)
        return calls

    monkeypatch.setattr(disclosures, "SETTINGS", SimpleNamespace(dart_api_key="test-key"))
    monkeypatch.setattr(disclosures.time, "sleep", lambda _: None)
    return install


def test_default_kst_overlap_includes_friday_weekend_and_empty_days(mock_dart):
    def respond(day, number):
        if day == FRIDAY:
            return page(1, 2, [filing(day), filing(day, 2, stock_code="999999")])
        return {"status": "013"}

    calls = mock_dart(respond)
    store = MemoryDatabase()
    days = disclosures.filing_days(None, None, today=MONDAY)
    results = disclosures.sync(store, days=days, budget=disclosures.RequestBudget())
    assert [result.day.isoformat() for result in results] == [
        "2026-11-23", "2026-11-22", "2026-11-21", "2026-11-20", "2026-11-19", "2026-11-18", "2026-11-17",
    ]
    assert all(result.status == "complete" for result in results)
    assert [result.fetched for result in results] == [0, 0, 0, 2, 0, 0, 0]
    assert [result.written for result in results] == [0, 0, 0, 1, 0, 0, 0]
    assert calls == [(day, 1) for day in days]
    assert [row["filed_on"] for row in store.rows.values()] == [FRIDAY.isoformat()]


@pytest.mark.parametrize("failure", ["timeout", "empty_page", "wrong_date", "repeated_receipt"])
def test_second_page_failure_never_writes_first_page(mock_dart, failure):
    def respond(day, number):
        if day == MONDAY:
            return page(1, 1, [filing(day)])
        if number == 1:
            return page(1, 101, [filing(day, i) for i in range(100)])
        if failure == "timeout":
            raise TimeoutError
        if failure == "empty_page":
            return {"status": "013"}
        if failure == "wrong_date":
            return page(2, 101, [filing(MONDAY, 101)])
        return page(2, 101, [filing(day, 1)])

    calls = mock_dart(respond)
    store = MemoryDatabase()
    results = disclosures.sync(store, days=[FRIDAY, MONDAY], budget=disclosures.RequestBudget())
    assert [result.status for result in results] == ["incomplete", "complete"]
    assert calls.count((FRIDAY, 2)) == (3 if failure == "timeout" else 1)
    assert {row["filed_on"] for row in store.rows.values()} == {MONDAY.isoformat()}


@pytest.mark.parametrize("code", [429, 503])
def test_retries_charge_run_budget(mock_dart, code):
    def respond(day, number):
        if len(calls) <= 2:
            raise HTTPError("not logged", code, "error", {}, None)
        return {"status": "013"}

    calls = mock_dart(respond)
    budget = disclosures.RequestBudget(3)
    results = disclosures.sync(MemoryDatabase(), days=[FRIDAY, MONDAY], budget=budget)
    assert len(calls) == budget.used == 3
    assert [result.status for result in results] == ["complete", "incomplete"]
    assert results[1].reason == "attempt_budget_exhausted"


def test_budget_exhausted_during_retry_marks_remaining_dates(mock_dart):
    def unavailable(day, number):
        raise TimeoutError

    calls = mock_dart(unavailable)
    budget = disclosures.RequestBudget(2)
    results = disclosures.sync(MemoryDatabase(), days=[FRIDAY, MONDAY], budget=budget)
    assert len(calls) == budget.used == 2
    assert [result.status for result in results] == ["incomplete", "not_attempted"]


@pytest.mark.parametrize(("data", "reason"), [
    ({"status": "010"}, "dart_010"),
    ({"status": "020"}, "dart_020"),
    ({"status": "000", "total_count": 10001, "total_page": 101}, "page_budget_exhausted"),
])
def test_run_stops_at_auth_quota_and_page_limits(mock_dart, data, reason):
    calls = mock_dart(lambda *_: data)
    store = MemoryDatabase()
    results = disclosures.sync(store, days=[FRIDAY, MONDAY], budget=disclosures.RequestBudget())
    assert len(calls) == 1
    assert [(result.status, result.reason) for result in results] == [
        ("incomplete", reason), ("not_attempted", reason),
    ]
    assert not store.rows


def test_replay_repairs_partial_upsert_and_updates_receipts(mock_dart, monkeypatch):
    data = [filing(FRIDAY, 1), filing(FRIDAY, 2, "[기재정정]현금ㆍ현물배당결정")]
    mock_dart(lambda *_: page(1, len(data), data))
    monkeypatch.setattr(disclosures, "WRITE_BATCH_SIZE", 1)
    store = MemoryDatabase(fail_write=2)
    existing = filing(FRIDAY, 3)
    store.rows.update({existing["rcept_no"]: existing})

    [first] = disclosures.sync(store, days=[FRIDAY], budget=disclosures.RequestBudget())
    assert (first.status, first.matched, first.written) == ("incomplete", 2, 1)
    assert data[1]["rcept_no"] not in store.rows

    data[0]["report_nm"] = "주식배당결정"
    [second] = disclosures.sync(store, days=[FRIDAY], budget=disclosures.RequestBudget())
    assert (second.status, second.written) == ("complete", 2)
    assert len(store.rows) == 3
    assert store.rows[data[0]["rcept_no"]]["title"] == "주식배당결정"
    assert store.rows[data[1]["rcept_no"]]["title"].startswith("[기재정정]")
    assert store.rows[existing["rcept_no"]] == existing


@pytest.mark.parametrize(("start", "end"), [
    ("2026-11-20", None), (None, "2026-11-20"), ("2026-11-27", "2026-11-28"),
    ("2026-11-23", "2026-11-22"), ("2026-07-26", "2026-11-23"), ("20261120", "2026-11-23"),
])
def test_invalid_ranges_are_rejected(start, end):
    with pytest.raises(ValueError):
        disclosures.filing_days(start, end, today=MONDAY)


def test_inclusive_range_accepts_leap_day_and_exact_limit():
    days = disclosures.filing_days("2024-02-28", "2024-06-26", today=MONDAY)
    assert len(days) == 120
    assert days[:3] == [date(2024, 2, 28), date(2024, 2, 29), date(2024, 3, 1)]
    assert days[-1] == date(2024, 6, 26)


def test_dry_run_skips_configuration_and_network(monkeypatch, capsys):
    def unexpected_call():
        pytest.fail("dry-run made an external request")

    monkeypatch.setattr(supabase_sync.supabase_store.SupabaseRestClient, "from_env", unexpected_call)
    assert supabase_sync.main([
        "disclosures", "--start", "2024-02-28", "--end", "2024-03-01",
        "--dry-run", "--max-http-attempts", "40",
    ]) == 0
    assert json.loads(capsys.readouterr().out) == {
        "event": "disclosures_plan", "dates": ["2024-02-28", "2024-02-29", "2024-03-01"],
        "max_http_attempts": 40,
    }


def test_cli_reports_incomplete_day_with_failure_exit_code(mock_dart, monkeypatch, capsys):
    mock_dart(lambda *_: {"status": "010"})
    monkeypatch.setattr(
        supabase_sync.supabase_store.SupabaseRestClient, "from_env", lambda: MemoryDatabase(),
    )
    assert supabase_sync.main(["disclosures", "--start", "2024-01-01", "--end", "2024-01-02"]) == 1
    first, second, summary = map(json.loads, capsys.readouterr().out.splitlines())
    assert (first["status"], first["reason"]) == ("incomplete", "dart_010")
    assert second["status"] == "not_attempted"
    assert summary["http_attempts"] == 1
    assert summary["incomplete_days"] == 2


def test_http_auth_failure_is_not_retried(mock_dart):
    def respond(day, number):
        raise HTTPError("not logged", 403, "error", {}, None)

    calls = mock_dart(respond)
    results = disclosures.sync(MemoryDatabase(), days=[FRIDAY, MONDAY], budget=disclosures.RequestBudget())
    assert len(calls) == 1
    assert [result.status for result in results] == ["incomplete", "not_attempted"]
    assert results[0].reason == "http_403"


@pytest.mark.parametrize("fault", ["truncated_body", "no_headers"])
@pytest.mark.parametrize("recover", [False, True])
def test_transport_fault_preserves_completed_days_and_redacts_error(mock_dart, monkeypatch, capsys, fault, recover):
    requests = []
    store = MemoryDatabase()

    class TruncatedBody(io.BytesIO):
        def read(self, *args):
            raise IncompleteRead(b"response-body-marker")

    def open_response(url, timeout):
        day = date.fromisoformat(parse_qs(urlsplit(url).query)["bgn_de"][0])
        requests.append(day)
        if day == FRIDAY:
            return io.BytesIO(json.dumps(page(1, 1, [filing(day)])).encode())
        if recover and requests.count(day) == 2:
            return io.BytesIO(b'{"status":"013"}')
        if fault == "no_headers":
            raise RemoteDisconnected("response-body-marker")
        return TruncatedBody()

    monkeypatch.setattr(disclosures, "open_dart", open_response)
    monkeypatch.setattr(supabase_sync.supabase_store.SupabaseRestClient, "from_env", lambda: store)
    exit_code = supabase_sync.main(["disclosures", "--start", "2026-11-20", "--end", "2026-11-21"])
    captured = capsys.readouterr()
    first, second, summary = map(json.loads, captured.out.splitlines())
    assert (first["status"], first["written"]) == ("complete", 1)
    assert list(store.rows) == [filing(FRIDAY)["rcept_no"]]
    assert (second["status"], second["reason"]) == (
        ("complete", None) if recover else ("incomplete", "dart_network_error")
    )
    assert exit_code == int(not recover)
    assert len(requests) == summary["http_attempts"] == (3 if recover else 4)
    assert "response-body-marker" not in captured.out + captured.err
    assert "test-key" not in captured.out + captured.err
