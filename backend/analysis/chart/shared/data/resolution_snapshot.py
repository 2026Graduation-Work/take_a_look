"""Freeze and verify the official resolution ledger used by local training."""

import csv
import hashlib
import io
import json
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date, timedelta
from fractions import Fraction
from pathlib import Path
from urllib.parse import urlsplit

import pandas as pd

from shared.io import canonical_hash, sha256

from .actions import FieldEvidence
from .calendar import scheduled_sessions
from .disclosures import KIND_VIEWER, Evidence, put_immutable, require
from .market_notices import SecurityKey
from .market_resolutions import (
    COMBINED_OFFERING_BONUS_REASON,
    ISSUER_MERGER_REASON,
    STRUCTURAL_REVIEW_REASON,
    Candidate,
    Resolution,
    ResolvedEvent,
    WindowLedger,
    ambiguous_document_claims,
    ambiguous_final_documents,
    issuer_merger_boundaries,
    issuer_merger_resolution,
    merger_facts,
    observed_structural_review_candidate,
    raw_window_fingerprint,
    structural_review_evidence,
    verify_structural_review_quantities,
)
from .resolution_archive import verify_archive_bindings
from .validation import KRX_RAW_COLUMNS

PRICE_POLICY = "krx_official_action_segments_v2"
SNAPSHOT_VERSION = 2
SEGMENT_COLUMN = "SegmentId"
TABLE_FILES = ("candidates.csv", "notices.csv", "resolutions.csv", "coverage.json")
SNAPSHOT_FILES = (*TABLE_FILES, "manifest.json")
SECURITY_COLUMNS = ["Code", "ISIN", "ListingDate", "DelistingDate", "Market", "ShareClass"]
CANDIDATE_COLUMNS = SECURITY_COLUMNS + ["Date", "PrevDate", "PrevClose", "BasePrice", "SharesBefore", "SharesAfter", "Paused"]
NOTICE_COLUMNS = SECURITY_COLUMNS + ["AcptNo", "FormId", "Section", "Published", "AppliedDate", "Title", "Kind",
                                    "Reason", "BasePrice", "EvaluationPrice", "Low", "High", "ParBefore", "ParAfter",
                                    "SharesBefore", "SharesAfter", "AddedShares", "Ratio", "Listing", "Sha256",
                                    "Evidence", "DocNo", "Family", "Final", "PreviousMarket", "PreviousClose", "PaidRecordDate", "PaidListing"]
RESOLUTION_COLUMNS = SECURITY_COLUMNS + ["Date", "Resolution", "PriceFactor", "VolumeFactor", "Evidence", "Reason", "Review", "FailedCheck"]
CONFIRMATION_COLUMNS = SECURITY_COLUMNS + ["Date", "OfficialURL", "FormId", "Section", "Ratio"]
REVIEW_COLUMNS = ["Code", "Date", "PrevClose", "BasePrice", "SharesBefore", "SharesAfter", "NearbyNotices", "Reason", "FailedCheck"]
BOUNDARIES = {Resolution.SEGMENT_BREAK, Resolution.SPAC_PREMERGER}


def _digest(value):
    return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) is not None


def _day(value):
    require(isinstance(value, str) and date.fromisoformat(value).isoformat() == value, "Invalid ledger date")
    return value


def _bool(value):
    require(value in {"True", "False"}, "Invalid ledger boolean")
    return value == "True"


def _security(row):
    fields = [row[field] for field in SECURITY_COLUMNS]
    fields[3] = fields[3] or None
    return SecurityKey(*fields)


def _evidence(raw):
    require(isinstance(raw, dict) and set(raw) == {"sha256", "receipt"} and all(map(_digest, raw.values())),
            "Invalid official receipt reference")
    return Evidence(**raw)


def _refs(value):
    if isinstance(value, dict):
        if set(value) == {"sha256", "receipt"}:
            yield _evidence(value)
        else:
            for item in value.values():
                yield from _refs(item)
    elif isinstance(value, list):
        for item in value:
            yield from _refs(item)


def _csv(path, columns, *, optional=()):
    with path.open(encoding="utf-8", newline="") as stream:
        reader = csv.DictReader(stream)
        require(reader.fieldnames == [col for col in columns if col not in optional or col in (reader.fieldnames or [])],
                f"Invalid ledger schema: {path.name}")
        for row in reader:
            require(None not in row and None not in row.values(), f"Invalid ledger row: {path.name}")
            yield {**dict.fromkeys(optional, ""), **row}


def _insert(mapping, key, value):
    require(key not in mapping, f"Duplicate ledger key: {key}")
    mapping[key] = value


def _scope(manifest):
    frame = manifest["scope"]
    start, end = (_day(frame[key]) for key in ("start", "end"))
    first, last = (_day(frame[key]) for key in ("published_start", "published_end"))
    codes = frame["codes"]
    require(first <= start <= end <= last and frame["sample_sha256"] is None and isinstance(codes, list)
            and codes == sorted(set(codes)) and all(re.fullmatch(r"[0-9A-Z]{6}", code) for code in codes),
            "Incomplete or sampled resolution scope")
    if "markets" in frame:
        markets = frame["markets"]
        require(isinstance(markets, list) and markets and markets == sorted(set(markets))
                and set(markets) <= {"KOSPI", "KOSDAQ"}, "Invalid resolution market scope")
    if "universe_start" in frame:
        require(start <= _day(frame["universe_start"]) <= end and frame.get("markets")
                and isinstance(frame.get("include_delisted"), bool), "Invalid verified listing universe scope")
    if "correction_cutoff" in frame:
        require(last <= _day(frame["correction_cutoff"]), "Invalid KIND correction publication cutoff")
    return start, end, codes


