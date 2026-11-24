"""Collect local, immutable official share-unit action snapshots for chart research."""

import argparse
import csv
import fcntl
import hashlib
import json
import os
import re
from dataclasses import asdict
from datetime import UTC, date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
from dotenv import dotenv_values
from shared.data.actions import (
    PRICE_POLICY,
    SNAPSHOT_VERSION,
    Security,
    decision_kind,
    implementation_hashes,
    implementation_kind,
    parse_auction,
    parse_decision,
    parse_implementation,
    read_snapshot,
    reconcile,
)
from shared.data.calendar import scheduled_sessions
from shared.data.disclosures import (
    DisclosureError,
    DocumentFormatError,
    OfficialDisclosures,
    chunks,
    put_immutable,
    require,
)
from shared.io import atomic_json, canonical_hash, sha256

DETAILS = {"bonus": "fricDecsn.json", "reduction": "crDecsn.json"}


def document_record(row, refs, **extra):
    return {"accession": row.accession, "published": row.published.isoformat(),
            "publication_precision": "date", "title": row.title, "sources": (row.evidence, *refs), **extra}


def collect_security(client, security, start, end, lookback, through, sessions):
    coverage, documents, pending = [], [], []
    dart, kind = {}, {}
    for first, last in chunks(lookback, through):
        rows, span = client.dart_list(security.corporation, first, last)
        dart.update((row.accession, row) for row in rows)
        coverage.append(span)
        rows, span = client.kind_list(security.issuer_code, first, last)
        kind.update((row.accession, row) for row in rows)
        coverage.append(span)

    if not client.corp_index.get(security.issuer_code):
        require(any(row.stock_code == security.issuer_code for row in dart.values()),
                "Historical DART filing does not verify the selected issuer code")
    else:
        require(client.corp_index[security.issuer_code] == {security.corporation},
                "DART corporation index does not uniquely verify the issuer code")

    relevant = {acc: row for acc, row in dart.items() if decision_kind(row.title)}
    unresolved = [row for row in dart.values() if not decision_kind(row.title)
                  and re.search(r"(?:유상.{0,4}무상|무상.{0,4}유상|주식분할|주식병합|무상증자|감자).*(?:결정|취소|철회)", row.title)]
    pending.extend(f"{row.accession}: unsupported decision title" for row in unresolved)
    detail_rows = {}
    for event, endpoint in DETAILS.items():
        if not any(decision_kind(row.title) == event for row in relevant.values()):
            continue
        for first, last in chunks(lookback, through):
            rows, span = client.dart_details(endpoint, security.corporation, first, last)
            coverage.append(span)
            for row in rows:
                accession = row["rcept_no"]
                if accession in detail_rows and detail_rows[accession][0] != row:
                    pending.append(f"{accession}: structured document differs between query windows")
                detail_rows[accession] = row, span.pages[0]
        for accession in set(detail_rows) - set(relevant):
            message = f"{accession}: structured decision missing from DART list"
            if message not in pending:
                pending.append(message)

    decisions = []
    for accession, row in relevant.items():
        structured = decision_kind(row.title) in DETAILS
        try:
            body, family, refs = client.dart_document(accession, structured=structured)
        except DocumentFormatError as exc:
            documents.append(document_record(row, exc.evidence))
            pending.append(f"{accession}: {exc}")
            continue
        documents.append(document_record(row, refs, family=family))
        if any(decision_kind(title) and linked not in relevant for linked, title in family):
            pending.append(f"{accession}: decision family extends beyond complete list results")
            continue
        valid_family = sorted((linked for linked, title in family if decision_kind(title) == decision_kind(row.title)),
                              key=lambda linked: relevant[linked].published, reverse=True)
        if not valid_family:
            pending.append(f"{accession}: official decision family lacks the selected report type")
            continue
        if len(valid_family) > 1 and relevant[valid_family[0]].published == relevant[valid_family[1]].published:
            pending.append(f"{accession}: same-day official decision revision order needs review")
            continue
        latest = valid_family[0]
        if structured and accession != latest and accession not in detail_rows:
            if re.search(r"취소|철회", relevant[latest].title):
                pending.append(f"{accession}: original structured terms are required to review cancellation")
            continue
        try:
            decisions.append(parse_decision(security, row, body, family, detail_rows.get(accession)))
        except (ValueError, KeyError, ZeroDivisionError) as exc:
            reason = str(exc) if isinstance(exc, DisclosureError) else type(exc).__name__
            pending.append(f"{accession}: {reason}")

    notices, auctions = [], []
    for accession, row in kind.items():
        auction = "자본감소에따른기준가격결정방법안내" in re.sub(r"\s+", "", row.title)
        if not implementation_kind(row.title) and not auction:
            continue
        try:
            body, refs = client.kind_document(row)
        except DocumentFormatError as exc:
            documents.append(document_record(row, exc.evidence))
            pending.append(f"{accession}: {exc}")
            continue
        documents.append(document_record(row, refs))
        try:
            if auction:
                auctions.append(parse_auction(security, row, body))
            else:
                notices.append(parse_implementation(security, row, body))
        except (ValueError, KeyError, ZeroDivisionError) as exc:
            reason = str(exc) if isinstance(exc, DisclosureError) else type(exc).__name__
            pending.append(f"{accession}: {reason}")
    sessions = dict(sessions)
    for notice in notices:
        if notice.kind == "bonus" and start <= notice.ex_date <= end and notice.ex_date in sessions:
            later = sorted({d.allocation for d in decisions if d.allocation and d.allocation > notice.ex_date})
            if not sessions[notice.ex_date] and later:
                calendar = scheduled_sessions(pd.Timestamp(notice.ex_date), pd.Timestamp(later[0]))
                if len(calendar) > 1:
                    sessions[notice.ex_date] = calendar[1].date().isoformat()
    verified, unmatched = reconcile(security, decisions, notices, start, end, sessions, auctions)
    pending.extend(unmatched)
    return coverage, documents, verified, pending


