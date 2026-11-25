"""Resolve KRX observations against official facts, without activating training boundaries."""

import math
import re
from collections import defaultdict
from dataclasses import dataclass
from enum import StrEnum
from fractions import Fraction

import pandas as pd

from shared.io import canonical_hash

from .actions import Action, FieldEvidence, compatible_base, tick_size
from .calendar import scheduled_sessions
from .disclosures import require
from .events import _observations, verify_action
from .market_notices import SecurityKey, normal_company
from .validation import validate_krx_raw


class Resolution(StrEnum):
    UNIT_CHANGE = "unit_change"
    BONUS = "bonus"
    RIGHTS = "rights"
    REFERENCE_RESET = "reference_reset"
    TICK_ROUNDING = "tick_rounding"
    SHARES_ONLY = "shares_only"
    SEGMENT_BREAK = "segment_break"
    SPAC_PREMERGER = "spac_premerger"


ADJUSTMENTS = {
    Resolution.UNIT_CHANGE, Resolution.BONUS, Resolution.RIGHTS,
    Resolution.REFERENCE_RESET, Resolution.TICK_ROUNDING,
}
ACTION_KIND = {"split": Resolution.UNIT_CHANGE, "merge": Resolution.UNIT_CHANGE,
               "reduction": Resolution.UNIT_CHANGE, "bonus": Resolution.BONUS,
               "reference_reset": Resolution.REFERENCE_RESET}
STRUCTURAL = re.compile(r"인적분할|회사분할|분할합병|분할\(존속\)|분할존속")
MERGER = re.compile(r"합병")
DISALLOWED_LISTING = re.compile(r"분할|병합|감자|합병|액면|무상증자|주식배당")
RESUME = re.compile(r"장기간매매정지|장기매매거래정지|장기거래정지|매매거래재개")
RIGHTS = {"유상증자", "권리락(유상증자)", "주주배정유상증자", "권리락(주주배정유상증자)"}
RIGHTS_FORMS = {"70766", "99301", "32101"}
SPAC = re.compile(r"기업인수목적|스팩|(?<![A-Z])SPAC(?![A-Z])", re.I)
BONUS = {"무상증자", "권리락(무상증자)"}
DIVIDEND = {"주식배당", "배당락(주식배당)"}


@dataclass(frozen=True)
class Candidate:
    security: SecurityKey
    date: str
    prev_date: str
    prev_close: int
    base_price: int
    shares_before: int
    shares_after: int
    paused: bool

    @property
    def moved(self):
        return self.prev_close != self.base_price


@dataclass(frozen=True)
class ResolvedEvent:
    security: SecurityKey
    date: str
    kind: Resolution
    reason: str
    evidence: tuple[FieldEvidence, ...] = ()
    price_factor: Fraction | None = None
    volume_factor: Fraction | None = None
    review: bool = False

    def __post_init__(self):
        required = self.kind in ADJUSTMENTS
        require((self.price_factor is not None) == (self.volume_factor is not None) == required
                and (not required or self.price_factor > 0 and self.volume_factor > 0),
                "Resolution factors do not match its type")


@dataclass(frozen=True)
class WindowLedger:
    candidates: tuple[Candidate, ...]
    resolutions: tuple[ResolvedEvent, ...]
    incomplete: tuple[str, ...]


def raw_window_fingerprint(raw, sessions):
    """Match market-wide and per-security KRX captures independently of file format."""
    checked = validate_krx_raw(raw, pd.DatetimeIndex(sessions))
    return canonical_hash([[day.date().isoformat(), *map(int, values)]
                           for day, *values in checked.itertuples(index=False, name=None)])


def _facts_evidence(notices):
    return tuple(dict.fromkeys(FieldEvidence(n.accession, source, f"KIND {n.form}/{n.facts.section}")
                               for n in notices for source in n.evidence))


def _action_evidence(action):
    refs = (action.ratio_evidence, action.dates_evidence, action.implementation_evidence)
    return (*refs, action.auction.evidence) if action.auction else refs


def _observed_candidate(security, raw, days, at, base):
    previous, current = raw.iloc[at - 1], raw.iloc[at]
    quantities = (previous.RawClose, base.iloc[at], previous.ListedShares, current.ListedShares)
    require(all(pd.notna(value) and int(value) == value and value > 0 for value in quantities),
            f"{security.code} {days[at]:%Y-%m-%d}: invalid KRX prices or share quantities")
    return Candidate(security, days[at].date().isoformat(), days[at - 1].date().isoformat(),
                     *map(int, quantities),
                     previous.RawVolume == 0 or previous.RawOpen == previous.RawHigh == previous.RawLow == 0)


