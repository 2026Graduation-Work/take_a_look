"""Pin a complete Census resolution ledger and its official disclosure archive."""

import argparse
import json
from collections import defaultdict
from pathlib import Path

import pandas as pd
from shared.data.actions import FieldEvidence
from shared.data.disclosures import Evidence, require
from shared.data.kind_market import MarketFiling
from shared.data.market_notices import SecurityKey, match_notice, notice_section_key
from shared.data.market_resolutions import (
    COMBINED_LISTING_FAILURE_FIELD,
    ISSUER_MERGER_REASON,
    STRUCTURAL_REVIEW_REASON,
    NoticeFailure,
    ambiguous_final_documents,
    issuer_merger_boundaries,
    raw_window_fingerprint,
    resolve_events,
)
from shared.data.resolution_snapshot import (
    _eligible,
    _insert,
    _load_tables,
    _scope,
    _security,
    _table_paths,
    read_resolution_snapshot,
    seal_resolution_snapshot,
)
from shared.io import sha256

from .census_actions import (
    _anchor_sources,
    _official_action_snapshots,
    _price_frame,
    _security_master,
    _share_class,
    _windows,
    master_security_aliases,
    spac_observations,
)


def freeze_resolution_snapshot(census_dir, destination, *, krx_days, active_master, delisted_master,
                               action_snapshots=(), evidence_archives=()):
    census_dir, destination, krx_days = map(Path, (census_dir, destination, krx_days))
    manifest_path = census_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_bytes())
    files = _table_paths(census_dir, manifest)
    coverage, windows, sessions, ledgers, _, refs = _load_tables(census_dir, manifest)
    _, _, codes = _scope(manifest)
    sources = manifest["sources"]
    require(sha256(active_master) == sources["active_master_sha256"]
            and sha256(delisted_master) == sources["delisted_master_sha256"]
            and [sha256(path) for path in action_snapshots] == sources["official_action_snapshots"],
            "Census KRX master or Action input bytes differ")
    master = _security_master(active_master, delisted_master)
    raw, hashes = _price_frame(krx_days, sessions, set(codes))
    require(hashes == sources["krx_sessions"], "Census KRX daily input bytes differ")
    securities, expected, aliases, anchors, training, _, _, failures = _windows(raw, master, sessions, {})
    identity_universe = master_security_aliases(master)
    for key, aliases_for_key in aliases.items():
        identity_universe.setdefault(key, set()).update(aliases_for_key)
    del raw
    require(securities.keys() == windows.keys() and not failures,
            "Census listing scope differs from independent KRX input windows")
    for security, window in windows.items():
        bars = securities[security]
        require(raw_window_fingerprint(bars, expected[security]) == window["raw_sha256"],
                f"{security.code}: census raw window fingerprint differs from KRX")
        require(window["spac"]["observations"] == spac_observations(bars, hashes),
                "Pinned SPAC observations differ from KRX")
    names = {}
    for row in master[master.Group.eq("주권") & master.Market.isin(["KOSPI", "KOSDAQ"])].itertuples(index=False):
        if pd.isna(row.ListingDate):
            continue
        try:
            key = SecurityKey(row.Code, row.ISIN, row.ListingDate.date().isoformat(),
                              row.DelistingDate.date().isoformat() if pd.notna(row.DelistingDate) else None,
                              row.Market, _share_class(row.KIND_STKCERT_TP_NM))
        except (ValueError, TypeError):
            continue
        if key in windows:
            _insert(names, key, str(row.Name))
    require(names.keys() == training, "Training metadata differs from independent KRX membership")
    _eligible(coverage, windows, names, codes)
    actions = _official_action_snapshots(action_snapshots)
    anchor_sources = _anchor_sources(securities, anchors)
    combined_listing_failures = defaultdict(lambda: defaultdict(list))
    for failure in coverage["failures"]:
        for target in failure.get("CombinedBonusListing", ()):
            key, day = _security(target), target["Date"]
            require(key in ledgers and any(row.date == day for row in ledgers[key].candidates),
                    "Additional listing failure lacks an affected bonus candidate")
            evidence = tuple(FieldEvidence(failure["AcptNo"], Evidence(**ref), COMBINED_LISTING_FAILURE_FIELD)
                             for ref in failure["Evidence"])
            combined_listing_failures[key][day].append(
                NoticeFailure(evidence, target["FailedCheck"], scope="combined_bonus_listing"))

    def verify_ledger(official, reviews):
        by_security = defaultdict(list)
        ambiguous_finals = ambiguous_final_documents(official)
        sections = {notice_section_key(notice): notice for notice in official}
        links = {tuple(row["Auction"]): tuple(sections[tuple(witness)] for witness in row["Witnesses"])
                 for row in coverage.get("kind_auction_identity_links", [])}
        for notice in official:
            filing = MarketFiling(notice.accession, pd.Timestamp(notice.published).date(), notice.title,
                                  notice.evidence[0], company_id=notice.company_id)
            matched = match_notice(filing, notice.form, notice.facts, notice, notice.evidence[1:],
                                   {notice.security: aliases[notice.security]},
                                   identity_witness=links.get(notice_section_key(notice), ()),
                                   identity_universe={key: names for key, names in identity_universe.items()
                                                      if key.code.startswith(notice.security.code[:5])})
            require(matched.security == notice.security, "Official filing differs from the KRX listing identity")
            by_security[notice.security].append(matched)
        issuer_mergers = issuer_merger_boundaries(
            official, windows, lambda key, day: key in expected and pd.Timestamp(day) in expected[key])
        for key, ledger in ledgers.items():
            replay = resolve_events(key, securities[key], expected[key], by_security[key],
                                    actions=actions[key], coverage_complete=True,
                                    unparsed_dates=combined_listing_failures[key],
                                    transfer_anchor=anchors.get(key), transfer_source=anchor_sources.get(key),
                                    issuer_mergers=issuer_mergers.get(key), structural_reviews=reviews.get(key, ()),
                                    ambiguous_finals=ambiguous_finals)
            require(set(ledger.candidates) == set(replay.candidates),
                    f"{key.code}: census candidates differ from KRX replay")
            resolutions = {row.date: row for row in replay.resolutions}
            have = {row.date for row in ledger.resolutions}
            require(all(row.date in have for row in replay.resolutions if not row.review or row.reason == STRUCTURAL_REVIEW_REASON),
                    f"{key.code}: census omits a verified resolution")
            for row in ledger.resolutions:
                audited = resolutions.get(row.date)
                if row.review and row.reason != STRUCTURAL_REVIEW_REASON:
                    require(not audited or audited.reason != ISSUER_MERGER_REASON,
                            f"{key.code} {row.date}: census replaces a verified issuer merger with review")
                    continue
                require(audited and (row.kind, row.price_factor, row.volume_factor, row.reason, row.review) ==
                        (audited.kind, audited.price_factor, audited.volume_factor, audited.reason, audited.review)
                        and set(row.evidence) == set(audited.evidence),
                        f"{key.code} {row.date}: resolution differs from the official source replay")

    return seal_resolution_snapshot(census_dir, destination, manifest, files, names, refs,
                                    action_snapshots, evidence_archives, verify_ledger=verify_ledger)


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    for field in ("census-dir", "destination", "krx-days", "active-master", "delisted-master"):
        cli.add_argument(f"--{field}", required=True, type=Path)
    cli.add_argument("--action-snapshot", action="append", type=Path, default=[])
    cli.add_argument("--evidence-archive", action="append", type=Path, default=[])
    args = cli.parse_args()
    path = freeze_resolution_snapshot(args.census_dir, args.destination, krx_days=args.krx_days,
                                      active_master=args.active_master, delisted_master=args.delisted_master,
                                      action_snapshots=args.action_snapshot, evidence_archives=args.evidence_archive)
    snapshot = read_resolution_snapshot(path)
    print(json.dumps({"snapshot": str(path), **snapshot.provenance}, indent=2))


if __name__ == "__main__":
    main()
