"""Verified share-unit decisions tied to a KRX security and effective session."""

import json
import math
import re
from dataclasses import dataclass
from datetime import date
from fractions import Fraction
from html import unescape
from pathlib import Path

from shared.io import sha256

from .disclosures import DisclosureError, Evidence, TableRows, one, require

PRICE_POLICY = "krx_official_share_units_historical_revision_v1"
SOURCES = ("OpenDART list", "KIND market actions")
SNAPSHOT_VERSION = 1


def valid_isin(isin):
    if not re.fullmatch(r"[A-Z]{2}[0-9A-Z]{9}[0-9]", isin) or isin.startswith("KRA"):
        return False
    digits = "".join(str(ord(char) - 55) if char.isalpha() else char for char in isin)
    weighted = [int(char) * (1 + i % 2) for i, char in enumerate(reversed(digits))]
    return sum(value if value < 10 else value - 9 for value in weighted) % 10 == 0


@dataclass(frozen=True)
class Security:
    code: str
    isin: str
    share_class: str
    listing: str
    delisting: str | None
    corporation: str
    issuer_code: str
    market: str = "KOSPI"

    def __post_init__(self):
        try:
            listing = date.fromisoformat(self.listing)
            delisting = date.fromisoformat(self.delisting) if self.delisting is not None else None
        except (TypeError, ValueError):
            raise DisclosureError("Invalid KRX listing interval date") from None
        require(re.fullmatch(r"[0-9A-Z]{6}", self.code)
                and valid_isin(self.isin)
                and self.share_class in {"common", "preferred"} and self.market in {"KOSPI", "KOSDAQ"}
                and re.fullmatch(r"[0-9]{8}", self.corporation)
                and re.fullmatch(r"[0-9A-Z]{6}", self.issuer_code)
                and self.listing == listing.isoformat()
                and (delisting is None or (listing < delisting and self.delisting == delisting.isoformat())),
                "Invalid KRX security identity")

    def active(self, day):
        return self.listing <= day and (self.delisting is None or day < self.delisting)


@dataclass(frozen=True)
class FieldEvidence:
    accession: str
    source: Evidence
    field: str


@dataclass(frozen=True)
class Decision:
    accession: str
    published: date
    family: str
    kind: str
    factor: Fraction
    listing: str | None
    allocation: str | None
    ratio: FieldEvidence
    dates: FieldEvidence
    cancelled: bool = False


@dataclass(frozen=True)
class Implementation:
    kind: str
    ex_date: str
    evidence: FieldEvidence
    factor: Fraction | None = None
    base: int | None = None
    shares: tuple[int, int] | None = None
    company: str | None = None


@dataclass(frozen=True)
class Auction:
    date: str
    evaluation: int
    low: int
    high: int
    evidence: FieldEvidence
    company: str


@dataclass(frozen=True)
class Action:
    event_id: str
    revision: str
    kind: str
    ex_date: str
    new_units: int
    old_units: int
    listing: str | None
    base: int | None
    shares: tuple[int, int] | None
    ratio_evidence: FieldEvidence
    dates_evidence: FieldEvidence
    implementation_evidence: FieldEvidence
    auction: Auction | None = None
    market: str = "KOSPI"

    @property
    def factor(self):
        return Fraction(self.new_units, self.old_units)


def implementation_hashes():
    chart = Path(__file__).resolve().parents[2]
    paths = ("shared/data/actions.py", "shared/data/disclosures.py", "shared/data/events.py",
             "shared/data/training_prices.py", "shared/data/calendar.py", "shared/data/metadata.py",
             "experiments/dataset/collect_actions.py")
    return {path: sha256(chart / path) for path in paths}


def require_price_provenance(manifest):
    evidence = manifest.get("official_actions")
    require(manifest.get("price_policy") == PRICE_POLICY and isinstance(evidence, dict)
            and re.fullmatch(r"[0-9a-f]{64}", evidence.get("sha256", ""))
            and evidence.get("version") == SNAPSHOT_VERSION,
            "Unsupported training price policy or missing official action provenance")
    return evidence


