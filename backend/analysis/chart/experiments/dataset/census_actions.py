"""Build the auditable market-action ledger from cached KRX prices and official disclosures."""

import argparse
import csv
import fcntl
import json
import re
import tempfile
from collections import Counter, defaultdict
from dataclasses import asdict
from datetime import date, datetime, timedelta
from fractions import Fraction
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
from shared.data.actions import FieldEvidence, action_from_record, read_snapshot
from shared.data.calendar import scheduled_sessions
from shared.data.disclosures import DisclosureError, DocumentFormatError, require
from shared.data.events import observation_mask
from shared.data.kind_market import KindMarket, KindUnavailable
from shared.data.market_notices import (
    SecurityKey,
    kind_topic,
    match_notice,
    normal_company,
    parse_notice,
)
from shared.data.market_resolutions import (
    Resolution,
    observe_candidates,
    raw_window_fingerprint,
    resolve_events,
    structural_notice,
)
from shared.data.resolution_archive import notice_facts_columns
from shared.data.resolution_snapshot import (
    CANDIDATE_COLUMNS,
    CONFIRMATION_COLUMNS,
    NOTICE_COLUMNS,
    RESOLUTION_COLUMNS,
    SECURITY_COLUMNS,
    _csv,
    _day,
    _security,
    kind_document_url,
)
from shared.data.validation import KRX_RAW_COLUMNS
from shared.io import atomic_json, canonical_hash, sha256

POLICY_VERSION = 1
MARKETS = {"KOSPI", "KOSDAQ", "KONEX"}
PRICES = ["Code", *KRX_RAW_COLUMNS, "ISU_ABBRV", "MKT_NM", "SECT_TP_NM"]


def calendar_days(start, end):
    return (start + timedelta(days=offset) for offset in range((end - start).days + 1))


def _price_frame(path, sessions, codes):
    frames, receipts = [], {}
    for day in sessions:
        file = path / f"{day:%Y-%m-%d}.parquet"
        require(file.is_file(), f"Missing preserved KRX session: {file.name}")
        rows = pd.read_parquet(file, columns=PRICES)
        require(not rows.empty and rows.Date.eq(day).all() and not rows.Code.duplicated().any(),
                f"Invalid KRX session: {file.name}")
        require(rows.Code.str.fullmatch(r"[0-9A-Z]{6}").all(), f"Invalid KRX short code: {file.name}")
        receipts[day.date().isoformat()] = sha256(file)
        if codes:
            rows = rows[rows.Code.isin(codes)]
        for col in ("Code", "ISU_ABBRV", "MKT_NM", "SECT_TP_NM"):
            rows[col] = rows[col].astype("string[pyarrow]")
        frames.append(rows)
    raw = pd.concat(frames, ignore_index=True).rename(columns={"MKT_NM": "Market"})
    raw["Market"] = raw.Market.replace({"KOSDAQ GLOBAL": "KOSDAQ"})
    return raw, receipts


def _security_master(active_path, delisted_path):
    active = pd.read_parquet(active_path).rename(columns={
        "ISU_SRT_CD": "Code", "ISU_CD": "ISIN", "ISU_NM": "Name", "ISU_ABBRV": "ShortName",
        "MKT_TP_NM": "Market", "SECUGRP_NM": "Group", "LIST_DD": "ListingDate",
    }).assign(DelistingDate=pd.NaT)
    delisted = pd.read_parquet(delisted_path).rename(columns={"Symbol": "Code", "SecuGroup": "Group"})
    fields = {"Code", "ISIN", "Name", "Market", "Group", "ListingDate", "DelistingDate", "KIND_STKCERT_TP_NM"}
    require(not (fields - set(active) or fields - set(delisted)), "KRX masters lack official security or listing fields")
    master = pd.concat([active, delisted], ignore_index=True)
    master["Market"] = master.Market.replace({"KOSDAQ GLOBAL": "KOSDAQ"})
    master["ListingDate"] = pd.to_datetime(master.ListingDate, errors="raise")
    master["DelistingDate"] = pd.to_datetime(master.DelistingDate, errors="raise")
    return master


def _share_class(label):
    if label == "보통주":
        return "common"
    if "우선주" in label or label in {"종류주권", "종류주식"}:
        return "preferred"
    raise DisclosureError(f"Unsupported KRX share class: {label}")