def observe_candidates(security, raw, days):
    days, base, candidates = _observations(raw, days)
    return tuple(_observed_candidate(security, raw, days, at, base) for at in candidates.to_numpy().nonzero()[0])


def _reason(notice):
    return re.sub(r"\s+", "", notice.facts.reason)


def _result(security, day, kind, reason, notices=(), *, factors=None, evidence=(), review=False):
    price, volume = factors if factors is not None else (None, None)
    return ResolvedEvent(security, day, kind, reason, tuple(dict.fromkeys((*evidence, *_facts_evidence(notices)))),
                      price, volume, review)


def _official_bonus(candidate, terms, listing_notice, market, raw, days):
    record = terms.facts
    if record.shares_before != candidate.shares_before:
        return None
    sessions = scheduled_sessions(pd.Timestamp(candidate.date), pd.Timestamp(record.effective))
    if len(sessions) != 2 or (record.kind == "bonus_terms" and sessions[-1].date().isoformat() != record.effective):
        return None
    ratio = 1 + record.ratio
    # Treasury shares can change the exchange reference price without changing what each holder receives.
    diluted = Fraction(record.shares_before + record.added_shares, record.shares_before)
    if not any(compatible_base(candidate.base_price, Fraction(candidate.prev_close) / expected, candidate.date, market)
               for expected in (ratio, diluted)):
        return None
    if listing_notice and (len(listing_notice) != 1 or listing_notice[0].facts.added_shares != record.added_shares):
        return None
    listing_day = listing_notice[0].facts.effective if listing_notice else record.listing
    if listing_day and pd.Timestamp(listing_day) in days:
        at = days.get_loc(pd.Timestamp(listing_day))
        if at == 0 or listing_day <= candidate.date:
            return None
        before, after = raw.ListedShares.iloc[at - 1:at + 1]
        if after - before != record.added_shares or (
            listing_notice and listing_notice[0].facts.shares_after not in {None, after}
        ):
            return None
    return 1 / ratio, ratio


def _valid_notices(notices):
    final_doc_nos = {notice.document_no for notice in notices if notice.final}
    return [notice for notice in notices if notice.final or not (final_doc_nos & set(notice.family))]


def _spac_issuer(merger, notices):
    return SPAC.search(merger.facts.company) or any(
        notice.facts.kind == "rename" and SPAC.search(notice.facts.company) for notice in notices
    )


def _spac_merger(raw, at, merger):
    if merger.facts.kind != "listing" or merger.facts.added_shares is None:
        return False
    if not at:
        return False
    before, after = raw.ListedShares.iloc[at - 1:at + 1]
    return (merger.facts.shares_after in {None, after}
            and before + merger.facts.added_shares == after)


def _combined_reference_adjustment(notice):
    reason = _reason(notice)
    return bool(re.search(r"액면분할|액면병합", reason) and re.search(r"무상증자|권리락|주식배당", reason))


def _compatible_action_notices(action, notices, candidate):
    for notice in notices:
        fact = notice.facts
        if fact.kind == "ex_price":
            if action.kind != "bonus" or _reason(notice) not in BONUS or fact.base != action.base:
                return False
        elif fact.kind == "auction":
            if action.auction is None or (fact.evaluation, fact.low, fact.high) != (
                action.auction.evaluation, action.auction.low, action.auction.high
            ):
                return False
        elif fact.kind == "listing_price":
            if action.kind == "bonus" or fact.base != candidate.base_price or _combined_reference_adjustment(notice):
                return False
        elif fact.kind == "listing":
            if action.kind == "bonus" or any((
                fact.shares_before not in {None, candidate.shares_before},
                fact.shares_after not in {None, candidate.shares_after},
                fact.added_shares not in {None, candidate.shares_after - candidate.shares_before},
                fact.par_before is not None and fact.par_after is not None and action.kind in {"split", "merge"}
                and Fraction(fact.par_before, fact.par_after) != action.factor,
            )):
                return False
    return True