def read_snapshot(path, *, verify_archive=False):
    payload = json.loads(Path(path).read_text())
    require(payload.get("version") == SNAPSHOT_VERSION and payload.get("price_policy") == PRICE_POLICY
            and payload.get("implementation_sha256") == implementation_hashes(),
            "Unsupported official action snapshot implementation")
    if verify_archive:
        archive = Path(path).parent.parent / "archive"

        def verify(item):
            if isinstance(item, dict):
                if set(item) == {"sha256", "receipt"}:
                    require(all(re.fullmatch(r"[0-9a-f]{64}", digest) for digest in item.values()),
                            "Invalid official evidence identifier")
                    receipt = archive / "receipts" / (item["receipt"] + ".json")
                    require(sha256(archive / "objects" / item["sha256"]) == item["sha256"]
                            and sha256(receipt) == item["receipt"]
                            and json.loads(receipt.read_text()).get("sha256") == item["sha256"],
                            "Official evidence changed or receipt points to another response")
                else:
                    for value in item.values():
                        verify(value)
            elif isinstance(item, list):
                for row in item:
                    verify(row)

        verify(payload)
    return payload


def actions_for_window(snapshot, code, days, *, listing, delisting, isin=None, share_class=None, market=None):
    listing = str(listing)
    delisting = str(delisting) if delisting is not None else None
    start, end = days[0].date().isoformat(), days[-1].date().isoformat()
    found = [item for item in snapshot["securities"]
             if item["security"]["code"] == code and item["security"]["listing"] == listing
             and item["security"]["delisting"] == delisting
             and (isin is None or item["security"]["isin"] == isin)
             and (share_class is None or item["security"]["share_class"] == share_class)
             and (market is None or item["security"]["market"] == market)]
    require(len(found) == 1, f"{code}: official snapshot lacks the unique KRX listing interval")
    row = found[0]
    security = Security(**row["security"])
    require(security.active(start) and security.active(end), f"{code}: prices lie outside the KRX listing interval")
    require(row["status"] == "covered", f"{code}: official actions {row['status']}; inspect the snapshot")
    require(row["start"] <= start <= end <= row["end"],
            f"{code}: price window exceeds official action coverage")
    for source in SOURCES:
        spans = sorted((c["start"], c["end"]) for c in row["coverage"] if c["source"] == source and c["pages"])
        require(spans and spans[0][0] <= start and spans[-1][1] >= end
                and all((date.fromisoformat(right[0]) - date.fromisoformat(left[1])).days == 1
                        for left, right in zip(spans, spans[1:])),
                f"{code}: incomplete {source} coverage")
    actions = []
    for raw in row["actions"]:
        fields = dict(raw)
        for key in ("ratio_evidence", "dates_evidence", "implementation_evidence"):
            evidence = fields[key]
            fields[key] = FieldEvidence(evidence["accession"], Evidence(**evidence["source"]), evidence["field"])
        if fields["shares"] is not None:
            fields["shares"] = tuple(fields["shares"])
        if fields.get("auction") is not None:
            auction_fields = fields["auction"]
            evidence = auction_fields["evidence"]
            fields["auction"] = Auction(auction_fields["date"], auction_fields["evaluation"],
                                        auction_fields["low"], auction_fields["high"],
                                        FieldEvidence(evidence["accession"], Evidence(**evidence["source"]), evidence["field"]),
                                        auction_fields["company"])
        action = Action(**fields)
        require(action.kind in {"split", "merge", "reduction", "bonus", "reference_reset"}
                and action.factor > 0 and (action.factor == 1) == (action.kind == "reference_reset"),
                f"{code}: invalid verified unit ratio")
        if start <= action.ex_date <= end:
            actions.append(action)
    return actions


def decision_kind(title):
    title = re.sub(r"\s", "", title)
    for name, kind in (("주식분할결정", "split"), ("주식병합결정", "merge"),
                       ("감자결정", "reduction"), ("무상증자결정", "bonus")):
        if name in title:
            return kind
    return None


def implementation_kind(title):
    title = re.sub(r"\s", "", title)
    if "권리락(무상증자)" in title:
        return "bonus"
    if "변경상장" in title or "상장안내(감자" in title:
        if "액면분할" in title:
            return "split"
        if "액면병합" in title:
            return "merge"
        if any(term in title for term in ("감자", "주식병합", "자본감소")):
            return "reduction"
    return None


def official_date(value):
    value = re.sub(r"\s", "", value).replace(".", "-")
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        return date.fromisoformat(value).isoformat()
    y, m, d = one(r"^(\d{4})년(\d{1,2})월(\d{1,2})일$", value, "Unsupported official date")
    return date(int(y), int(m), int(d)).isoformat()


def deal_table(html):
    table = TableRows()
    table.feed(html)
    return table.rows