def _windows(raw, master, sessions, market_observed):
    securities, expected_days, aliases, anchors, failures = {}, {}, {}, {}, []
    other_groups, listing_starts = {}, set()
    training_intervals = set()
    by_code = master.groupby("Code").indices
    for code, bars in raw.groupby("Code", sort=True):
        if code not in by_code:
            failures.append({"Code": code, "Stage": "identity", "Reason": "KRX masters lack this observed code"})
            continue
        intervals = master.iloc[by_code[code]]
        intervals = intervals[(intervals.ListingDate <= sessions[-1]) &
                              (intervals.DelistingDate.isna() | (intervals.DelistingDate > sessions[0]))]
        claimed = pd.Series(False, index=bars.index)
        for interval in intervals.itertuples(index=False):
            dates = bars.Date >= interval.ListingDate
            if pd.notna(interval.DelistingDate):
                dates &= bars.Date < interval.DelistingDate
            exact_market = bars.Market.eq(interval.Market)
            same_market = intervals[intervals.Market.eq(interval.Market)]
            other_market = intervals[~intervals.Market.eq(interval.Market)]
            if len(same_market) > 1 or not other_market.empty:
                dates &= exact_market
            match = bars.loc[dates]
            if match.empty:
                continue
            if interval.Group not in {"주권", "외국주권", "주식예탁증권", "부동산투자회사"}:
                other_groups.update({(code, day.date().isoformat()): interval.Group for day in match.Date
                                     if (code, day.date().isoformat()) in market_observed})
                claimed |= dates
                continue
            try:
                require(interval.Market in MARKETS and not (claimed & dates).any(),
                        "Ambiguous KRX listing intervals")
                key = SecurityKey(code, interval.ISIN, interval.ListingDate.date().isoformat(),
                                  interval.DelistingDate.date().isoformat() if pd.notna(interval.DelistingDate) else None,
                                  interval.Market, _share_class(interval.KIND_STKCERT_TP_NM))
                require(key not in securities, "Duplicate official KRX security key")
                expected = sessions[sessions >= interval.ListingDate]
                if pd.notna(interval.DelistingDate):
                    expected = expected[expected < interval.DelistingDate]
                sorted_bars = match.sort_values("Date").reset_index(drop=True)
                claimed |= dates
                expected_days[key] = expected
                securities[key] = sorted_bars
                aliases[key] = {normal_company(str(name)) for name in (
                    *match.ISU_ABBRV.dropna().unique(), interval.Name, interval.ShortName) if pd.notna(name)}
                first_at = sessions.get_loc(expected[0])
                if first_at and interval.ListingDate == expected[0]:
                    listing_starts.add((code, key.listing))
                    previous = bars[bars.Date.eq(sessions[first_at - 1]) & bars.Market.ne(key.market)]
                    if len(previous) == 1:
                        anchors[key] = previous
                if interval.Group == "주권" and key.market in {"KOSPI", "KOSDAQ"}:
                    training_intervals.add(key)
            except (ValueError, TypeError) as exc:
                failures.append({"Code": code, "Stage": "identity", "Reason": str(exc)})
        if (~claimed).any():
            failures.append({"Code": code, "Stage": "identity", "Reason": "Some KRX bars lack a unique listing interval",
                             "Rows": int((~claimed).sum())})
    return securities, expected_days, aliases, anchors, training_intervals, other_groups, listing_starts, failures


def _anchor_sources(securities, anchors):
    ending = defaultdict(list)
    for key in securities:
        if key.delisting:
            ending[key.code, key.delisting, key.market].append(key)
    sources = {}
    for key, anchor in anchors.items():
        found = ending[key.code, key.listing, anchor.Market.iloc[0]]
        if len(found) == 1 and found[0].active(anchor.Date.iloc[0].date().isoformat()):
            sources[key] = found[0]
    return sources


def _candidate_range(candidate):
    return (date.fromisoformat(candidate.prev_date) - timedelta(days=7),
            date.fromisoformat(candidate.date) + timedelta(days=3))


def _in_scope(filing, candidate):
    start, end = _candidate_range(candidate)
    return start <= filing.published <= end


def _kind_inventory(client, start, end, company_cache, codes, registered=frozenset()):
    daily, company, targeted, failures, rows = {}, defaultdict(list), defaultdict(list), [], {}
    for day in calendar_days(start, end):
        try:
            filings, span = client.day(day)
            daily[day] = span
            for filing in filings:
                if kind_topic(filing) or filing.accession in registered:
                    rows.setdefault(filing.accession, filing)
        except (ValueError, OSError) as exc:
            failures.append({"Date": str(day), "Stage": "kind_daily", "Reason": str(exc)})
    if company_cache:
        for cache in sorted(company_cache.glob("*_p1.html")):
            found = re.fullmatch(r"([0-9A-Z]{6})_(\d{4}-\d\d-\d\d)_(\d{4}-\d\d-\d\d)_p1.html", cache.name)
            if not found or codes and found[1] not in codes:
                continue
            code, lo, hi = found[1], date.fromisoformat(found[2]), date.fromisoformat(found[3])
            if lo > end or hi < start:
                continue
            try:
                filings, span = client.cached_company(code, lo, hi)
                company[code].append(span)
                for filing in filings:
                    if start <= filing.published <= end and (kind_topic(filing) or filing.accession in registered):
                        rows.setdefault(filing.accession, filing)
            except (ValueError, OSError) as exc:
                failures.append({"Code": code, "Stage": "kind_company", "Reason": str(exc)})
    for code, filings, span in client.archived_market_lists(start, end, codes):
        targeted[code].append(span)
        for filing in filings:
            if start <= filing.published <= end and (kind_topic(filing) or filing.accession in registered):
                rows.setdefault(filing.accession, filing)
    return daily, company, targeted, tuple(rows.values()), failures