def _official_transfer(security, raw, at, candidate, events):
    if "Market" not in raw or raw.Market.iloc[at - 1] == raw.Market.iloc[at]:
        return False
    prices = [notice for notice in events if notice.facts.kind in {"listing_price", "auction"}]
    if len(prices) != 1:
        return False
    notice = prices[0]
    facts, reason = notice.facts, _reason(notice)
    if facts.base != candidate.base_price and not (
        facts.evaluation is not None and facts.low <= candidate.base_price <= facts.high
        and raw.RawOpen.iloc[at] == candidate.base_price
    ):
        return False
    if "이전상장" in reason:
        return (facts.previous_market in {None, raw.Market.iloc[at - 1]}
                and facts.previous_close in {None, candidate.prev_close})
    return ("신규상장" in reason and "ISU_ABBRV" in raw
            and normal_company(raw.ISU_ABBRV.iloc[at - 1]) == normal_company(raw.ISU_ABBRV.iloc[at])
            and any(n.facts.kind == "new_listing" and n.facts.isin == security.isin and n.facts.code == security.code
                    and n.facts.shares_after == candidate.shares_after for n in events))


def _resolve_day(security, raw, days, at, candidate, action, notices, terms, all_listings, complete, blocked, unparsed):
    day = days[at].date().isoformat()
    final = [notice for notice in notices if notice.final]
    nonfinal = len(final) != len(notices)
    events = [notice for notice in final if notice.facts.kind != "rename"]
    action_evidence = _action_evidence(action) if action else ()
    if any(STRUCTURAL.search(_reason(notice)) for notice in events):
        return _result(security, day, Resolution.SEGMENT_BREAK, "official_division", final, evidence=action_evidence)
    merger = [notice for notice in events if notice.facts.kind in {"listing", "auction"} and MERGER.search(_reason(notice))]
    if merger:
        spac = [notice for notice in merger if _spac_issuer(notice, final)]
        if spac:
            if sum(_spac_merger(raw, at, notice) for notice in spac) == 1:
                return _result(security, day, Resolution.SPAC_PREMERGER, "official_spac_merger_listing", final,
                               evidence=action_evidence)
            return _result(security, day, Resolution.SEGMENT_BREAK, "spac_merger_share_observation_disagrees", final,
                           evidence=action_evidence, review=True)
        return _result(security, day, Resolution.SEGMENT_BREAK, "official_merger", final, evidence=action_evidence)
    if candidate is None:
        return None
    if blocked:
        return None
    if unparsed:
        if not complete:
            return None
        return _result(security, day, Resolution.SEGMENT_BREAK, "official_notice_format_requires_review", notices,
                       evidence=(*action_evidence, *unparsed), review=True)
    if not nonfinal and _official_transfer(security, raw, at, candidate, events):
        if action or any(n.facts.kind in {"ex_price", "listing"} and DISALLOWED_LISTING.search(_reason(n)) for n in events):
            return _result(security, day, Resolution.SEGMENT_BREAK, "transfer_conflicts_with_unit_event", final,
                           evidence=action_evidence, review=True)
        return _result(security, day, Resolution.REFERENCE_RESET, "official_continuous_transfer", final,
                       factors=(Fraction(1), Fraction(1)))
    if action is not None and not nonfinal:
        try:
            verify_action(security.code, raw, days, at, candidate.base_price, action)
        except ValueError:
            return _result(security, day, Resolution.SEGMENT_BREAK, "official_action_disagrees_with_krx", final,
                           evidence=action_evidence, review=True)
        action_kind = ACTION_KIND[action.kind]
        if _compatible_action_notices(action, events, candidate):
            return _result(security, day, action_kind, "verified_dart_and_kind_action", final,
                           factors=(1 / action.factor, action.factor), evidence=action_evidence)
        return _result(security, day, Resolution.SEGMENT_BREAK, "official_action_conflicts_with_kind_notice", final,
                       evidence=action_evidence, review=True)

    prices = [notice for notice in events if notice.facts.kind in {"ex_price", "auction", "listing_price"}]
    listings = [notice for notice in events if notice.facts.kind == "listing"]
    market = raw.Market.iloc[at] if "Market" in raw else security.market
    if not nonfinal and len(prices) == 1:
        notice = prices[0]
        facts, reason = notice.facts, _reason(notice)
        unit_unchanged = candidate.shares_before == candidate.shares_after and not listings
        if facts.kind == "ex_price" and facts.base == candidate.base_price and unit_unchanged:
            if notice.form in RIGHTS_FORMS and reason in RIGHTS and candidate.moved:
                return _result(security, day, Resolution.RIGHTS, "official_paid_rights_reference", final,
                               factors=(Fraction(candidate.base_price, candidate.prev_close), Fraction(1)))
            term_kind = "dividend_terms" if reason in DIVIDEND else "bonus_terms" if reason in BONUS else None
            if term_kind:
                matching = []
                for term in terms:
                    if (not term.final or term.facts.kind != term_kind or term.facts.effective < day
                        or term.company_id and notice.company_id and term.company_id != notice.company_id):
                        continue
                    later = [item for item in all_listings.get(term.facts.listing, ())
                             if item.final and item.facts.kind == "listing" and "무상증자" in _reason(item)]
                    if factors := _official_bonus(candidate, term, later, market, raw, days):
                        matching.append((term, later, factors))
                if len(matching) == 1:
                    term, later, factors = matching[0]
                    return _result(security, day, Resolution.BONUS, term_kind, [*final, term, *later], factors=factors)
        if (facts.kind == "auction" and unit_unchanged and RESUME.search(reason) and candidate.paused
            and facts.evaluation == candidate.prev_close and facts.low <= candidate.base_price <= facts.high
            and raw.RawOpen.iloc[at] == candidate.base_price and raw.RawVolume.iloc[at] > 0):
            return _result(security, day, Resolution.REFERENCE_RESET, "official_resumption_auction", final,
                           factors=(Fraction(1), Fraction(1)))

    if not nonfinal and all(notice.facts.kind == "listing_price" and notice.facts.base == candidate.base_price
                            and not _combined_reference_adjustment(notice) for notice in prices) and len(listings) == 1:
        listed = listings[0]
        facts = listed.facts
        if (facts.par_before and facts.par_after and facts.par_before != facts.par_after
            and re.search(r"액면분할|액면병합", _reason(listed))
            and facts.shares_before in {None, candidate.shares_before} and facts.shares_after == candidate.shares_after):
            ratio = Fraction(facts.par_before, facts.par_after)
            if (ratio * candidate.shares_before == candidate.shares_after
                and compatible_base(candidate.base_price, Fraction(candidate.prev_close) / ratio, day, market)):
                return _result(security, day, Resolution.UNIT_CHANGE, "official_kind_face_value_and_shares", final,
                               factors=(1 / ratio, ratio))
    current_halt = raw.RawVolume.iloc[at] == 0 and raw[["RawOpen", "RawHigh", "RawLow"]].iloc[at].eq(0).all()
    if (not nonfinal and not prices and listings and candidate.paused and current_halt and not candidate.moved
        and all(not DISALLOWED_LISTING.search(_reason(notice)) for notice in listings)):
        amounts = [notice.facts.added_shares for notice in listings]
        after = {notice.facts.shares_after for notice in listings if notice.facts.shares_after is not None}
        before = {notice.facts.shares_before for notice in listings if notice.facts.shares_before is not None}
        if ((not after or after == {candidate.shares_after}) and (not before or before == {candidate.shares_before})
            and (all(amount is not None for amount in amounts)
                 and sum(amounts) == candidate.shares_after - candidate.shares_before
                 or len(listings) == 1 and after == {candidate.shares_after} and amounts == [None])):
            return _result(security, day, Resolution.SHARES_ONLY, "official_listing_share_change_at_same_reference", final)

    if not complete:
        return None
    tick = tick_size(candidate.prev_close, day, market)
    if (not events and not nonfinal and action is None and candidate.shares_before == candidate.shares_after
        and 0 < candidate.base_price - candidate.prev_close < tick
        and candidate.base_price == math.ceil(Fraction(candidate.prev_close, tick)) * tick):
        return _result(security, day, Resolution.TICK_ROUNDING, "krx_reference_rounded_up_to_tick",
                       factors=(Fraction(1), Fraction(1)))
    reason = "official_facts_conflict_or_lack_terms" if notices else "completed_search_without_official_proof"
    return _result(security, day, Resolution.SEGMENT_BREAK, reason, notices,
                   evidence=action_evidence, review=True)