def _consumer_hash():
    folder = Path(__file__).parent
    return canonical_hash({name: sha256(folder / name) for name in (
        "resolution_snapshot.py", "resolution_archive.py", "segmented_prices.py", "market_resolutions.py", "events.py",
        "validation.py", "calendar.py", "market_notices.py", "kind_market.py", "actions.py",
        "disclosures.py", "training_prices.py", "issuer_aliases.json",
    )})


def snapshot_path(root, digest):
    require(_digest(digest), "Invalid resolution snapshot hash")
    return Path(root) / "official_actions" / "snapshots" / f"{digest}.json"


def price_store_manifest(directory):
    directory = Path(directory)
    path = directory / "feature_manifest.json"
    if not path.is_file() and directory.name == "processed":
        path = directory.parent / "processed_manifest.json"
    if not path.is_file() and directory.name == "raw":
        path = directory.parent / "dataset_manifest.json"
    return json.loads(path.read_text()) if path.is_file() else {}


def require_price_provenance(manifest):
    value = manifest.get("official_actions")
    require(manifest.get("price_policy") == PRICE_POLICY and isinstance(value, dict)
            and value.get("version") == SNAPSHOT_VERSION
            and all(_digest(value.get(key)) for key in ("sha256", "evidence_sha256", "producer_sha256",
                                                        "segmentation_sha256")),
            "Unsupported training price policy or missing resolution snapshot provenance")
    return value


@dataclass(frozen=True)
class ResolutionSnapshot:
    path: Path
    manifest: dict
    coverage: dict
    windows: dict
    sessions: pd.DatetimeIndex
    ledgers: dict
    training_names: dict
    notices: dict
    archive_refs: frozenset[Evidence]
    evidence_sha256: str
    segmentation_sha256: str

    @property
    def provenance(self):
        return {"sha256": self.path.stem, "version": SNAPSHOT_VERSION, "evidence_sha256": self.evidence_sha256,
                "producer_sha256": canonical_hash(self.manifest["implementation_sha256"]),
                "segmentation_sha256": self.segmentation_sha256}

    def days(self, security):
        require(security in self.windows, f"Resolution snapshot lacks listing interval: {security}")
        window = self.windows[security]
        return self.sessions[(self.sessions >= window["first_session"]) & (self.sessions <= window["last_session"])]

    def select_sessions(self, sessions):
        days = pd.DatetimeIndex(sessions)
        require(len(days) and days.equals(self.sessions[(self.sessions >= days[0]) & (self.sessions <= days[-1])]),
                "Collection calendar requires complete sessions from the resolution snapshot")
        return days

    def window(self, security, raw, days, *, source=None):
        full = self.days(security)
        require(self.windows[security]["complete"] and
                days.equals(full[(full >= days[0]) & (full <= days[-1])]),
                f"{security.code}: incomplete or invalid resolution listing window")
        if days.equals(full):
            expected_hash = self.windows[security]["raw_sha256"]
        else:
            require(source is not None, f"{security.code}: partial window requires verified KRX source days")
            expected_hash = raw_window_fingerprint(source.bars(security, days), days)
        require(raw_window_fingerprint(raw, days) == expected_hash,
                f"{security.code}: KRX raw prices differ from the resolution snapshot")
        ledger = self.ledgers[security]
        review_dates = {row.date for row in ledger.resolutions if row.reason == STRUCTURAL_REVIEW_REASON}
        for candidate in ledger.candidates:
            if candidate.date not in review_dates or pd.Timestamp(candidate.date) not in days:
                continue
            proof = pd.DatetimeIndex([candidate.prev_date, candidate.date])
            evidence = (raw.loc[raw.Date.isin(proof)] if proof.isin(days).all() else source.bars(security, proof))
            require(candidate == observed_structural_review_candidate(security, evidence, proof, candidate.date),
                    f"{security.code}: structural review candidate differs from actual KRX prices")
        return ledger

    def segment_starts(self, security):
        first = self.windows[security]["first_session"]
        dates = {security.listing, *(row.date for row in self.ledgers[security].resolutions
                                    if row.kind in BOUNDARIES and row.date >= first)}
        return sorted(dates)

    def excluded_segment_ids(self, security):
        spac = self.windows[security]["spac"]
        if not spac["observations"] and not spac["merger_listing"]:
            return frozenset()
        end = spac["merger_listing"]
        return frozenset(segment_id(security, start) for start in self.segment_starts(security)
                         if end is None or start < end)

    def review_rows(self, securities=None, *, sessions=None):
        included = None if sessions is None else {day.date().isoformat() for day in sessions}
        for security in self.ledgers if securities is None else securities:
            ledger = self.ledgers[security]
            candidates = {item.date: item for item in ledger.candidates}
            for row in ledger.resolutions:
                if not row.review or (included is not None and row.date not in included):
                    continue
                candidate = candidates[row.date]
                day = date.fromisoformat(row.date)
                accessions = {ref.accession for ref in row.evidence if ref.field.startswith("KIND ")}
                accessions.update(accession for accession, published, applied in self.notices[security]
                                  if -30 <= (date.fromisoformat(published) - day).days <= 3 or applied == row.date)
                yield dict(zip(REVIEW_COLUMNS, (
                    security.code, row.date, candidate.prev_close, candidate.base_price,
                    candidate.shares_before, candidate.shares_after,
                    " ".join(kind_document_url(item)
                             for item in sorted(accessions)),
                    row.reason, row.failed_check,
                )))


