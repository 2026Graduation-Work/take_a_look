import csv
import json

import pytest
from experiments.dataset.review_corporate_actions import main


def ledger(folder, *, kind="segment_break", review="True", factor="", evidence=None):
    folder.mkdir()
    security = dict(Code="005930", ISIN="KR7005930003", ListingDate="1975-06-11", DelistingDate="",
                    Market="KOSPI", ShareClass="common", Date="2016-01-04")
    row = dict(security, Resolution=kind, PriceFactor=factor, VolumeFactor="" if review == "True" else "1",
               Review=review, Reason="test", Evidence=json.dumps(evidence or []), FailedCheck="notice_parse_failed")
    for name, rows in (("resolutions", [row]), ("candidates", [security])):
        with (folder / f"{name}.csv").open("w", newline="") as stream:
            writer = csv.DictWriter(stream, list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
    (folder / "manifest.json").write_text(json.dumps({"kind_http_calls_this_run": 0, "dart_http_calls_this_run": 0,
                                                    "table_sha256": {}}))
    (folder / "coverage.json").write_text(json.dumps({"failures": [
        {"AcptNo": "20160722000097", "Reason": "Unsupported KIND market-action form 11308"}]}))


def test_review_comparison_uses_evidence_accession_instead_of_a_sha_substring(tmp_path):
    before, after = tmp_path / "before", tmp_path / "after"
    ledger(before, evidence=[{"accession": "20160104000001", "field": "KIND notice awaiting review",
                              "source": {"sha256": "a20160722000097b"}}])
    ledger(after, kind="bonus", review="False", factor="1/2")
    main(["--output", str(after), "--baseline", str(before), "--summarize-only"])
    report = json.loads((after / "review-summary.json").read_text())
    assert report["new_automatic"] == 1
    assert report["form_11308"]["baseline_review"] == 0
    assert report["form_11308"]["became_bonus"] == 0


def test_review_comparison_rejects_changed_automatic_factors(tmp_path):
    before, after = tmp_path / "before", tmp_path / "after"
    ledger(before, kind="rights", review="False", factor="1/2")
    ledger(after, kind="rights", review="False", factor="1/3")
    with pytest.raises(ValueError, match="previously automatic"):
        main(["--output", str(after), "--baseline", str(before), "--summarize-only"])
    assert not (after / "review-summary.json").exists()


def test_replay_does_not_summarize_old_output_after_an_argument_error(tmp_path):
    output = tmp_path / "old-output"
    ledger(output)
    replay = tmp_path / "replay.json"
    replay.write_text(json.dumps(["--invalid-census-option"]))
    with pytest.raises(SystemExit) as exc:
        main(["--output", str(output), "--kind-root", str(tmp_path / "cache"), "--replay-args", str(replay)])
    assert exc.value.code == 2
    assert not (output / "review-summary.json").exists()