def resolve_events(security, raw, expected_dates, notices, *, actions=(), coverage_complete=False,
                   covered_dates=frozenset(), blocked_dates=frozenset(), unparsed_dates=None, transfer_anchor=None,
                   transfer_source=None):
    """Produce one canonical outcome per observed candidate and confirmed structure date."""
    days, base, mask = _observations(raw, expected_dates)
    require(not days.empty and all(security.active(day.date().isoformat()) for day in days),
            "KRX prices lie outside the official listing interval")
    require(all(notice.security == security for notice in notices), "KIND notices mix listing identities")
    unparsed_dates = unparsed_dates or {}
    notices = _valid_notices(notices)
    terms = tuple(n for n in notices if n.facts.kind.endswith("_terms"))
    on_date = defaultdict(list)
    for notice in notices:
        if notice not in terms:
            on_date[notice.facts.effective].append(notice)
    first_day = days[0].date().isoformat()
    require(transfer_source is None or transfer_anchor is not None, "Missing former KRX trading session")
    if transfer_anchor is not None:
        require(len(transfer_anchor) == 1 and transfer_anchor.Date.iloc[0] < days[0]
                and transfer_anchor.Market.iloc[0] != raw.Market.iloc[0]
                and transfer_anchor.Code.iloc[0] == security.code
                and len(scheduled_sessions(transfer_anchor.Date.iloc[0], days[0])) == 2, "Invalid KRX transfer anchor")
        first_session = on_date.get(first_day, [])
        prior_verified = transfer_source is not None
        if prior_verified:
            require(transfer_source.code == security.code and transfer_source.market == transfer_anchor.Market.iloc[0]
                    and transfer_source.active(transfer_anchor.Date.iloc[0].date().isoformat())
                    and transfer_source.delisting == first_day, "Former KRX security does not cover the transfer anchor")
        elif any(n.final and n.facts.kind in {"listing_price", "auction"} for n in first_session):
            pair = pd.concat([transfer_anchor, raw.iloc[:1]], ignore_index=True)
            pair_days = pd.DatetimeIndex(pair.Date)
            pair_base = pair.RawClose - pair.RawChange
            observation = _observed_candidate(security, pair, pair_days, 1, pair_base)
            prior_verified = _official_transfer(security, pair, 1, observation, [n for n in first_session if n.final])
        if prior_verified:
            raw = pd.concat([transfer_anchor, raw], ignore_index=True)
            days, base, mask = _observations(raw, days.insert(0, transfer_anchor.Date.iloc[0]))
    indexed_actions: dict[str, Action] = {action.ex_date: action for action in actions}
    require(len(indexed_actions) == len(actions) and all(action.market == security.market
            and action.event_id.startswith(f"{security.isin}:") for action in actions),
            "Verified actions mix listing identities or effective dates")
    candidates, resolved, incomplete = [], [], []
    by_date = {day.date().isoformat(): at for at, day in enumerate(days)}
    outside = sorted(day for day in set(indexed_actions) | set(on_date)
                     if first_day <= day <= max(by_date) and day not in by_date)
    for day in outside:
        if day in indexed_actions or any(
            STRUCTURAL.search(_reason(notice)) or MERGER.search(_reason(notice)) for notice in on_date[day]
        ):
            incomplete.append(day)
    dates = set(on_date) | set(indexed_actions) | {days[at].date().isoformat() for at in mask.to_numpy().nonzero()[0]}
    if transfer_source and transfer_source.isin != security.isin:
        dates.add(first_day)
    for day in sorted(day for day in dates & by_date.keys() if day >= first_day):
        at = by_date[day]
        observed = bool(mask.iloc[at])
        anchored_transfer = day == first_day and at == 1
        candidate = (_observed_candidate(security, raw, days, at, base)
                     if at and (observed or anchored_transfer or day in indexed_actions) else None)
        if observed:
            candidates.append(candidate)
        current = on_date.get(day, [])
        complete = coverage_complete or day in covered_dates
        row = _resolve_day(security, raw, days, at, candidate, indexed_actions.get(day), current,
                           terms, on_date, complete, day in blocked_dates, unparsed_dates.get(day, ()))
        if (anchored_transfer and transfer_source and transfer_source.isin != security.isin
                and (row is None or row.kind in ADJUSTMENTS or row.kind == Resolution.SHARES_ONLY)):
            row = _result(security, day, Resolution.SEGMENT_BREAK, "separate_verified_listing_units", current)
        if row is not None and row.review and not observed:
            if not at:
                incomplete.append(day)
                continue
            candidates.append(candidate or _observed_candidate(security, raw, days, at, base))
        if row is not None:
            resolved.append(row)
        elif observed or day in indexed_actions or (current and day in blocked_dates):
            incomplete.append(day)
    return WindowLedger(tuple(candidates), tuple(resolved), tuple(incomplete))


def adjustment_events(resolutions):
    """Expose factors in the existing apply_events input shape."""
    rows = [{"Code": row.security.code, "ExDate": pd.Timestamp(row.date),
             "PriceFactor": float(row.price_factor), "VolumeFactor": float(row.volume_factor)}
            for row in resolutions if row.kind in ADJUSTMENTS]
    return pd.DataFrame(rows, columns=["Code", "ExDate", "PriceFactor", "VolumeFactor"])