def publish_snapshot(root, run_id, securities, start, end, lookback, through, key, budget, *, session=None):
    root.mkdir(parents=True, exist_ok=True)
    run = root / "runs" / run_id
    run.mkdir(parents=True, exist_ok=True)
    archive = root / "archive"
    checkpoint = run / "status.json"
    with (root / "writer.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise DisclosureError("An official action collector already owns this root") from None
        implementation = implementation_hashes()
        identity = canonical_hash({
            "securities": [asdict(item) for item in securities],
            "start": start.isoformat(), "end": end.isoformat(),
            "lookback": lookback.isoformat(), "through": through.isoformat(),
            "implementation": implementation,
        })
        progress = json.loads(checkpoint.read_text()) if checkpoint.exists() else {
            "identity": identity, "securities": {}, "started_at": datetime.now(UTC).isoformat(),
        }
        require(progress["identity"] == identity, "Run scope or source implementation changed; choose a new run ID")
        if snapshot := progress.get("snapshot"):
            path = root / "snapshots" / f"{snapshot}.json"
            require(sha256(path) == snapshot, "Previously published snapshot changed")
            read_snapshot(path, verify_archive=True)
            return path
        atomic_json(checkpoint, _jsonable(progress))
        calendar = scheduled_sessions(pd.Timestamp(start), pd.Timestamp(end))
        days = [item.date().isoformat() for item in calendar]
        sessions = {item: days[i + 1] if i + 1 < len(days) else None for i, item in enumerate(days)}
        client = OfficialDisclosures(archive, run, key, budget, session=session)
        try:
            client.corp_index, index_source = client.corporations()
        except (ValueError, TypeError, KeyError, OSError) as exc:
            progress["query_error"] = str(exc) if isinstance(exc, DisclosureError) else type(exc).__name__
            atomic_json(checkpoint, progress)
            raise DisclosureError(f"Corporation index query incomplete: {progress['query_error']}") from None
        progress.pop("query_error", None)
        for security in securities:
            identity_key = canonical_hash(asdict(security))
            previous = progress["securities"].get(identity_key)
            if previous and previous["status"] != "query_failed":
                continue
            row = {"security": asdict(security), "start": start.isoformat(), "end": end.isoformat()}
            try:
                coverage, documents, actions, pending = collect_security(
                    client, security, start.isoformat(), end.isoformat(), lookback, through, sessions)
                row.update(status="review_pending" if pending else "covered",
                           coverage=[asdict(item) for item in coverage],
                           documents=documents, actions=[asdict(item) for item in actions], pending=pending)
            except (ValueError, TypeError, KeyError, OSError) as exc:
                row.update(status="query_failed", pending=[
                    str(exc) if isinstance(exc, DisclosureError) else type(exc).__name__])
            progress["securities"][identity_key] = row
            atomic_json(checkpoint, _jsonable(progress))
            if client.remaining == 0 and row["status"] == "query_failed":
                break
        records = [progress["securities"][canonical_hash(asdict(security))]
                   for security in securities if canonical_hash(asdict(security)) in progress["securities"]]
        require(len(records) == len(securities) and all(row["status"] != "query_failed" for row in records),
                f"Official queries incomplete; inspect {checkpoint} and resume")
        frozen = progress.setdefault("frozen_at", datetime.now(UTC).isoformat())
        atomic_json(checkpoint, _jsonable(progress))
        payload = _jsonable({
            "version": SNAPSHOT_VERSION, "price_policy": PRICE_POLICY,
            "implementation_sha256": implementation, "corp_index": asdict(index_source),
            "published_search_start": lookback.isoformat(), "published_search_end": through.isoformat(),
            "collected_from": progress["started_at"], "frozen_at": frozen,
            "securities": records,
        })
        serialized = (json.dumps(payload, sort_keys=True, ensure_ascii=False, indent=2) + "\n").encode()
        digest = hashlib.sha256(serialized).hexdigest()
        path = root / "snapshots" / f"{digest}.json"
        put_immutable(path, serialized)
        progress["snapshot"] = digest
        atomic_json(checkpoint, _jsonable(progress))
        return path


def _jsonable(value):
    from dataclasses import asdict, is_dataclass

    return json.loads(json.dumps(value, default=lambda item: asdict(item) if is_dataclass(item) else str(item)))


def main(argv=None):
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--root", type=Path, required=True)
    cli.add_argument("--run", required=True, help="Reuse to resume; choose a new one to refresh all sources")
    cli.add_argument("--securities", type=Path, required=True, help="CSV of verified KRX security listing identities")
    cli.add_argument("--start", type=date.fromisoformat, required=True, help="First price date")
    cli.add_argument("--end", type=date.fromisoformat, required=True, help="Last price date")
    cli.add_argument("--lookback", type=date.fromisoformat, required=True, help="First publication date to read")
    cli.add_argument("--through", type=date.fromisoformat, required=True, help="Last publication date to read")
    cli.add_argument("--request-budget", type=int, required=True)
    cli.add_argument("--env-file", type=Path)
    args = cli.parse_args(argv)
    try:
        require(re.fullmatch(r"[A-Za-z0-9_-]{1,80}", args.run), "Invalid run ID")
        require(args.lookback <= args.start <= args.end <= args.through <= datetime.now(ZoneInfo("Asia/Seoul")).date(),
                "Invalid price/publication bounds")
        require(args.request_budget > 0, "A positive request budget is required")
        with args.securities.open(encoding="utf-8-sig", newline="") as stream:
            reader = csv.DictReader(stream)
            columns = {"code", "isin", "share_class", "listing", "delisting", "corporation", "issuer_code", "market"}
            require(reader.fieldnames and set(reader.fieldnames) == columns and len(reader.fieldnames) == len(columns),
                    "Security CSV requires code,isin,share_class,listing,delisting,corporation,issuer_code,market")
            securities = [Security(**{**row, "delisting": row["delisting"] or None}) for row in reader]
        require(securities and len({(s.code, s.listing, s.delisting) for s in securities}) == len(securities),
                "Missing or duplicate KRX securities")
        key = os.environ.get("OPEN_DART_API") or os.environ.get("DART_API_KEY")
        if not key and args.env_file:
            config = dotenv_values(args.env_file)
            key = config.get("OPEN_DART_API") or config.get("DART_API_KEY")
        path = publish_snapshot(args.root, args.run, securities, args.start, args.end, args.lookback,
                                args.through, key, args.request_budget)
        print(path)
    except (ValueError, TypeError, KeyError, OSError) as exc:
        cli.exit(1, f"{exc if isinstance(exc, DisclosureError) else type(exc).__name__}\n")


if __name__ == "__main__":
    main()
