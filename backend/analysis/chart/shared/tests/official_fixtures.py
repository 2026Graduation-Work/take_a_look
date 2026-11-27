from dataclasses import asdict
from pathlib import Path

from shared.data.actions import (
    PRICE_POLICY,
    SNAPSHOT_VERSION,
    Action,
    FieldEvidence,
    Security,
    implementation_hashes,
    valid_isin,
)
from shared.data.disclosures import Evidence
from shared.io import atomic_json, sha256

FAKE_EVIDENCE = FieldEvidence("20240103000123", Evidence("a" * 64, "b" * 64), "synthetic test")
NEW_POLICY = {"price_policy": PRICE_POLICY, "official_actions": {"sha256": "a" * 64, "version": SNAPSHOT_VERSION}}


def fake_split(date, old, new, shares=None):
    return Action("synthetic", "fixture", "split", str(date), new, old, str(date), None, shares,
                  FAKE_EVIDENCE, FAKE_EVIDENCE, FAKE_EVIDENCE)


def fake_isin(code):
    return next(isin for i in range(10) if valid_isin(isin := f"KR7{code}00{i}"))


def fixture_snapshot(root, codes, dates, actions=()):
    start, end = dates[0].date().isoformat(), dates[-1].date().isoformat()
    rows = []
    for code in codes:
        security = Security(code, fake_isin(code), "common", start, None, "12345678", code)
        rows.append({
            "security": asdict(security), "start": start, "end": end, "status": "covered",
            "coverage": [{"source": source, "start": start, "end": end, "rows": 0,
                          "pages": [asdict(FAKE_EVIDENCE.source)]}
                         for source in ("OpenDART list", "KIND market actions")],
            "actions": [asdict(action) for action in actions],
        })
    payload = {"version": SNAPSHOT_VERSION, "price_policy": PRICE_POLICY,
               "implementation_sha256": implementation_hashes(), "securities": rows}
    folder = Path(root) / "official_actions"
    staged = folder / "fixture.json"
    atomic_json(staged, payload)
    digest = sha256(staged)
    path = folder / f"{digest}.json"
    staged.replace(path)
    return path


def price_provenance(root, codes, dates):
    path = fixture_snapshot(root, codes, dates)
    return {"price_policy": PRICE_POLICY, "official_actions": {"sha256": sha256(path), "version": SNAPSHOT_VERSION}}