@dataclass(frozen=True)
class VerifiedSourceDays:
    _by_code: object

    @staticmethod
    def _verified_bytes(snapshot, days, source_days, destination=None):
        days = snapshot.select_sessions(days)
        pos = snapshot.sessions.get_loc(days[0])
        if pos:
            days = snapshot.sessions[pos - 1:pos].append(days)
        hashes = snapshot.manifest["sources"]["krx_sessions"]
        for day in days:
            session = day.date().isoformat()
            name = f"{session}.parquet"
            target = Path(destination) / name if destination is not None else None
            path = target if target is not None and target.exists() else Path(source_days) / name
            require(path.is_file(), f"Missing verified KRX day {session}: {path}")
            body = path.read_bytes()
            require(hashlib.sha256(body).hexdigest() == hashes[session],
                    f"KRX source day bytes differ from the resolution snapshot: {session}")
            if target is not None and path != target:
                put_immutable(target, body)
            yield body

    @classmethod
    def check_files(cls, snapshot, days, directory):
        for _ in cls._verified_bytes(snapshot, days, directory):
            pass

    @classmethod
    def read(cls, snapshot, days, source_days, *, destination=None):
        frames = []
        for body in cls._verified_bytes(snapshot, days, source_days, destination):
            frame = pd.read_parquet(io.BytesIO(body), columns=["Code", "MKT_NM", *KRX_RAW_COLUMNS])
            frame["MKT_NM"] = frame.MKT_NM.replace({"KOSDAQ GLOBAL": "KOSDAQ"})
            frames.append(frame)
        return cls(pd.concat(frames, ignore_index=True).groupby("Code", sort=False))

    def bars(self, security, days):
        rows = self._by_code.get_group(security.code)
        return rows.loc[rows.MKT_NM.eq(security.market) & rows.Date.isin(days), KRX_RAW_COLUMNS]


def kind_document_url(accession):
    return f"{KIND_VIEWER}?method=search&acptno={accession}"


def segment_id(security, start):
    return f"{security.isin}:{security.listing}:{start}"


def _publication_spans(coverage, refs):
    def spans(rows):
        values = []
        for entry in rows:
            start, end = (_day(entry[k]) for k in ("start", "end"))
            require(start <= end and isinstance(entry["rows"], int) and entry["rows"] >= 0 and entry["pages"],
                    "Invalid publication coverage")
            refs.update(map(_evidence, entry["pages"]))
            values.append((date.fromisoformat(start), date.fromisoformat(end)))
        return values

    daily = spans(coverage["daily"])
    require(all(start == end for start, end in daily) and len(set(daily)) == len(daily),
            "Duplicate or invalid daily publication coverage")
    bounded = defaultdict(list)
    for table in ("company", "archived_market_actions"):
        for code, entries in coverage[table].items():
            bounded[code].extend(spans(entries))
    corrected = coverage.get("correction_daily", ())
    supplements = spans(corrected)
    require(all(start == end for start, end in supplements) and len(set(supplements)) == len(supplements),
            "Duplicate or invalid KIND correction publication coverage")
    correction_pages = {row["start"]: set(map(_evidence, row["pages"])) for row in corrected}
    return {start for start, _ in daily}, bounded, correction_pages