def _collect_notices(client, filings, aliases, candidates, *, anchors, spac_keys, bounded,
                     unresolved_issuers=frozenset(), registered=frozenset(), daily=None, expected_days=None):
    by_name, by_code, by_company = defaultdict(set), defaultdict(set), defaultdict(set)
    for key, names in aliases.items():
        for name in names:
            by_name[name].add(key)
        by_code[key.code].add(key)
        by_company[key.code[:5]].add(key)
    parsed, blocked, unparsed, failures = defaultdict(list), defaultdict(set), defaultdict(lambda: defaultdict(list)), []
    structural_gaps, unattributed_structure, nonstock = defaultdict(set), set(), []
    selected, fetched, verified, families = set(), set(), {}, []

    def bind(filing, form, body, acquired, issuer, keys):
        sections = parse_notice(filing, form, body)
        if not sections:
            require(form == "68155" and body.final, "KIND notice lacks verified listing sections")
            nonstock.append({"AcptNo": filing.accession, "DocNo": body.document_no, "FormId": form,
                             "Evidence": [asdict(ref) for ref in (filing.evidence, *acquired)]})
        matched = []
        for facts in sections:
            if facts.code:
                possible = by_code[facts.code] & keys if issuer else by_code[facts.code]
            else:
                possible = keys if issuer else keys | by_name[normal_company(facts.company)]
            if not any(key.active(facts.effective) and (
                (facts.share_label in {"보통주", "보통주식"}) == (key.share_class == "common")
            ) for key in possible):
                continue
            notice = match_notice(filing, form, facts, body, acquired, {key: aliases[key] for key in possible})
            parsed[notice.security].append(notice)
            matched.append(notice)
        verified[filing.accession] = matched

    ordered = sorted(filings, key=lambda row: (kind_topic(row) == "terms", row.published, row.accession))
    for filing in ordered:
        if filing.accession in selected:
            continue
        topic = kind_topic(filing)
        if topic is None and filing.accession not in registered:
            continue
        issuer = (filing.company_id or filing.stock_code)[:5]
        keys = by_company[issuer] if issuer else by_name[normal_company(filing.company)]
        if not keys:
            if topic == "structural" and not bounded and (not issuer or issuer in unresolved_issuers):
                unattributed_structure.add(filing.accession)
                failures.append({"AcptNo": filing.accession, "Date": str(filing.published), "Stage": "structural_identity",
                                 "Topic": topic, "Reason": "No verified security matches the KIND list row",
                                 "Evidence": [asdict(filing.evidence)]})
            continue
        affected = [(key, candidate) for key in keys for candidate in candidates[key]
                    if _in_scope(filing, candidate)]
        structural = (topic == "structural" or topic in {"transfer", "new_listing"} and bool(keys & anchors.keys())
                      or topic == "rename" and bool(keys & spac_keys))
        if topic == "terms":
            term_type = "주식배당" if "주식배당" in filing.title else "무상증자"
            affected = [(key, candidate) for key in keys for candidate in candidates[key]
                        if abs((date.fromisoformat(candidate.date) - filing.published).days) <= 120
                        and any(notice.final and notice.facts.kind == "ex_price" and notice.facts.effective == candidate.date
                                and term_type in notice.facts.reason for notice in parsed[key])]
        if not affected and not structural and filing.accession not in registered:
            continue
        selected.add(filing.accession)
        refs = (filing.evidence,)
        try:
            form, body, acquired = client.document(filing)
            refs += acquired
            fetched.add(filing.accession)
            if body.final:
                bind(filing, form, body, acquired, issuer, keys)
                continue
            referral = client.final_referral(filing, body, acquired)
            accession = referral.route.accession
            route_day = date.fromisoformat(f"{accession[:4]}-{accession[4:6]}-{accession[6:8]}")
            hints = {route_day, *(row.published for row in ordered if row.accession == accession)}
            matches = [target for day in sorted(hints) if (span := (daily or {}).get(day))
                       and (target := client.dated_filing(span, accession))]
            require(len(matches) == 1, "KIND final document is absent or ambiguous in verified daily lists")
            target, = matches
            require(issuer and (target.company_id or target.stock_code)[:5] == issuer,
                    "KIND final document identifies another issuer")
            require(accession not in selected or accession in verified, "KIND final document was not verified when selected")
            selected.add(accession)
            target_form, target_body, target_refs = client.document(target, expected=referral)
            fetched.add(accession)
            if accession not in verified:
                bind(target, target_form, target_body, target_refs, issuer, keys)
            rows = [row for row in verified[accession] if row.security in keys and row.document_no == target_body.document_no
                    and row.evidence[1:] == target_refs]
            require(rows, "KIND final document identifies no affected stock")
            closed = {row.security for row in rows if structural and structural_notice(row)
                      and (expected_days is None or pd.Timestamp(row.facts.effective) in expected_days[row.security])}
            require(not structural or closed, "KIND final document does not confirm an affected structural event")
            for key in keys - closed if structural else ():
                structural_gaps[key].add(filing.accession)
            families.append({"AcptNo": filing.accession, "DocNo": body.document_no, "FinalAcptNo": accession,
                             "FinalDocNo": target_body.document_no, "FormId": target_form,
                             "ClosedWindows": [_security_columns(key) for key in sorted(closed, key=str)],
                             "Evidence": [asdict(ref) for ref in (filing.evidence, acquired[0], referral.evidence,
                                                                  target.evidence, *target_refs)]})
        except (ValueError, OSError) as exc:
            stage = "kind_document" if isinstance(exc, (DocumentFormatError, KindUnavailable)) or len(refs) == 1 else "kind_notice"
            if isinstance(exc, DocumentFormatError):
                refs += exc.evidence
            failures.append({"Code": filing.stock_code or None, "AcptNo": filing.accession, "Date": str(filing.published),
                             "Stage": stage, "Topic": topic, "Reason": str(exc),
                             "Evidence": [asdict(ref) for ref in refs]})
            if structural:
                for key in keys:
                    structural_gaps[key].add(filing.accession)
            for key, candidate in affected:
                if stage == "kind_document":
                    blocked[key].add(candidate.date)
                else:
                    unparsed[key][candidate.date].extend(FieldEvidence(filing.accession, ref, "KIND notice awaiting review")
                                                        for ref in refs)
    return parsed, blocked, unparsed, structural_gaps, unattributed_structure, failures, nonstock, families, len(selected), len(fetched)