def parse_decision(security, filing, body, family, detail=None):
    kind = decision_kind(filing.title)
    has_parent = any(acc != filing.accession for acc, _ in family)
    roots = [acc for acc, title in family
             if decision_kind(title) == kind and not re.search(r"정정|철회|취소", title)]
    require(len(roots) == 1 and (has_parent or "정정" not in filing.title),
            "DART decision family missing a unique original")
    require(security.issuer_code == filing.stock_code or filing.stock_code == "",
            "DART filing stock code differs from issuer")
    is_withdrawal = "철회" in filing.title or filing.note == "철"
    is_cancelled = bool(re.search(r"(?:분할|병합|증자|감자)\s*결정\s*취소", filing.title))
    if is_cancelled:
        require(has_parent and "취소" in body.text(), "Corporate action cancellation lacks its decision family")
        ref = FieldEvidence(filing.accession, body.evidence, "결정 취소")
        return Decision(filing.accession, filing.published, roots[0], kind, Fraction(1), None, None, ref, ref, True)
    require(not is_withdrawal, "DART document withdrawn; corporate action status needs review")
    require(not any(term in re.sub(r"\s+", "", filing.title) for term in ("유무상증자", "유상및무상증자")),
            "Combined capital issue needs review")
    allocation = None
    if kind in {"bonus", "reduction"}:
        require(detail is not None, "DART structured details lack this decision revision")
        fields, details_evidence = detail
        require(fields["rcept_no"] == filing.accession, "DART detail revision differs from filing")
        if kind == "bonus":
            key = "nstk_ascnt_ps_ostk" if security.share_class == "common" else "nstk_ascnt_ps_estk"
            factor = Fraction(fields[key].replace(",", "")) + 1
            listing = official_date(fields["nstk_lstprd"])
            allocation = official_date(fields["nstk_asstd"])
            ratio_field, date_field = key, "nstk_lstprd,nstk_asstd"
        else:
            require(security.share_class == "common", "Unsupported preferred-share reduction")
            common_terms = fields["cr_mth"].split("우선주식")[0]
            unchanged_units = (
                "보통주식" in common_terms and "무상 액면감소" in common_terms
                and re.search(r"주당\s*액면가액.*감액", common_terms, re.DOTALL)
                and fields["bfcr_tisstk_ostk"] == fields["atcr_tisstk_ostk"]
            )
            if unchanged_units:
                kind, factor = "reference_reset", Fraction(1)
            else:
                old, new = one(r"보통주식\s*([\d,]+)주[^.\r\n]*?보통주식\s*(?:각\s*)?([\d,]+)주로\s*병합",
                               common_terms, "Reduction has no explicit common-share exchange ratio")
                factor = Fraction(int(new.replace(",", "")), int(old.replace(",", "")))
            listing = official_date(fields["crsc_nstklstprd"])
            ratio_field, date_field = "cr_mth", "crsc_nstklstprd"
    else:
        text_columns = deal_table(body.text())
        # Only the labelled, complete decision rows count. The correction table's
        # date row has three cells with old/new dates, and is excluded here.
        old, new = one(r"(?m)^([\d,]+)\|([\d,]+)$", "\n".join(
            "|".join(row[1:]) for row in text_columns if len(row) == 3
            and re.sub(r"\s+", "", row[0]) == "1주당가액(원)"
        ), "Unique DART before/after face values required")
        amounts = [row[1] for row in text_columns if len(row) == 2
                   and re.sub(r"\s+", "", row[0]) in {"신주권상장예정일", "신주상장예정일"}]
        require(len(amounts) == 1, "Unique DART scheduled listing date required")
        listing = official_date(amounts[0])
        factor = Fraction(int(old.replace(",", "")), int(new.replace(",", "")))
        if security.share_class == "preferred":
            require(any(any("종류주식" in cell for cell in row[:-2]) and len(row) >= 3
                        and all(re.fullmatch(r"[\d,]+", num) for num in row[-2:]) for row in text_columns),
                    "DART decision does not identify converted preferred shares")
        details_evidence = body.evidence
        ratio_field, date_field = "1주당 가액(원) 변경전/후", "신주권상장예정일"
    require((factor > 1 if kind in {"split", "bonus"} else 0 < factor <= 1),
            "DART ratio has an unexpected direction")
    return Decision(filing.accession, filing.published, roots[0], kind, factor, listing, allocation,
                    FieldEvidence(filing.accession, details_evidence, ratio_field),
                    FieldEvidence(filing.accession, details_evidence, date_field))