def _load_tables(folder, manifest):
    start, end, codes = _scope(manifest)
    sessions = scheduled_sessions(pd.Timestamp(start), pd.Timestamp(end))
    price_hashes = manifest["sources"]["krx_sessions"]
    require(set(price_hashes) == {day.date().isoformat() for day in sessions}
            and all(map(_digest, price_hashes.values()))
            and canonical_hash(price_hashes) == manifest["sources"]["krx_sha256"], "Invalid KRX session provenance")
    coverage = json.loads((folder / "coverage.json").read_bytes())
    confirmations = coverage.get("review_confirmations")
    require((canonical_hash(confirmations) if confirmations else None)
            == manifest["sources"].get("review_confirmations_sha256"),
            "Manual review registrations differ from producer lineage")
    windows, refs = {}, set()
    daily, bounded, correction_pages = _publication_spans(coverage, refs)
    published = manifest["scope"]
    require(all(published["published_end"] < day <= published.get("correction_cutoff", published["published_end"])
                for day in correction_pages), "KIND correction publication is outside the frozen scope")
    nonstock = coverage.get("nonstock_notices", [])
    require(isinstance(nonstock, list) and len(nonstock) == manifest.get("nonstock_notices", 0),
            "Non-stock notice count differs from census manifest")
    nonstock_keys = set()
    for row in nonstock:
        require(isinstance(row, dict) and set(row) == {"AcptNo", "DocNo", "FormId", "Evidence"}
                and all(isinstance(row[name], str) and re.fullmatch(r"[0-9]{14}", row[name])
                        for name in ("AcptNo", "DocNo")) and row["FormId"] == "68155"
                and isinstance(row["Evidence"], list) and len(row["Evidence"]) == 4
                and row["AcptNo"] not in nonstock_keys, "Invalid or missing official non-stock notice evidence")
        nonstock_keys.add(row["AcptNo"])
        refs.update(map(_evidence, row["Evidence"]))
    outside, outside_targets = [], set()
    for failure in coverage["failures"]:
        if not ({"OutsidePriceWindows", "VerifiedEffectiveDates"} & failure.keys()):
            continue
        excluded, dates = failure.get("OutsidePriceWindows"), failure.get("VerifiedEffectiveDates")
        require(isinstance(excluded, list) and excluded and isinstance(dates, list) and dates
                and isinstance(failure.get("Evidence"), list) and len(failure["Evidence"]) in {4, 9},
                "Out-of-window structural decision lacks dated official evidence")
        keys = {_security(item) for item in excluded}
        require(len(keys) == len(excluded) and list(map(_day, dates)) == sorted(set(dates)),
                "Invalid out-of-window security keys or dates")
        outside.append((keys, dates))
        evidence = tuple(map(_evidence, failure["Evidence"]))
        if "FinalAcptNo" in failure:
            accession = failure["FinalAcptNo"]
            require(len(evidence) == 9 and isinstance(accession, str) and re.fullmatch(r"[0-9]{14}", accession),
                    "Invalid archived final accession in out-of-window evidence")
            outside_targets.add((accession, evidence[5]))
        refs.update(evidence)
    families = coverage.get("kind_final_families", [])
    require(isinstance(families, list) and len(families) == manifest.get("superseded_documents", 0),
            "KIND final family count differs from census manifest")
    sources, review_refs, final_targets = set(), {}, outside_targets
    for row in families:
        identifiers = ("AcptNo", "DocNo", "FinalAcptNo", "FinalDocNo")
        require(isinstance(row, dict) and set(row) - {"OriginalNoticeEvidence", "ReviewWitness"}
                == {*identifiers, "FormId", "ClosedWindows", "Evidence"}
                and all(isinstance(row[name], str) and re.fullmatch(r"[0-9]{14}", row[name]) for name in identifiers)
                and row["AcptNo"] != row["FinalAcptNo"] and row["DocNo"] != row["FinalDocNo"]
                and isinstance(row["FormId"], str) and re.fullmatch(r"[0-9]{5}", row["FormId"])
                and isinstance(row["ClosedWindows"], list) and isinstance(row["Evidence"], list)
                and len(row["Evidence"]) == 7 and row["AcptNo"] not in sources, "Invalid KIND final family evidence")
        closed = {_security(item) for item in row["ClosedWindows"]}
        require(len(closed) == len(row["ClosedWindows"]), "Duplicate KIND final family closure window")
        sources.add(row["AcptNo"])
        final_targets.add((row["FinalAcptNo"], _evidence(row["Evidence"][3])))
        refs.update(map(_evidence, row["Evidence"]))
        if "OriginalNoticeEvidence" in row:
            original = row["OriginalNoticeEvidence"]
            require(row["FormId"] in {"70765", "32002"} and isinstance(original, list) and len(original) == 2
                    and closed, "Invalid KIND source role evidence")
            refs.update(map(_evidence, original))
        if "ReviewWitness" in row:
            witness = row["ReviewWitness"]
            require(isinstance(witness, dict) and set(witness) == {"Security", "Date", "OriginalFormId", "OriginalNoticeEvidence"}
                    and row["FormId"] == "68155" and witness["OriginalFormId"] == "68151" and not closed
                    and isinstance(witness["OriginalNoticeEvidence"], list) and len(witness["OriginalNoticeEvidence"]) == 2,
                    "Invalid KIND structural review witness")
            original = tuple(map(_evidence, witness["OriginalNoticeEvidence"]))
            refs.update(original)
            key = _security(witness["Security"]), _day(witness["Date"])
            _insert(review_refs, key, structural_review_evidence(row["AcptNo"], row["FinalAcptNo"],
                                                                 tuple(map(_evidence, row["Evidence"])), original))
    first = date.fromisoformat(published["published_start"])
    last = date.fromisoformat(published["published_end"])
    requested = {first + timedelta(days=offset) for offset in range((last - first).days + 1)}
    require(daily <= requested and (set(coverage["missing_daily_dates"]) == {str(day) for day in requested - daily}),
            "Publication inventory differs from census scope")
    for row in coverage["windows"]:
        security = _security(row)
        first, last = (_day(row[field]) for field in ("first_session", "last_session"))
        left = date.fromisoformat(_day(row["publication_start"]))
        right = date.fromisoformat(_day(row["publication_end"]))
        days = sessions[sessions >= security.listing]
        if security.delisting:
            days = days[days < security.delisting]
        require(len(days) and start <= first <= last <= end and
                (first, last) == (days[0].date().isoformat(), days[-1].date().isoformat())
                and row["expected_sessions"] == len(days) and (not codes or security.code in codes),
                f"{security.code}: coverage window differs from official sessions")
        complete_search = all(day in daily or any(a <= day <= b for a, b in bounded[security.code])
                              for day in (left + timedelta(days=i) for i in range((right - left).days + 1)))
        require(left == days[0].date() - timedelta(days=7) and right == days[-1].date() + timedelta(days=3)
                and row["publication_complete"] is complete_search, "Invalid publication coverage bounds")
        require(row["complete"] is (complete_search and _digest(row["raw_sha256"])
                                    and row["price_rows"] == len(days)
                                    and not row["structural_documents_incomplete"]
                                    and not row["required_dates_incomplete"]
                                    and not row["unattributed_structural_documents_present"]),
                "Inconsistent resolution window completeness")
        _insert(windows, security, row)
    require(all(keys <= windows.keys() and all(day < windows[key]["first_session"] for day in dates for key in keys)
                for keys, dates in outside), "Structural event is not before the verified price windows")
    require(len(windows) == manifest["security_intervals"] and windows, "Resolution ledger lacks listing windows")
    require(not codes or {key.code for key in windows} == set(codes), "Resolution ledger lacks a requested code")
    require(all(key in windows and day in price_hashes and windows[key]["first_session"] < day <= windows[key]["last_session"]
                for key, day in review_refs), "KIND structural review lies outside its listing window")

    candidates, notices, resolutions = {}, defaultdict(list), {}
    for row in _csv(folder / "candidates.csv", CANDIDATE_COLUMNS):
        security, day, prev = _security(row), _day(row["Date"]), _day(row["PrevDate"])
        quantities = tuple(int(row[field]) for field in REVIEW_COLUMNS[2:6])
        require(security in windows and day in price_hashes and prev in price_hashes
                and windows[security]["first_session"] <= day <= windows[security]["last_session"]
                and prev < day and min(quantities) > 0, "Invalid candidate identity, date, or prices")
        _insert(candidates, (security, day), Candidate(security, day, prev, *quantities, _bool(row["Paused"])))
    notice_refs, merger_refs, combined_terms = {}, defaultdict(dict), {}
    final_claims, final_sections = [], defaultdict(set)
    for row in _csv(folder / "notices.csv", NOTICE_COLUMNS, optional=("PaidRecordDate", "PaidListing")):
        security = _security(row)
        accession, form, section = row["AcptNo"], row["FormId"], int(row["Section"])
        published, applied = _day(row["Published"]), _day(row["AppliedDate"])
        key = (security, accession, form, section)
        evidence = tuple(map(_evidence, json.loads(row["Evidence"])))
        in_scope = manifest["scope"]["published_start"] <= published <= manifest["scope"]["published_end"]
        corrected = (row["Final"] == "True" and evidence and (accession, evidence[0]) in final_targets
                     and evidence[0] in correction_pages.get(published, ()))
        require(security in windows and security.active(applied) and (in_scope or corrected)
                and re.fullmatch(r"[0-9]{14}", accession) and re.fullmatch(r"[0-9]{5}", form)
                and section > 0 and re.fullmatch(r"[0-9]{14}", row["DocNo"]) and evidence and evidence[-1].sha256 == row["Sha256"],
                "Invalid or duplicate official notice")
        _insert(notice_refs, key, set(evidence))
        if row["Final"] == "True":
            final_claims.append((row["DocNo"], json.loads(row["Family"])))
            final_sections[accession, form, section].add(row["DocNo"])
        if form == "11308" and row["Kind"] == "bonus_terms":
            require(row["Final"] == "True" and row["Ratio"] and Fraction(row["Ratio"]) > 0
                    and int(row["AddedShares"]) > 0 and row["Listing"]
                    and _day(row["PaidRecordDate"]) and _day(row["PaidListing"]),
                    "Invalid combined offering bonus terms")
            combined_terms[key] = row
        if (row["Final"] == "True" and merger_facts(row["Kind"], row["Reason"]) and applied in price_hashes
                and windows[security]["first_session"] <= applied <= windows[security]["last_session"]):
            merger_refs[(security.code[:5], applied, accession, form, section)][security] = set(evidence)
        refs.update(evidence)
        notices[security].append((accession, published, applied))

    ambiguous_finals = ambiguous_document_claims(final_claims)
    section_owners = defaultdict(set)
    for security, accession, form, section in notice_refs:
        section_owners[accession, form, section].add(security)

    def section_key(value):
        require(isinstance(value, list) and len(value) == 3 and all(isinstance(part, str) for part in value[:2])
                and type(value[2]) is int, "Invalid KIND auction identity section")
        return tuple(value)

    linked = set()
    links = coverage.get("kind_auction_identity_links", [])
    require(isinstance(links, list), "Invalid KIND auction identity links")
    for item in links:
        require(isinstance(item, dict) and set(item) == {"Auction", "Witnesses"}
                and isinstance(item["Witnesses"], list) and 1 <= len(item["Witnesses"]) <= 2,
                "Invalid KIND auction identity link")
        source = section_key(item["Auction"])
        require(len(section_owners.get(source, ())) == 1 and source not in linked and source[1] in {"99332", "99334"}
                and all(section_owners.get(section_key(ref)) == section_owners[source] for ref in item["Witnesses"]),
                "KIND auction identity link does not reference the same security")
        linked.add(source)

    for row in _csv(folder / "resolutions.csv", RESOLUTION_COLUMNS, optional=("FailedCheck",)):
        security, day = _security(row), _day(row["Date"])
        key = (security, day)
        kind, review = Resolution(row["Resolution"]), _bool(row["Review"])
        inherited_merger = row["Reason"] == ISSUER_MERGER_REASON
        require(security in windows and day in price_hashes and
                windows[security]["first_session"] <= day <= windows[security]["last_session"] and row["Reason"]
                and (not review or kind == Resolution.SEGMENT_BREAK and key in candidates)
                and (not inherited_merger or kind == Resolution.SEGMENT_BREAK and not review),
                "Invalid resolution identity, date or review flag")
        fields, raw_days, ticks = [], set(), 0
        for item in json.loads(row["Evidence"]):
            source = item["source"]
            if isinstance(source, dict):
                ref = _evidence(source)
                accession, field = item["accession"], item["field"]
                require(re.fullmatch(r"[0-9]{14}", accession) and isinstance(field, str) and field,
                        "Invalid official field evidence")
                if match := re.fullmatch(r"KIND ([0-9]{5})/([0-9]+)", field):
                    form, section = match[1], int(match[2])
                    require(review or not ambiguous_finals.intersection(final_sections.get((accession, form, section), ())),
                            "Automatic resolution uses an ambiguous KIND correction family")
                    if inherited_merger:
                        bound = merger_refs.get((security.code[:5], day, accession, form, section), {})
                        valid = any(source != security and ref in refs for source, refs in bound.items())
                    else:
                        valid = ref in notice_refs.get((security, accession, form, section), ())
                    require(valid, "Resolution evidence refers to another notice or security")
                else:
                    require(not inherited_merger, "Issuer merger evidence must reference the original KIND notice")
                fields.append(FieldEvidence(accession, ref, field))
                refs.add(ref)
            elif source == "KRX raw":
                require(price_hashes.get(item["session"]) == item["sha256"], "Unknown KRX evidence")
                raw_days.add(item["session"])
            else:
                require(source == "KRX tick table" and kind == Resolution.TICK_ROUNDING
                        and item["market"] == security.market
                        and item["effective_from"] == ("2023-01-25" if day >= "2023-01-25" else None),
                        "Invalid non-document evidence")
                ticks += 1
        candidate = candidates.get(key)
        if key in review_refs or row["Reason"] == STRUCTURAL_REVIEW_REASON:
            require(review and kind == Resolution.SEGMENT_BREAK and row["Reason"] == STRUCTURAL_REVIEW_REASON
                    and tuple(fields) == review_refs.get(key), "KIND structural review resolution differs from its witness")
            previous = sessions[sessions.get_loc(pd.Timestamp(day)) - 1].date().isoformat()
            require(candidate.prev_date == previous, "KIND structural review requires adjacent actual KRX sessions")
        require(raw_days == ({day, candidate.prev_date} if candidate else {day})
                and ticks == int(kind == Resolution.TICK_ROUNDING)
                and (fields or review or kind == Resolution.TICK_ROUNDING),
                "Missing resolution evidence")
        price, volume = (Fraction(row[name]) if row[name] else None for name in ("PriceFactor", "VolumeFactor"))
        if row["Reason"] == COMBINED_OFFERING_BONUS_REASON:
            terms = {key: term for key, term in combined_terms.items() if key[0] == security
                     and any(field.accession == key[1] and field.field == f"KIND 11308/{key[3]}" for field in fields)}
            require(kind == Resolution.BONUS and candidate and not review and len(terms) == 1,
                    "Combined offering bonus lacks one final official allocation")
            term, = terms.values()
            record, listing = _day(term["AppliedDate"]), _day(term["Listing"])
            require(price == Fraction(candidate.base_price, candidate.prev_close)
                    and volume == 1 + Fraction(term["Ratio"]) and abs(price * volume - 1) <= Fraction(1, 50)
                    and _day(term["PaidRecordDate"]) != record
                    and day < record <= listing and listing in price_hashes
                    and len(scheduled_sessions(pd.Timestamp(day), pd.Timestamp(record))) == 2,
                    "Combined offering bonus factors or dates disagree")
        elif kind in {Resolution.UNIT_CHANGE, Resolution.BONUS}:
            require(price is not None and volume is not None and price * volume == 1
                    and (kind != Resolution.BONUS or volume > 1), "Share-unit factors disagree")
        elif kind in {Resolution.REFERENCE_RESET, Resolution.TICK_ROUNDING, Resolution.RIGHTS}:
            expected_price = Fraction(candidate.base_price, candidate.prev_close) if kind == Resolution.RIGHTS and candidate else 1
            require(price == expected_price and volume == 1 and (kind != Resolution.RIGHTS or candidate),
                    "Reference or rights factors disagree")
        _insert(resolutions, key, ResolvedEvent(security, day, kind, row["Reason"], tuple(fields), price, volume, review, row["FailedCheck"]))

    require(review_refs.keys() <= resolutions.keys(), "Resolution ledger omits a witnessed structural review")
    require(len(candidates) == manifest["market_candidates"] and
            sum(key in resolutions for key in candidates) == manifest["candidates_with_resolution"]
            and len(resolutions.keys() - candidates.keys()) == manifest["resolutions_without_price_observation"],
            "Resolution table counts differ from census manifest")
    counts = Counter(row.kind for row in resolutions.values())
    require(manifest["market_resolution_counts"] == {kind.value: counts[kind] for kind in Resolution},
            "Resolution type counts differ from census manifest")
    candidates_by_key, resolutions_by_key = defaultdict(list), defaultdict(list)
    for (security, _), candidate in candidates.items():
        candidates_by_key[security].append(candidate)
    for (security, _), resolution in resolutions.items():
        resolutions_by_key[security].append(resolution)
    ledgers = {}
    for security, window in windows.items():
        known = tuple(sorted(resolutions_by_key[security], key=lambda item: item.date))
        observed = tuple(sorted(candidates_by_key[security], key=lambda item: item.date))
        incomplete = tuple(map(_day, window["required_dates_incomplete"]))
        require(not window["complete"] or all((security, item.date) in resolutions for item in observed),
                "Complete window has an unresolved ledger lookup")
        spac = window["spac"]
        merger = [row.date for row in known if row.kind == Resolution.SPAC_PREMERGER]
        require(merger == ([spac["merger_listing"]] if spac["merger_listing"] else []), "SPAC merger differs from ledger")
        for item in spac["observations"]:
            require(item["field"] == "SECT_TP_NM" and item["session"] in price_hashes
                    and price_hashes[item["session"]] == item["sha256"]
                    and window["first_session"] <= item["session"] <= window["last_session"]
                    and re.search(r"SPAC|기업인수목적|스팩", item["value"], re.I)
                    and (not merger or item["session"] < merger[0]), "Invalid SPAC classification evidence")
        ledgers[security] = WindowLedger(observed, known, incomplete)
    return coverage, windows, sessions, ledgers, notices, frozenset(refs)