def _official_action_snapshots(paths):
    actions = defaultdict(list)
    for path in paths:
        data = read_snapshot(path, verify_archive=True)
        require(path.stem == sha256(path), "Official snapshot filename does not match its hash")
        for item in data["securities"]:
            raw = item["security"]
            key = SecurityKey(*(raw[field] for field in ("code", "isin", "listing", "delisting", "market", "share_class")))
            for action in map(action_from_record, item["actions"]):
                if action not in actions[key]:
                    actions[key].append(action)
    return actions


def _covered(candidate, daily, spans):
    start, end = _candidate_range(candidate)
    return all(day in daily for day in calendar_days(start, end)) or any(
        span.start <= start <= end <= span.end for span in spans)


def spac_observations(bars, prices):
    spac_bars = bars[bars.SECT_TP_NM.str.contains(r"SPAC|기업인수목적|스팩", case=False, regex=True, na=False)]
    spac_receipts = []
    if not spac_bars.empty:
        for at in dict.fromkeys((0, len(spac_bars) - 1)):
            row = spac_bars.iloc[at]
            day = row.Date.date().isoformat()
            spac_receipts.append({"session": day, "field": "SECT_TP_NM", "value": row.SECT_TP_NM,
                                  "sha256": prices[day]})
    return spac_receipts


def _window_coverage(key, bars, expected, prices, daily, spans, structural_gaps, raw_sha256, ledger, *, sampled,
                     unattributed_structure):
    start, end = expected[0].date(), expected[-1].date()
    publish_start, publish_end = start - timedelta(days=7), end + timedelta(days=3)
    list_complete = all(day in daily or any(span.start <= day <= span.end for span in spans)
                        for day in calendar_days(publish_start, publish_end))
    merger = next((row.date for row in ledger.resolutions if row.kind == Resolution.SPAC_PREMERGER), None) if ledger else None
    return {**_security_columns(key), "first_session": str(start), "last_session": str(end),
            "expected_sessions": len(expected), "price_rows": len(bars), "raw_sha256": raw_sha256,
            "publication_start": str(publish_start), "publication_end": str(publish_end),
            "publication_complete": list_complete,
            "structural_documents_incomplete": sorted(structural_gaps),
            "unattributed_structural_documents_present": unattributed_structure,
            "required_dates_incomplete": list(ledger.incomplete) if ledger else [],
            "complete": bool(not sampled and raw_sha256 and ledger and list_complete and not structural_gaps
                             and not unattributed_structure and not ledger.incomplete),
            "spac": {"observations": spac_observations(bars, prices), "merger_listing": merger}}


