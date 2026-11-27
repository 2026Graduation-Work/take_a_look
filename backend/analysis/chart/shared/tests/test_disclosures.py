import json
from datetime import date

import pytest
import requests
from shared.data.disclosures import (
    Coverage,
    DisclosureError,
    Evidence,
    Filing,
    OfficialDisclosures,
    collect_pages,
)


class Wire:
    def __init__(self, *bodies):
        self.bodies = iter(bodies)
        self.calls = 0

    def request(self, *args, **kwargs):
        self.calls += 1
        body = next(self.bodies)
        if isinstance(body, Exception):
            raise body
        response = requests.Response()
        response.status_code = 200
        response._content = body
        response._content_consumed = True
        return response


def test_resume_and_document_revision(tmp_path):
    secret = "key-which-must-stay-with-the-request"
    archive = tmp_path / "archive"
    endpoint = "https://opendart.fss.or.kr/api/document.xml"
    wire = Wire(b"original", requests.RequestException(endpoint + "?crtfc_key=" + secret))
    owner = OfficialDisclosures(archive, tmp_path / "first", secret, 2, session=wire)
    original = owner._fetch(endpoint)
    with pytest.raises(DisclosureError, match="^Official HTTP request failed$"):
        owner._fetch(endpoint, params={"page_no": 2})
    resumed = OfficialDisclosures(archive, tmp_path / "first", secret, 1, session=Wire(b"next page"))
    assert resumed._fetch(endpoint).evidence == original.evidence
    assert resumed._fetch(endpoint, params={"page_no": 2}).body == b"next page"
    next_run = OfficialDisclosures(archive, tmp_path / "second", secret, 1, session=Wire(b"new version"))
    updated = next_run._fetch(endpoint)
    assert updated.evidence.sha256 != original.evidence.sha256
    assert (archive / "objects" / original.evidence.sha256).read_bytes() == b"original"
    assert all(secret.encode() not in path.read_bytes() for path in tmp_path.rglob("*") if path.is_file())


def test_failed_page_never_returns_coverage():
    day = date(2021, 7, 22)
    evidence = Evidence("list", "receipt")
    first, second = [Filing(str(i), day, "notice", evidence) for i in range(2)]
    with pytest.raises(DisclosureError, match="missing rows"):
        collect_pages("KIND", day, day, 1, lambda page: (2, 2, [first] if page == 1 else [], evidence))
    with pytest.raises(DisclosureError, match="duplicate"):
        collect_pages("KIND", day, day, 1, lambda page: (2, 2, [first], evidence))
    rows, covered = collect_pages("KIND", day, day, 1, lambda page: (2, 2, [[first, second][page - 1]], evidence))
    assert rows == [first, second]
    assert covered == Coverage("KIND", day, day, 2, (evidence, evidence))
    assert collect_pages("KIND", day, day, 1, lambda page: (0, 1, [], evidence))[1].rows == 0


def test_dart_changed_totals_restart_that_window_on_resume(tmp_path):
    def page(number, total, rows):
        return json.dumps({
            "status": "000", "page_no": number, "page_count": 100, "total_count": total, "total_page": 2,
            "list": [{"corp_code": "00126380", "rcept_dt": "20180503", "rcept_no": f"20180503{i:06d}",
                      "report_nm": "notice", "corp_name": "issuer", "stock_code": "005930"} for i in rows],
        }).encode()

    day = date(2018, 5, 3)
    first = page(1, 101, range(100))
    wire = Wire(first, page(2, 102, range(100, 102)))
    archive, run = tmp_path / "archive", tmp_path / "run"
    with pytest.raises(DisclosureError, match="totals changed"):
        OfficialDisclosures(archive, run, "test-key", 2, session=wire).dart_list("00126380", day, day)
    assert len(list((archive / "objects").iterdir())) == 2
    repaired = Wire(first, page(2, 101, [100]))
    rows, proof = OfficialDisclosures(archive, run, "test-key", 2, session=repaired).dart_list("00126380", day, day)
    assert len(rows) == proof.rows == 101 and repaired.calls == 2
    assert len(list((archive / "objects").iterdir())) == 3


def test_dart_uses_explicit_publication_date_for_coverage(tmp_path):
    listing = json.dumps({"status": "000", "page_no": 1, "page_count": 100, "total_count": 1, "total_page": 1,
                          "list": [{"corp_code": "00126380", "rcept_dt": "20180510", "rcept_no": "20180509003300",
                                    "report_nm": "notice", "corp_name": "issuer", "stock_code": "005930"}]}).encode()
    client = OfficialDisclosures(tmp_path / "archive", tmp_path / "run", "test-key", 1, session=Wire(listing))
    day = date(2018, 5, 10)
    rows, coverage = client.dart_list("00126380", day, day)
    assert rows[0].published == day and coverage.rows == 1