def _archive_file(archives, kind, name):
    for archive in archives:
        path = archive / kind / name
        if path.is_file():
            return path
    raise ValueError(f"Missing official archive {kind}: {name}")


def _archive_receipts(refs, archives, destination=None):
    checked = {}
    for ref in sorted(refs, key=lambda item: item.receipt):
        receipt_path = _archive_file(archives, "receipts", f"{ref.receipt}.json")
        receipt = receipt_path.read_bytes()
        require(hashlib.sha256(receipt).hexdigest() == ref.receipt, "Official receipt hash differs")
        metadata = json.loads(receipt)
        request = metadata["request"]
        url = urlsplit(request["url"])
        require(metadata["sha256"] == ref.sha256 and url.scheme == "https" and
                url.netloc in {"kind.krx.co.kr", "opendart.fss.or.kr", "dart.fss.or.kr"}
                and not re.search(rb'crtfc_key|authorization|api[_-]?key|password', receipt, re.I),
                "Invalid public official receipt")
        if ref.sha256 not in checked:
            body = _archive_file(archives, "objects", ref.sha256).read_bytes()
            require(hashlib.sha256(body).hexdigest() == ref.sha256 and len(body) == metadata["bytes"],
                    "Official archived response differs")
            if destination is not None:
                put_immutable(destination / "objects" / ref.sha256, body)
            checked[ref.sha256] = len(body)
        require(checked[ref.sha256] == metadata["bytes"], "Official archived response size differs")
        if destination is not None:
            put_immutable(destination / "receipts" / receipt_path.name, receipt)