def _security_columns(key):
    return dict(zip(SECURITY_COLUMNS, (key.code, key.isin, key.listing, key.delisting, key.market, key.share_class)))


def _candidate_columns(candidate):
    return {**_security_columns(candidate.security), "Date": candidate.date, "PrevDate": candidate.prev_date,
            "PrevClose": candidate.prev_close, "BasePrice": candidate.base_price, "SharesBefore": candidate.shares_before,
            "SharesAfter": candidate.shares_after, "Paused": candidate.paused}


def _notice_columns(notice):
    return {**_security_columns(notice.security), "AcptNo": notice.accession, "FormId": notice.form,
            "Published": notice.published, "Title": notice.title, **notice_facts_columns(notice.facts),
            "Sha256": notice.evidence[-1].sha256, "Evidence": json.dumps([asdict(ref) for ref in notice.evidence]),
            "DocNo": notice.document_no, "Family": json.dumps(notice.family), "Final": notice.final}


def _resolution_columns(resolution, observations, price_hashes):
    evidence = [asdict(ref) for ref in resolution.evidence]
    dates = {resolution.date}
    if candidate := observations.get((resolution.security, resolution.date)):
        dates.add(candidate.prev_date)
    evidence.extend({"source": "KRX raw", "session": day, "sha256": price_hashes[day]} for day in sorted(dates))
    if resolution.kind == Resolution.TICK_ROUNDING:
        evidence.append({"source": "KRX tick table", "market": resolution.security.market,
                         "effective_from": "2023-01-25" if resolution.date >= "2023-01-25" else None})
    return {**_security_columns(resolution.security), "Date": resolution.date, "Resolution": resolution.kind,
            "PriceFactor": resolution.price_factor, "VolumeFactor": resolution.volume_factor,
            "Evidence": json.dumps(evidence),
            "Reason": resolution.reason, "Review": resolution.review}


def _write_csv(path, columns, rows):
    with tempfile.TemporaryDirectory(dir=path.parent) as tmp:
        output = Path(tmp) / path.name
        with output.open("w", encoding="utf-8", newline="") as stream:
            writer = csv.DictWriter(stream, columns)
            writer.writeheader()
            writer.writerows(rows)
        output.replace(path)


def _implementation_hashes():
    chart = Path(__file__).resolve().parents[2]
    return {name: sha256(chart / name) for name in (
        "experiments/dataset/census_actions.py", "shared/data/actions.py", "shared/data/events.py",
        "shared/data/disclosures.py", "shared/data/kind_market.py", "shared/data/market_notices.py",
        "shared/data/market_resolutions.py", "shared/data/calendar.py", "shared/data/validation.py",
        "shared/data/resolution_snapshot.py", "shared/data/resolution_archive.py",
    )}


def read_review_confirmations(path):
    if path is None:
        return {}
    rows = {}
    for row in _csv(path, CONFIRMATION_COLUMNS):
        key = (_security(row), _day(row["Date"]))
        accession = row["OfficialURL"].rsplit("=", 1)[-1]
        require(key not in rows and re.fullmatch(r"[0-9]{14}", accession)
                and row["OfficialURL"] == kind_document_url(accession)
                and re.fullmatch(r"[0-9]{5}", row["FormId"])
                and int(row["Section"]) > 0 and Fraction(row["Ratio"]) > 0,
                "Invalid or duplicate official review confirmation")
        rows[key] = (accession, row)
    require(rows, "Empty official review confirmations")
    return rows


def verify_review_confirmations(confirmations, notices, resolutions, candidates):
    indexed = {(row.security, row.date): row for row in resolutions}
    approved = []
    for key, (accession, entry) in confirmations.items():
        security, day = key
        resolution = indexed.get(key)
        require(key in candidates and resolution is not None and resolution.volume_factor is not None,
                f"{security.code} {day}: official review confirmation did not resolve an observed candidate")
        matching = [notice for notice in notices[security] if notice.accession == accession
                    and (notice.form, notice.facts.section) == (entry["FormId"], int(entry["Section"]))
                    and notice.final]
        field = f"KIND {entry['FormId']}/{entry['Section']}"
        require(len(matching) == 1 and any(
            ref.accession == accession and ref.field == field and ref.source == matching[0].evidence[-1]
            for ref in resolution.evidence
        ), f"{security.code} {day}: confirmed official section is not part of the resolved event")
        expected = {
            Resolution.UNIT_CHANGE: resolution.volume_factor,
            Resolution.BONUS: resolution.volume_factor - 1,
            Resolution.RIGHTS: resolution.price_factor,
            Resolution.REFERENCE_RESET: Fraction(1),
        }.get(resolution.kind)
        require(expected is not None and Fraction(entry["Ratio"]) == expected,
                f"{security.code} {day}: confirmed ratio differs from the verified resolution")
        approved.append(entry)
    return approved


