import io
import json
import zipfile
from datetime import date

import pandas as pd
import pytest
from experiments.dataset.collect_actions import collect_security, publish_snapshot
from shared.data.actions import read_snapshot
from shared.data.calendar import scheduled_sessions
from shared.data.disclosures import Coverage, DisclosureError
from shared.tests.test_disclosures import Wire
from shared.tests.test_official_actions import action_case, filing, response


def test_publish_resumes_failed_query_and_keeps_previous_snapshot(tmp_path):
    security, *_ = action_case("005930")
    index = io.BytesIO()
    with zipfile.ZipFile(index, "w") as archive:
        archive.writestr("CORPCODE.xml", f"<result><list><corp_code>{security.corporation}</corp_code>"
                         f"<stock_code>{security.issuer_code}</stock_code></list></result>")
    no_dart = b'{"status":"013","message":"no data"}'
    no_kind = response("samsung-empty.html").body
    start, end = date(2018, 6, 4), date(2018, 6, 8)
    scope = ([security], start, end, start, end, "fixture-key")
    wire = Wire(index.getvalue(), no_dart)
    with pytest.raises(DisclosureError, match="Official queries incomplete"):
        publish_snapshot(tmp_path, "first", *scope, 2, session=wire)
    record = json.loads((tmp_path / "runs/first/status.json").read_text())
    assert list(record["securities"].values())[0]["status"] == "query_failed"
    assert not (tmp_path / "snapshots").exists()

    resumed = Wire(no_kind)
    path = publish_snapshot(tmp_path, "first", *scope, 1, session=resumed)
    assert resumed.calls == 1
    original = path.read_bytes()
    snapshot = read_snapshot(path, verify_archive=True)
    selected = snapshot["securities"][0]
    assert selected["status"] == "covered"
    assert selected["actions"] == []
    assert {c["source"]: c["rows"] for c in selected["coverage"]} == {"OpenDART list": 0, "KIND market actions": 0}
    assert publish_snapshot(tmp_path, "first", *scope, 1, session=Wire()) == path

    next_path = publish_snapshot(tmp_path, "second", *scope, 3, session=Wire(index.getvalue(), no_dart, no_kind))
    assert next_path != path
    assert path.read_bytes() == original
    next_snapshot = read_snapshot(next_path, verify_archive=True)
    assert next_snapshot["securities"][0]["status"] == "covered"
    kind_blob = next(item for item in next_snapshot["securities"][0]["coverage"] if item["source"].startswith("KIND"))
    (tmp_path / "archive/objects" / kind_blob["pages"][0]["sha256"]).write_bytes(b"damaged response")
    with pytest.raises(DisclosureError, match="Official evidence changed"):
        publish_snapshot(tmp_path, "first", *scope, 1, session=Wire())


def test_missing_structured_detail_does_not_resolve_a_same_day_family():
    security, decisions, notice, sessions, _ = action_case("104620")
    body = response("104620-bonus.response")
    notice_body = response("104620.notice.html")
    original, newer, latest = decisions[0].accession, "20210708000001", "20210708000002"
    title = "주요사항보고서(무상증자결정)"
    revisions = ((latest, "[정정] " + title), (newer, "[정정] " + title), (original, title))
    entries = [filing(accession, name, body, security) for accession, name in revisions]
    kind_notice = filing(notice.evidence.accession, "권리락(무상증자)", notice_body)
    details = {**json.loads(body.body)["list"][0], "rcept_no": latest}

    class Official:
        corp_index = {security.issuer_code: {security.corporation}}

        def dart_list(self, corporation, start, end):
            return entries, Coverage("OpenDART list", start, end, 3, (body.evidence,))

        def dart_details(self, endpoint, corporation, start, end):
            return [details], Coverage(endpoint, start, end, 1, (body.evidence,))

        def dart_document(self, accession, **kwargs):
            return body, revisions, (body.evidence,)

        def kind_list(self, code, start, end):
            return [kind_notice], Coverage("KIND market actions", start, end, 1, (notice_body.evidence,))

        def kind_document(self, filing):
            return notice_body, (notice_body.evidence,)

    _, documents, actions, pending = collect_security(
        Official(), security, "2021-07-19", "2021-08-20", date(2021, 7, 1), date(2021, 8, 31), sessions,
    )
    assert {row["accession"] for row in documents} == {original, newer, latest, kind_notice.accession}
    assert not actions and any("same-day official decision revision" in row for row in pending)


@pytest.mark.parametrize("response_bytes, error", [
    (b"<result><status>020</status></result>", "020"),
    (b"PK malformed ZIP", "Invalid OpenDART corporation archive"),
])
def test_corporation_fetch_error_survives_in_checkpoint(tmp_path, response_bytes, error):
    security, *_ = action_case("005930")
    day = date(2018, 5, 4)
    with pytest.raises(DisclosureError, match=error):
        publish_snapshot(tmp_path, "failed", [security], day, day, day, day, "fixture-key", 1,
                         session=Wire(response_bytes))
    failure = json.loads((tmp_path / "runs/failed/status.json").read_text())
    assert error in failure["query_error"] and not failure["securities"]


def test_calendar_accepts_single_trading_day_or_holiday():
    session = pd.Timestamp("2018-05-04")
    holiday = pd.Timestamp("2016-01-01")
    assert scheduled_sessions(session, session).tolist() == [session]
    assert scheduled_sessions(holiday, holiday).empty


def test_issuer_market_actions_discover_preferred_share_listing():
    security, decisions, notice, sessions, _ = action_case("005935", preferred=True)
    title = "주식분할결정"
    family = tuple((decision.accession, title if decision.accession == decision.family else "[정정] " + title)
                   for decision in decisions)
    dart_bodies = {accession: response(f"{accession}.body.html") for accession, _ in family}
    entries = [filing(accession, name, dart_bodies[accession], security) for accession, name in family]
    notice_body = response("20180503000318.notice.html")
    kind_notice = filing(notice.evidence.accession, "변경상장(액면분할)", notice_body)

    class Official:
        corp_index = {security.issuer_code: {security.corporation}}

        def dart_list(self, corporation, start, end):
            return entries, Coverage("OpenDART list", start, end, len(entries), (entries[0].evidence,))

        def dart_document(self, accession, **kwargs):
            body = dart_bodies[accession]
            return body, family, (body.evidence,)

        def kind_list(self, code, start, end):
            entries = [kind_notice] if code == security.issuer_code else []
            return entries, Coverage("KIND market actions", start, end, len(entries), (notice_body.evidence,))

        def kind_document(self, filing):
            return notice_body, (notice_body.evidence,)

    _, _, actions, pending = collect_security(
        Official(), security, "2018-05-04", "2018-05-04", date(2018, 1, 1), date(2018, 5, 31), sessions,
    )
    assert pending == []
    assert [(event.ex_date, event.shares, event.new_units, event.old_units) for event in actions] == [
        ("2018-05-04", (18_072_580, 903_629_000), 50, 1),
    ]
