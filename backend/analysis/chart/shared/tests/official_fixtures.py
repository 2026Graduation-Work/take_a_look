from collections import Counter
from dataclasses import asdict
from datetime import timedelta
from pathlib import Path

import pandas as pd
from shared.data.actions import Action, FieldEvidence, valid_isin
from shared.data.disclosures import Evidence
from shared.data.market_notices import SecurityKey
from shared.data.market_resolutions import (
    Resolution,
    ResolvedEvent,
    observe_candidates,
    raw_window_fingerprint,
)
from shared.data.resolution_snapshot import (
    CANDIDATE_COLUMNS,
    NOTICE_COLUMNS,
    PRICE_POLICY,
    RESOLUTION_COLUMNS,
    SNAPSHOT_VERSION,
    read_resolution_snapshot,
    seal_resolution_snapshot,
)
from shared.io import atomic_json, canonical_hash, sha256

FAKE_EVIDENCE = FieldEvidence("20240103000123", Evidence("a" * 64, "b" * 64), "synthetic test")
NEW_POLICY = {"price_policy": PRICE_POLICY, "official_actions": {
    "sha256": "a" * 64, "version": SNAPSHOT_VERSION, "producer_sha256": "b" * 64,
    "segmentation_sha256": "c" * 64, "evidence_sha256": "d" * 64,
}}


def fake_split(date, old, new, shares=None):
    return Action("synthetic", "fixture", "split", str(date), new, old, str(date), None, shares,
                  FAKE_EVIDENCE, FAKE_EVIDENCE, FAKE_EVIDENCE)


def fake_isin(code):
    return next(isin for i in range(10) if valid_isin(isin := f"KR7{code}00{i}"))