def build_census(args, client):
    implementation = _implementation_hashes()
    registration = getattr(args, "review_confirmations", None)
    require(not registration or not args.sample, "Review confirmations require an unsampled census")
    registration_hash = sha256(registration) if registration else None
    confirmations = read_review_confirmations(registration)
    registered = {accession for accession, _ in confirmations.values()}
    sessions = scheduled_sessions(pd.Timestamp(args.start), pd.Timestamp(args.end))
    require(len(sessions), "No KRX sessions in requested range")
    sample = set()
    if args.sample:
        with args.sample.open(encoding="utf-8-sig", newline="") as stream:
            sample = {(row["Code"], date.fromisoformat(row["Date"]).isoformat()) for row in csv.DictReader(stream)}
        require(sample, "Empty candidate sample")
    codes = set(args.code) | {code for code, _ in sample}
    raw, prices = _price_frame(args.krx_days, sessions, codes)
    master = _security_master(args.active_master, args.delisted_master)
    previous = raw.groupby("Code", sort=False)[["RawClose", "RawVolume", "RawOpen", "RawHigh", "RawLow", "ListedShares"]].shift()
    baseline_mask = observation_mask(raw, raw.RawClose - raw.RawChange, previous)
    previous_dates = raw.groupby("Code", sort=False).Date.shift().loc[baseline_mask]
    market_observed = {(row.Code, row.Date.date().isoformat()): previous_dates.at[row.Index]
                       for row in raw.loc[baseline_mask, ["Code", "Date"]].itertuples()}
    del previous
    if sample:
        market_observed = {key: value for key, value in market_observed.items() if key in sample}
    windows = _windows(raw, master, sessions, market_observed)
    securities, expected_days, aliases, anchors, training, other_groups, listing_starts, failures = windows
    anchor_sources = _anchor_sources(securities, anchors)
    raw_count = len(raw)
    raw_codes = raw.Code.nunique()
    failures.extend({"Code": code, "Stage": "identity", "Reason": "No preserved KRX prices in this scope"}
                    for code in sorted(codes - set(raw.Code.unique())))
    del raw, master
    candidates = defaultdict(tuple)
    fingerprints = {}
    for key, bars in securities.items():
        try:
            fingerprints[key] = raw_window_fingerprint(bars, expected_days[key])
            if key in anchor_sources:
                prior = anchors[key]
                context = pd.concat([prior, bars], ignore_index=True)
                found = observe_candidates(key, context, expected_days[key].insert(0, prior.Date.iloc[0]))
            else:
                found = observe_candidates(key, bars, expected_days[key])
            candidates[key] = tuple(c for c in found if not sample or (key.code, c.date) in sample)
        except ValueError as exc:
            failures.append({"Code": key.code, "Stage": "krx_candidate", "Reason": str(exc)})

    daily, company, targeted, filings, source_errors = _kind_inventory(
        client, args.published_start, args.published_end, args.kind_company_cache, codes, registered)
    spac_keys = {key for key, bars in securities.items()
                 if bars.SECT_TP_NM.str.contains(r"SPAC|기업인수목적|스팩", case=False, regex=True, na=False).any()}
    unresolved_issuers = {failure["Code"][:5] for failure in failures if failure["Stage"] == "identity"}
    acquired = _collect_notices(client, filings, aliases, candidates, anchors=anchors,
                                spac_keys=spac_keys, bounded=bool(codes), unresolved_issuers=unresolved_issuers,
                                registered=registered, daily=daily, expected_days=expected_days)
    notices, blocked, unparsed, structural_gaps, unattributed_structure, document_errors, nonstock, families, selected, fetched = acquired
    actions = _official_action_snapshots(args.action_snapshot)
    resolved, unresolved, failed_windows, window_coverage = [], [], [], []
    for key, bars in securities.items():
        covered = {candidate.date for candidate in candidates[key] if _covered(candidate, daily, company[key.code])}
        ledger = None
        try:
            require(key in fingerprints, "Official KRX raw window failed validation")
            ledger = resolve_events(key, bars, expected_days[key], notices[key], actions=actions[key],
                                    covered_dates=covered, blocked_dates=blocked[key], unparsed_dates=unparsed[key],
                                    transfer_anchor=anchors.get(key), transfer_source=anchor_sources.get(key))
        except ValueError as exc:
            failed_windows.append({"Code": key.code, "Stage": "resolver", "Reason": str(exc)})
        coverage_spans = [*company[key.code], *targeted[key.code]]
        window_coverage.append(_window_coverage(
            key, bars, expected_days[key], prices, daily, coverage_spans,
            structural_gaps[key], fingerprints.get(key), ledger, sampled=bool(sample),
            unattributed_structure=bool(unattributed_structure)))
        if ledger is None:
            continue
        candidates[key] = tuple(c for c in ledger.candidates if not sample or (key.code, c.date) in sample)
        targets = {c.date for c in candidates[key]}
        resolved.extend(row for row in ledger.resolutions if not sample or row.date in targets or
                        row.kind in {Resolution.SEGMENT_BREAK, Resolution.SPAC_PREMERGER} and not row.review)
        unresolved.extend({**_security_columns(key), "Date": day, "Reason": "Official search or document incomplete"}
                          for day in ledger.incomplete if not sample or day in targets)
    all_candidates = [c for values in candidates.values() for c in values]
    all_notices = [n for values in notices.values() for n in values]
    market_counts = Counter(row.kind for row in resolved)
    training_counts = Counter(row.kind for row in resolved if row.security in training)
    requested = set(calendar_days(args.published_start, args.published_end))
    resolutions_by_key = {(r.security, r.date) for r in resolved}
    observations = {(c.security, c.date): c for c in all_candidates}
    resolution_count = sum((c.security, c.date) in resolutions_by_key for c in all_candidates)
    identity_bound = {(c.security.code, c.date) for c in all_candidates}
    market_candidates_observed = sum((c.security.code, c.date) in market_observed for c in all_candidates)
    review_candidates_unobserved = sum(row.review and (row.security, row.date) in observations
                                       and (row.security.code, row.date) not in market_observed for row in resolved)
    unassigned, market_exclusions = [], []
    for code, day in sorted(market_observed.keys() - identity_bound):
        prior = market_observed[code, day]
        if group := other_groups.get((code, day)):
            market_exclusions.append({"Code": code, "Date": day, "Reason": "excluded_security_group", "Group": group})
        elif (code, day) in listing_starts and sessions.get_loc(pd.Timestamp(day)) - sessions.get_loc(prior) > 1:
            market_exclusions.append({"Code": code, "Date": day, "Reason": "nonconsecutive_listing_history"})
        else:
            unassigned.append({"Code": code, "Date": day, "PrevDate": prior.date().isoformat(),
                               "Reason": "transfer_proof_incomplete" if (code, day) in listing_starts
                               else "historical_security_identity_or_prices_incomplete"})
    confirmed = verify_review_confirmations(confirmations, notices, resolved, observations)
    coverage = {"daily": [asdict(span) for span in daily.values()],
                "company": {code: [asdict(span) for span in spans] for code, spans in company.items()},
                "archived_market_actions": {code: [asdict(span) for span in spans] for code, spans in targeted.items()},
                "windows": window_coverage, "unattributed_structural_documents": sorted(unattributed_structure),
                "missing_daily_dates": sorted(map(str, requested - set(daily))),
                "incomplete_candidates": unresolved, "unassigned_market_observations": unassigned,
                "market_observations_outside_ledger_scope": market_exclusions,
                "nonstock_notices": nonstock,
                "kind_final_families": sorted(families, key=lambda row: row["AcptNo"]),
                "failures": [*failures, *source_errors, *document_errors, *failed_windows]}
    tables = {
        "candidates": (CANDIDATE_COLUMNS, map(_candidate_columns, all_candidates)),
        "notices": (NOTICE_COLUMNS, map(_notice_columns, all_notices)),
        "resolutions": (RESOLUTION_COLUMNS, (_resolution_columns(r, observations, prices) for r in resolved)),
    }
    if confirmed:
        coverage["review_confirmations"] = confirmed
    hashes = {}
    for name, (columns, rows) in tables.items():
        path = args.output / f"{name}.csv"
        _write_csv(path, columns, rows)
        hashes[name] = sha256(path)
    atomic_json(args.output / "coverage.json", json.loads(json.dumps(coverage, default=str)))
    hashes["coverage"] = sha256(args.output / "coverage.json")
    require(implementation == _implementation_hashes(), "Census implementation changed during collection")
    report = {
        "version": POLICY_VERSION, "implementation_sha256": implementation, "table_sha256": hashes,
        "scope": {"start": str(args.start), "end": str(args.end), "published_start": str(args.published_start),
                  "published_end": str(args.published_end), "codes": sorted(codes),
                  "sample_sha256": sha256(args.sample) if args.sample else None},
        "sources": {"krx_sessions": prices, "krx_sha256": canonical_hash(prices),
                    "active_master_sha256": sha256(args.active_master), "delisted_master_sha256": sha256(args.delisted_master),
                    "official_action_snapshots": [sha256(path) for path in args.action_snapshot]},
        "price_rows": raw_count, "price_codes": int(raw_codes), "security_intervals": len(securities),
        "market_observations_before_identity": len(market_observed), "unassigned_market_observations": len(unassigned),
        "market_observations_outside_ledger_scope": len(market_exclusions),
        "market_candidates": len(all_candidates), "training_candidates": sum(c.security in training for c in all_candidates),
        "market_candidates_with_market_observation": market_candidates_observed,
        "review_candidates_without_market_observation": review_candidates_unobserved,
        "candidates_with_resolution": resolution_count, "incomplete_candidates": len(unresolved),
        "resolutions_without_price_observation": len(resolutions_by_key - observations.keys()),
        "unmatched_sample_keys": sorted(sample - {(r.security.code, r.date) for r in all_candidates}),
        "kind_list_dates": len(daily), "requested_kind_list_dates": len(requested),
        "selected_documents": selected, "retrieved_documents": fetched,
        "nonstock_notices": len(nonstock),
        "superseded_documents": len(families),
        "unattributed_structural_documents": len(unattributed_structure),
        "kind_http_calls_this_run": client.calls, "dart_http_calls_this_run": 0,
        "whole_tickers_excluded_by_resolver": None, "training_policy_active": False,
        "failed_windows": len(failed_windows), "failed_codes": len({e["Code"] for e in [*failures, *failed_windows]}),
        "complete_windows": sum(window["complete"] for window in window_coverage),
        "market_resolution_counts": {kind.value: market_counts[kind] for kind in Resolution},
        "training_resolution_counts": {kind.value: training_counts[kind] for kind in Resolution},
        "inventory_complete": len(daily) == len(requested),
        "ledger_complete": (
            not codes and len(daily) == len(requested) and resolution_count == len(all_candidates)
            and not (unassigned or unresolved or failures or failed_windows)
            and not any(e["Stage"] == "kind_document" for e in document_errors)
            and all(window["complete"] for window in window_coverage)
        ),
    }
    if confirmed:
        require(sha256(registration) == registration_hash, "Review confirmation input changed during census")
        report["sources"]["review_confirmations_sha256"] = canonical_hash(confirmed)
        report["sources"]["review_confirmations_input_sha256"] = registration_hash
    atomic_json(args.output / "manifest.json", report)
    return report