def _table_paths(folder, manifest):
    files = {name: folder / name for name in TABLE_FILES}
    hashes = manifest["table_sha256"]
    require(set(hashes) == {path.stem for path in files.values()} and all(
        _digest(hashes[path.stem]) and path.is_file() and sha256(path) == hashes[path.stem] for path in files.values()
    ), "Resolution census table hash differs")
    require(manifest["version"] == 1 and manifest["training_policy_active"] is False
            and manifest["implementation_sha256"] and all(map(_digest, manifest["implementation_sha256"].values())),
            "Invalid resolution census producer")
    return files


def _eligible(coverage, windows, training_names, codes):
    chosen = {key for key in windows if not codes or key.code in codes}
    require(not coverage["unattributed_structural_documents"] and
            not coverage["unassigned_market_observations"] and
            all(windows[key]["complete"] for key in chosen) and
            not any(item["Stage"] in {"identity", "kind_document", "resolver", "krx_candidate"}
                    for item in coverage["failures"]), "Resolution snapshot has incomplete source or identity coverage")
    require(training_names and training_names.keys() <= chosen and all(
        key.market in {"KOSPI", "KOSDAQ"} and isinstance(name, str) and name for key, name in training_names.items()
    ), "Resolution snapshot lacks eligible KOSPI/KOSDAQ 주권 listing windows")


