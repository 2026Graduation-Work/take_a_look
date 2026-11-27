"""Replay a preserved action census without HTTP and compare its decisions with a baseline."""

import argparse
import csv
import json
import socket
from collections import Counter
from pathlib import Path
from unittest.mock import patch

from shared.data.resolution_snapshot import REVIEW_COLUMNS, ResolutionSnapshot, _load_tables
from shared.io import atomic_json, sha256

from .census_actions import _write_csv
from .census_actions import main as census

IDENTITY = ("Code", "ISIN", "ListingDate", "DelistingDate", "Market", "ShareClass", "Date")
DECISION = ("Resolution", "PriceFactor", "VolumeFactor", "Review")


def _read(folder, name):
    with (folder / f"{name}.csv").open(newline="", encoding="utf-8") as stream:
        return list(csv.DictReader(stream))


def summarize(folder, baseline=None):
    rows = _read(folder, "resolutions")
    candidates = _read(folder, "candidates")
    def identity(row):
        return tuple(row[field] for field in IDENTITY)
    candidate_keys = {identity(row) for row in candidates}
    current = {identity(row): row for row in rows}
    if len(current) != len(rows):
        raise ValueError("Duplicate census resolution identity")
    reviews = [row for row in rows if row["Review"] == "True"]
    manifest = json.loads((folder / "manifest.json").read_text())
    if manifest["kind_http_calls_this_run"] or manifest["dart_http_calls_this_run"]:
        raise ValueError("Replay made an HTTP call")
    result = {
        "resolution_counts": dict(Counter(row["Resolution"] for row in rows)),
        "candidate_automatic": sum(identity(row) in candidate_keys and row["Review"] == "False" for row in rows),
        "market_review": len(reviews), "training_review": manifest.get("training_review_count", len(_read(folder, "review_queue"))
                                                     if (folder / "review_queue.csv").is_file() else None),
        "failed_checks": Counter(row.get("FailedCheck", "") for row in reviews).most_common(),
        "reasons": dict(Counter(row["Reason"] for row in reviews)),
        "http_calls": 0, "tables": manifest["table_sha256"],
    }
    if baseline:
        before = {identity(row): row for row in _read(baseline, "resolutions")}
        if before.keys() != current.keys():
            raise ValueError("Replay changed the census resolution identity set")
        changed = [key for key, row in before.items() if row["Review"] == "False"
                   and any(row[field] != current[key][field] for field in DECISION)]
        result["previous_automatic_decision_changes"] = changed
        # Early census tables predate FailedCheck; an absent diagnostic is empty.
        result["baseline_failed_check_unavailable"] = sum("FailedCheck" not in row for row in before.values())
        result["previous_automatic_metadata_changes"] = [
            {"identity": key, "before": row["Reason"], "after": current[key]["Reason"],
             "changed_fields": {field: {"before": row.get(field, ""), "after": current[key].get(field, "")}
                                for field in ("Reason", "Evidence", "FailedCheck") if row.get(field, "") != current[key].get(field, "")}}
            for key, row in before.items() if row["Review"] == "False"
            and any(row.get(field, "") != current[key].get(field, "") for field in ("Reason", "Evidence", "FailedCheck"))
        ]
        result["new_automatic"] = sum(row["Review"] == "True" and current[key]["Review"] == "False"
                                      for key, row in before.items())
        coverage = json.loads((baseline / "coverage.json").read_text())
        accessions = {row["AcptNo"] for row in coverage["failures"]
                      if row.get("FailedCheck") == "unsupported_form:11308"
                      or row.get("Reason") == "Unsupported KIND market-action form 11308"}
        blocked = {key for key, row in before.items() if row["Review"] == "True"
                   and any(ref.get("accession") in accessions and ref.get("field") == "KIND notice awaiting review"
                           for ref in json.loads(row["Evidence"]))}
        result["form_11308"] = {
            "baseline_review": len(blocked),
            "became_bonus": sum(current[key]["Resolution"] == "bonus" for key in blocked),
            "remaining_failed_checks": dict(Counter(current[key].get("FailedCheck", "") for key in blocked
                                                     if current[key]["Review"] == "True")),
        }
        if result["previous_automatic_metadata_changes"]:
            raise ValueError("Changed previously automatic metadata")
        if changed:
            raise ValueError(f"Changed {len(changed)} previously automatic decisions")
        if (baseline / "review_queue.csv").is_file():
            training_keys = {(row["Code"], row["Date"]) for row in _read(baseline, "review_queue")}
            coverage, windows, sessions, ledgers, notices, refs = _load_tables(folder, manifest)
            snapshot = ResolutionSnapshot(folder / "manifest.json", manifest, coverage, windows, sessions,
                                          ledgers, {}, notices, refs, "", "")
            queue = sorted((row for row in snapshot.review_rows() if (row["Code"], row["Date"]) in training_keys),
                           key=lambda row: (row["Code"], row["Date"]))
            if len(queue) != result["training_review"]:
                raise ValueError("Training review queue differs from census membership count")
            _write_csv(folder / "review_queue.csv", REVIEW_COLUMNS, queue)
            result["review_queue"] = {"rows": len(queue), "sha256": sha256(folder / "review_queue.csv")}
    atomic_json(folder / "review-summary.json", result)
    return result


def main(argv=None):
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--replay-args", type=Path)
    cli.add_argument("--kind-root", type=Path)
    cli.add_argument("--output", required=True, type=Path)
    cli.add_argument("--baseline", type=Path)
    cli.add_argument("--summarize-only", action="store_true")
    args = cli.parse_args(argv)
    if not args.summarize_only:
        if not args.replay_args or not args.kind_root:
            cli.error("--replay-args and an independent --kind-root are required")
        replay = [*json.loads(args.replay_args.read_text()), "--output", str(args.output),
                  "--kind-root", str(args.kind_root), "--request-budget", "0", "--preview"]
        def no_network(*unused, **kwargs):
            raise AssertionError("Cached action replay attempted a network connection")
        with patch.object(socket.socket, "connect", no_network), patch.object(socket, "create_connection", no_network):
            census(replay)
        atomic_json(args.output / "replay-input.json", {"argv": replay, "source_sha256": sha256(args.replay_args)})
    print(json.dumps(summarize(args.output, args.baseline), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