def fixture_snapshot(root, codes, dates, actions=(), *, raw=None, keys=None, events=(), spac_codes=()):
    from experiments.dataset.census_actions import (
        _candidate_columns,
        _resolution_columns,
        _security_columns,
        _write_csv,
    )

    root = Path(root)
    start, end = dates[0].date(), dates[-1].date()
    left, right = start - timedelta(days=7), end + timedelta(days=3)
    source = root / "synthetic-census"
    archive = source / "archive"
    for kind in ("objects", "receipts"):
        (archive / kind).mkdir(parents=True, exist_ok=True)
    body = source / "fixture.txt"
    body.write_text("전체 <em>0</em>건 : <strong>1</strong>/1 조회된 결과값이 없습니다.")
    body_hash = sha256(body)
    (archive / "objects" / body_hash).write_bytes(body.read_bytes())
    proofs = {}
    for code in codes:
        receipt = source / f"{code}-receipt.json"
        atomic_json(receipt, {"sha256": body_hash, "bytes": len(body.read_bytes()), "charset": "utf-8",
                             "request": {"url": "https://kind.krx.co.kr/disclosure/details.do",
                                 "form": {"method": "searchDetailsSub", "searchCorpName": code,
                                          "repIsuSrtCd": f"A{code}", "fromDate": str(left),
                                          "toDate": str(right), "pageIndex": "1", "currentPageSize": "100"}}})
        proofs[code] = Evidence(body_hash, sha256(receipt))
        (archive / "receipts" / f"{proofs[code].receipt}.json").write_bytes(receipt.read_bytes())
    sessions = {str(day.date()): "a" * 64 for day in dates}
    windows, candidates, resolutions, names = [], [], [], {}
    if raw is None:
        raw = pd.DataFrame({"Date": dates, "RawOpen": 100, "RawHigh": 102, "RawLow": 98, "RawClose": 100,
                            "RawChange": 0, "RawVolume": 1_000, "Amount": 100_000, "ListedShares": 100_000})
    keys = keys or [SecurityKey(code, fake_isin(code), str(start), None, "KOSPI", "common") for code in codes]
    for key in keys:
        field = FieldEvidence(FAKE_EVIDENCE.accession, proofs[key.code], "synthetic test")
        frame = raw.loc[raw.Date.dt.strftime("%Y-%m-%d").map(key.active)]
        days = pd.DatetimeIndex(frame.Date)
        resolved = {date: (kind, price, volume) for date, kind, price, volume in events}
        resolved.update({item.ex_date: (Resolution.UNIT_CHANGE, 1 / item.factor, item.factor) for item in actions})
        observed = observe_candidates(key, frame, days)
        names[key] = "Synthetic"
        for candidate in observed:
            candidates.append(candidate)
            if candidate.date not in resolved:
                resolutions.append(ResolvedEvent(key, candidate.date, Resolution.SEGMENT_BREAK,
                                                 "completed_search_without_official_proof", review=True))
        for day, (kind, price, volume) in resolved.items():
            resolutions.append(ResolvedEvent(key, day, kind, "synthetic", (field,), price, volume))
        merger = next((day for day, row in resolved.items() if row[0] == Resolution.SPAC_PREMERGER), None)
        spac = ([{"session": str(days[0].date()), "field": "SECT_TP_NM", "value": "SPAC",
                  "sha256": sessions[str(days[0].date())]}] if key.code in spac_codes else [])
        windows.append({**_security_columns(key), "first_session": str(days[0].date()),
                        "last_session": str(days[-1].date()), "expected_sessions": len(days),
                        "price_rows": len(days), "raw_sha256": raw_window_fingerprint(frame, days),
                        "publication_start": str(days[0].date() - timedelta(days=7)),
                        "publication_end": str(days[-1].date() + timedelta(days=3)),
                        "publication_complete": True, "structural_documents_incomplete": [],
                        "unattributed_structural_documents_present": False, "required_dates_incomplete": [],
                        "complete": True, "spac": {"merger_listing": merger, "observations": spac}})
    observations = {(row.security, row.date): row for row in candidates}
    indexed = {(row.security, row.date): row for row in resolutions}
    counts = Counter(row.kind for row in resolutions)
    papers = {"candidates.csv": (CANDIDATE_COLUMNS, map(_candidate_columns, candidates)),
              "notices.csv": (NOTICE_COLUMNS, []),
              "resolutions.csv": (RESOLUTION_COLUMNS, (_resolution_columns(row, observations, sessions)
                                                       for row in resolutions))}
    files = {name: source / name for name in [*papers, "coverage.json"]}
    for name, (columns, rows) in papers.items():
        _write_csv(files[name], columns, rows)
    atomic_json(files["coverage.json"], {"windows": windows, "unattributed_structural_documents": [],
                "unassigned_market_observations": [], "failures": [], "daily": [], "archived_market_actions": {},
                "missing_daily_dates": [str(day.date()) for day in pd.date_range(left, right)],
                "company": {code: [{"start": str(left), "end": str(right), "source": "KIND company disclosure list",
                                    "rows": 0, "pages": [asdict(proofs[code])]}] for code in codes}})
    manifest = {"version": 1, "training_policy_active": False,
                "table_sha256": {path.stem: sha256(path) for path in files.values()},
                "implementation_sha256": {"synthetic": "f" * 64},
                "scope": {"start": str(start), "end": str(end), "codes": [], "sample_sha256": None,
                          "published_start": str(left), "published_end": str(right)},
                "sources": {"krx_sessions": sessions, "krx_sha256": canonical_hash(sessions),
                            "official_action_snapshots": []},
                "security_intervals": len(windows), "market_candidates": len(candidates),
                "candidates_with_resolution": len(observations.keys() & indexed.keys()),
                "resolutions_without_price_observation": len(indexed.keys() - observations.keys()),
                "market_resolution_counts": {kind.value: counts[kind] for kind in Resolution}}
    atomic_json(source / "manifest.json", manifest)
    return seal_resolution_snapshot(source, root / "official_actions", manifest, files, names,
                                    set(proofs.values()), [], [archive])


def price_provenance(root, codes, dates):
    snapshot = read_resolution_snapshot(fixture_snapshot(root, codes, dates))
    return {"price_policy": PRICE_POLICY, "official_actions": snapshot.provenance}


def listing_segment(code, listing):
    from shared.data.resolution_snapshot import segment_id

    key = SecurityKey(code, fake_isin(code), listing, None, "KOSPI", "common")
    return segment_id(key, listing)