def seal_resolution_snapshot(census_dir, destination, manifest, files, names, refs,
                             action_snapshots, evidence_archives, *, verify_ledger=None):
    manifest_path = census_dir / "manifest.json"
    sources = manifest["sources"]
    action_archives = [Path(path).parent.parent / "archive" for path in action_snapshots]
    archive = destination / "archive"
    refs = refs.union(*(set(_refs(json.loads(Path(path).read_bytes()))) for path in action_snapshots))
    _archive_receipts(refs, [*map(Path, evidence_archives), *action_archives], archive)
    official, reviews = verify_archive_bindings(census_dir, json.loads(files["coverage.json"].read_bytes()), archive,
                                                set(sources["krx_sessions"]))
    require(not reviews or verify_ledger is not None, "KIND structural reviews require actual KRX price replay")
    if verify_ledger is not None:
        verify_ledger(official, reviews)
    for path, digest in zip(action_snapshots, sources["official_action_snapshots"]):
        put_immutable(archive / "objects" / digest, Path(path).read_bytes())
    content = {
        "version": SNAPSHOT_VERSION, "price_policy": PRICE_POLICY, "segmentation_sha256": _consumer_hash(),
        "evidence_sha256": canonical_hash(sorted((ref.sha256, ref.receipt) for ref in refs)),
        "files": {name: sha256(path) for name, path in {**files, "manifest.json": manifest_path}.items()},
        "training_names": [[*vars(key).values(), name] for key, name in sorted(names.items(), key=lambda x: str(x[0]))],
    }
    body = (json.dumps(content, sort_keys=True, ensure_ascii=False) + "\n").encode()
    digest = hashlib.sha256(body).hexdigest()
    root = destination / "snapshots" / f"{digest}.json"
    for name, path in {**files, "manifest.json": manifest_path}.items():
        payload = path.read_bytes()
        require(hashlib.sha256(payload).hexdigest() == content["files"][name], f"Census file changed: {name}")
        put_immutable(root.with_suffix("") / name, payload)
    put_immutable(root, body)
    return root