def _archive(value):
    archive, sep, run = value.partition("=")
    if not sep:
        raise argparse.ArgumentTypeError("KIND archive must be OBJECT_ROOT=RUN_ROOT")
    return Path(archive), Path(run)


def main(argv=None):
    cli = argparse.ArgumentParser(description=__doc__)
    for field in ("start", "end", "published-start", "published-end"):
        cli.add_argument(f"--{field}", type=date.fromisoformat, required=True)
    for field in ("krx-days", "active-master", "delisted-master", "kind-root", "output"):
        cli.add_argument(f"--{field}", type=Path, required=True)
    cli.add_argument("--kind-daily-cache", type=Path)
    cli.add_argument("--kind-company-cache", type=Path)
    cli.add_argument("--kind-legacy-docs", type=Path, action="append", default=[])
    cli.add_argument("--kind-archive", type=_archive, action="append", default=[])
    cli.add_argument("--action-snapshot", type=Path, action="append", default=[])
    cli.add_argument("--review-confirmations", type=Path)
    cli.add_argument("--sample", type=Path, help="CSV with Code and Date columns")
    cli.add_argument("--code", action="append", default=[], help="Restrict to one or more verified securities")
    cli.add_argument("--request-budget", type=int, default=0)
    cli.add_argument("--preview", action="store_true", help="Allow an incomplete market ledger to exit successfully")
    args = cli.parse_args(argv)
    try:
        require(args.published_start <= args.start <= args.end <= args.published_end
                <= datetime.now(ZoneInfo("Asia/Seoul")).date(), "Invalid census scope")
        args.output.mkdir(parents=True, exist_ok=True)
        args.kind_root.mkdir(parents=True, exist_ok=True)
        client = KindMarket(args.kind_root, budget=args.request_budget, daily_cache=args.kind_daily_cache,
                            company_cache=args.kind_company_cache, legacy_docs=args.kind_legacy_docs, archives=args.kind_archive)
        with (args.kind_root / "writer.lock").open("a") as lock, (args.output / "writer.lock").open("a") as output_lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                fcntl.flock(output_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise DisclosureError("Another census is writing this cache or output") from None
            require(not (args.output / "manifest.json").exists(), "Census output already published; choose a new output directory")
            report = build_census(args, client)
        print(json.dumps({key: val for key, val in report.items() if key not in {
            "implementation_sha256", "table_sha256", "sources",
        }}, ensure_ascii=False, indent=2))
        if not report["ledger_complete"] and not (args.preview or args.sample or args.code):
            cli.exit(2, "Market ledger incomplete. See coverage.json and resume with a verified cache.\n")
    except (ValueError, OSError, KeyError) as exc:
        cli.exit(1, f"{exc}\n")


if __name__ == "__main__":
    main()