def parse_implementation(security, filing, body):
    kind = implementation_kind(filing.title)
    html = body.text()
    require(not re.search(r"정정|철회|취소", filing.title), "KIND notice revision requires review")
    if kind == "bonus":
        values = re.findall(r'<span class="xforms_input"[^>]*>([^<]+)</span>', html)
        require(len(values) == 6, "Unsupported KIND rights notice table")
        _, share_class, code, base, ex_date, reason = map(str.strip, values)
        require(code == "A" + security.code and reason == "무상증자"
                and share_class == ("보통주식" if security.share_class == "common" else "종류주식"),
                "KIND rights notice security or reason differs")
        return Implementation(kind, official_date(ex_date),
                              FieldEvidence(filing.accession, body.evidence, "권리락일·기준가·단축코드"),
                              base=int(base.replace(",", "")))

    text = unescape(re.sub(r"<[^>]+>", " ", html))
    records = re.findall(
        r"(?:(보통주|[0-9]*우선주)[ \t]+)?표준코드\s*:\s*([A-Z]{2}[0-9A-Z]{9}[0-9])"
        r"\s*\(\s*단축코드\s*:\s*A([0-9A-Z]{6})\s*\)", text,
    )
    classes = [share_class for share_class, isin, code in records if (isin, code) == (security.isin, security.code)]
    require(len(classes) == 1, "KIND listing does not identify one matching KRX security")
    group = "보통주" if security.share_class == "common" else r"[0-9]*우선주"
    if label := classes[0]:
        require(re.fullmatch(group, label), "KIND listing code, ISIN and share class disagree")
        group = re.escape(label)
    else:
        require(len(records) == 1, "KIND joint listing does not identify the security's share class")
    if kind == "reduction" and "변경사항 없음" in text:
        units = one(rf"주식의\s*종류와\s*수\(변경사항 없음\)\s*▶\s*기명식\s*{group}\s+([\d,]+)주",
                    text, "KIND unchanged share count is ambiguous")
        shares = (int(units.replace(",", "")),) * 2
        kind = "reference_reset"
    else:
        old, new = one(rf"기명식\s*{group}\s+([\d,]+)주\s*(?:\([^)]*\)\s*)?→\s*([\d,]+)주", text,
                       "KIND listing share class or quantities are ambiguous")
        shares = tuple(int(value.replace(",", "")) for value in (old, new))
    raw_date = r"(?:\d{4}년\s*\d{1,2}월\s*\d{1,2}일|\d{4}[.]\d{2}[.]\d{2})"
    listed = official_date(one(r"변경상장일\s*:\s*(" + raw_date + ")", text, "KIND actual listing date missing"))
    resumed = re.findall(r"변경상장일\s*\((" + raw_date + r")\)\s*에\s*매매거래정지(?:가)?\s*해제", text)
    require(not resumed or [listed] == [official_date(value) for value in resumed], "KIND resumption date differs")
    company = re.sub(r"\s+|\(주\)", "", one(r"◎\s*([^\n]+?)\s*변경상장",
                                                         text, "KIND listing company missing"))
    if kind == "reference_reset":
        return Implementation(kind, listed, FieldEvidence(filing.accession, body.evidence,
                              "변경상장일·표준코드·주식수 변경사항 없음"), factor=Fraction(1), shares=shares, company=company)
    if kind == "reduction":
        one(r"1주의\s*금액\s*:\s*[\d,]+원\s*(?:④|$)", text, "Unsupported KIND reduction face-value field")
        return Implementation(kind, listed, FieldEvidence(filing.accession, body.evidence, "변경상장일·표준코드·주식수"),
                              factor=Fraction(1), shares=shares, company=company)
    old, new = one(r"1주의\s*금액\s*:\s*([\d,]+)원\s*→\s*([\d,]+)원", text,
                   "KIND before/after face amounts missing")
    factor = Fraction(int(old.replace(",", "")), int(new.replace(",", "")))
    return Implementation(kind, listed, FieldEvidence(filing.accession, body.evidence, "변경상장일·표준코드·주식수"),
                          factor=factor, shares=shares, company=company)