def read_resolution_snapshot(path, *, verify_archive=False):
    path = Path(path)
    require(path.is_file() and _digest(path.stem) and sha256(path) == path.stem,
            "Missing or changed hash-addressed resolution snapshot")
    root = json.loads(path.read_bytes())
    require(root.get("version") == SNAPSHOT_VERSION and root.get("price_policy") == PRICE_POLICY
            and _digest(root.get("segmentation_sha256")), "Unsupported resolution snapshot version or price policy")
    folder = path.with_suffix("")
    require(set(root["files"]) == set(SNAPSHOT_FILES) and all(
        _digest(digest) and (folder / name).is_file() and sha256(folder / name) == digest
        for name, digest in root["files"].items()
    ), "Resolution snapshot file hash differs")
    manifest = json.loads((folder / "manifest.json").read_bytes())
    _table_paths(folder, manifest)
    coverage, windows, sessions, ledgers, notices, refs = _load_tables(folder, manifest)
    names = {}
    for row in root["training_names"]:
        _insert(names, SecurityKey(*row[:-1]), row[-1])
    _eligible(coverage, windows, names, _scope(manifest)[2])
    archive = path.parent.parent / "archive"
    for digest in manifest["sources"]["official_action_snapshots"]:
        require(_digest(digest), "Invalid prior Action snapshot hash")
        prior = archive / "objects" / digest
        require(prior.is_file() and sha256(prior) == digest, "Prior Action snapshot bytes differ")
        refs = refs.union(_refs(json.loads(prior.read_bytes())))
    require(root["evidence_sha256"] == canonical_hash(sorted((ref.sha256, ref.receipt) for ref in refs)),
            "Resolution snapshot evidence inventory differs")
    if verify_archive:
        _archive_receipts(refs, [archive])
        session_dates = set(manifest["sources"]["krx_sessions"])
        official, reviews = verify_archive_bindings(folder, coverage, archive, session_dates)
        ambiguous_finals = ambiguous_final_documents(official)
        inherited = issuer_merger_boundaries(
            official, windows, lambda key, day: key in windows and day in session_dates
            and windows[key]["first_session"] <= day <= windows[key]["last_session"])
        expected = {(key, day): set(issuer_merger_resolution(key, day, sources).evidence)
                    for key, days in inherited.items() for day, sources in days.items()
                    if not any(notice.document_no in ambiguous_finals for notice in sources)}
        actual = {(key, row.date): set(row.evidence) for key, ledger in ledgers.items()
                  for row in ledger.resolutions if row.reason == ISSUER_MERGER_REASON}
        require(actual == expected, "Issuer merger resolutions differ from the official source archive")
        for key, proofs in reviews.items():
            candidates = {candidate.date: candidate for candidate in ledgers[key].candidates}
            for proof in proofs:
                verify_structural_review_quantities(candidates[proof.date], proof)
    return ResolutionSnapshot(path, manifest, coverage, windows, sessions, ledgers, names, notices,
                              refs, root["evidence_sha256"], root["segmentation_sha256"])


def pin_resolution_snapshot(snapshot, root):
    target = snapshot_path(root, snapshot.path.stem)
    source_archive = snapshot.path.parent.parent / "archive"
    archive = target.parent.parent / "archive"
    _archive_receipts(snapshot.archive_refs, [source_archive], archive)
    for digest in snapshot.manifest["sources"]["official_action_snapshots"]:
        put_immutable(archive / "objects" / digest, (source_archive / "objects" / digest).read_bytes())
    for name in SNAPSHOT_FILES:
        put_immutable(target.with_suffix("") / name, (snapshot.path.with_suffix("") / name).read_bytes())
    put_immutable(target, snapshot.path.read_bytes())
    return read_resolution_snapshot(target, verify_archive=True)