def parse_auction(security, filing, body):
    rows = deal_table(body.text())
    companies = [re.sub(r"\s+|\(주\)", "", row[1]) for row in rows
                 if len(row) == 2 and row[0] == "1. 회사명"]
    require(len(companies) == 1 and security.share_class == "common", "Unsupported KRX auction security")
    values = [row[1:] for row in rows if len(row) == 4 and row[0] == "보통주식"]
    dates = [row[1] for row in rows if len(row) == 2 and "적용일" in row[0]]
    require(len(values) == len(dates) == 1 and any(
        "최초가격이 기준가격이 됨" in " ".join(row) for row in rows
    ), "Unsupported KRX auction notice")
    evaluation, high, low = (int(value.replace(",", "")) for value in values[0])
    require(0 < low <= evaluation <= high, "Invalid KRX auction bounds")
    return Auction(official_date(dates[0]), evaluation, low, high,
                   FieldEvidence(filing.accession, body.evidence, "평가가격·최저/최고호가·적용일"), companies[0])


def reconcile(security, decisions, notices, start, end, sessions, auctions=()):
    """Use one current DART revision and one compatible KRX notice for each event."""
    families = {}
    for decision in decisions:
        families.setdefault(decision.family, []).append(decision)
    actions, pending, used = [], [], set()
    latest = []
    for family, group in families.items():
        ordered = sorted(group, key=lambda d: d.published, reverse=True)
        if len(ordered) > 1 and ordered[0].published == ordered[1].published:
            pending.append(f"{family}: same-day decision revision order needs review")
        else:
            latest.append(ordered[0])
    for notice in notices:
        if not start <= notice.ex_date <= end:
            continue
        if notice.ex_date not in sessions or not security.active(notice.ex_date):
            pending.append(f"{notice.evidence.accession}: implementation outside KRX session or listing")
            continue
        if notice.kind == "bonus":
            next_day = sessions.get(notice.ex_date)
            candidates = [d for d in latest if not d.cancelled and d.kind == "bonus"
                          and next_day is not None and d.allocation == next_day]
        else:
            candidates = [d for d in latest if not d.cancelled and d.kind == notice.kind
                          and d.listing == notice.ex_date and notice.factor == (1 if d.kind == "reduction" else d.factor)]
        if len(candidates) != 1:
            pending.append(f"{notice.evidence.accession}: expected one official matching decision, found {len(candidates)}")
            continue
        decision = candidates[0]
        if decision.family in used:
            pending.append(f"{decision.family}: multiple implementation notices")
            continue
        auction = None
        if decision.kind in {"reduction", "reference_reset"}:
            auctions_for_date = [item for item in auctions if item.date == notice.ex_date and item.company == notice.company]
            if len(auctions_for_date) != 1:
                pending.append(f"{decision.family}: unique KRX reduction auction notice required")
                continue
            auction = auctions_for_date[0]
        used.add(decision.family)
        actions.append(Action(
            f"{security.isin}:{decision.family}", decision.accession, decision.kind, notice.ex_date,
            decision.factor.numerator, decision.factor.denominator, decision.listing, notice.base,
            notice.shares, decision.ratio, decision.dates, notice.evidence, auction, security.market,
        ))
    for decision in latest:
        effective = decision.allocation if decision.kind == "bonus" else decision.listing
        if decision.cancelled:
            earlier = [d for d in families[decision.family] if not d.cancelled]
            cancelled_on = decision.published.isoformat()
            previous_session = {following: day for day, following in sessions.items() if following}
            effective_dates = [previous_session.get(d.allocation) if d.kind == "bonus" else d.listing for d in earlier]
            if not effective_dates or any(not day or day <= cancelled_on for day in effective_dates):
                pending.append(f"{decision.family}: cancellation at or after scheduled implementation needs review")
        elif decision.family not in used and effective and start <= effective <= end:
            pending.append(f"{decision.family}: official implementation missing")
    if len(actions) != len({action.ex_date for action in actions}):
        pending.append("Multiple unit events on the same KRX session")
    return sorted(actions, key=lambda a: a.ex_date), pending


def compatible_base(reference, converted, day, market):
    """Allow one KRX tick for official rounded prices."""
    if day < "2023-01-25":
        thresholds = ((1_000, 1), (5_000, 5), (10_000, 10), (50_000, 50), (100_000, 100))
    else:
        thresholds = ((2_000, 1), (5_000, 5), (20_000, 10), (50_000, 50), (200_000, 100))
    thresholds += ((math.inf, 100),) if market == "KOSDAQ" else ((500_000, 500), (math.inf, 1_000))
    tick = next(tick for ceiling, tick in thresholds if converted < ceiling)
    return abs(reference - converted) <= tick
