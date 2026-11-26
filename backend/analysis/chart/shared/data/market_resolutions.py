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
from .market_notices import SecurityKey, kind_topic, normal_company, superseded_merger_facts
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
ISSUER_MERGER_REASON = "official_issuer_merger"
STRUCTURAL_REVIEW_REASON = "superseded_implementation_requires_review"
DISALLOWED_LISTING = re.compile(r"분할|병합|감자|합병|액면|무상증자|주식배당")
RESUME = re.compile(r"장기간매매정지|장기매매거래정지|장기거래정지|매매거래재개")
RIGHTS = {"유상증자", "권리락(유상증자)", "주주배정유상증자", "권리락(주주배정유상증자)"}
RIGHTS_FORMS = {"70766", "99301", "32101"}
SPAC = re.compile(r"기업인수목적|스팩|(?<![A-Z])SPAC(?![A-Z])", re.I)
BONUS = {"무상증자", "권리락(무상증자)"}
DIVIDEND = {"주식배당", "배당락(주식배당)"}
PAR_CHANGE = re.compile(r"액면분할|액면병합")
REDUCTION_REASONS = {"자본감소", "자본감소(액면감액)", "감자(주식병합)", "감자(액면변경)"}


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
    failed_check: str = ""

    def __post_init__(self):
        required = self.kind in ADJUSTMENTS
        require((self.price_factor is not None) == (self.volume_factor is not None) == required
                and (not required or self.price_factor > 0 and self.volume_factor > 0),
                "Resolution factors do not match its type")


@dataclass(frozen=True)
class NoticeFailure:
    evidence: tuple[FieldEvidence, ...]
    failed_check: str


@dataclass(frozen=True)
class StructuralReview:
    security: SecurityKey
    date: str
    shares_after: int
    added_shares: int
    evidence: tuple[FieldEvidence, ...]


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


def structural_review_evidence(original, final, family_refs, original_body_refs):
    original_refs = (*family_refs[:3], *original_body_refs)
    return tuple(FieldEvidence(original, ref, "KIND superseded structural implementation") for ref in original_refs) + tuple(
        FieldEvidence(final, ref, "KIND final name correction") for ref in family_refs[3:])


def superseded_merger_review(filing, form, body, final, keys, has_session, evidence):
    require(len(final) == 1, "KIND final name correction identifies multiple listing intervals")
    notice, = final
    facts = superseded_merger_facts(filing, form, body)
    security, day = notice.security, facts.effective
    rename_day = notice.facts.effective
    require(notice.form == "68155" and notice.final and notice.facts.kind == "rename"
            and filing.company_id and filing.company_id == notice.company_id and security.code.startswith(filing.company_id)
            and security in keys and (facts.code, facts.isin, security.share_class) == (security.code, security.isin, "common")
            and security.active(day) and security.active(rename_day) and has_session(security, day)
            and has_session(security, rename_day) and day < rename_day
            and len(scheduled_sessions(pd.Timestamp(day), pd.Timestamp(rename_day))) == 2
            and facts.renamed_company == normal_company(notice.facts.company),
            "KIND final name correction cannot identify the original implementation window")
    return StructuralReview(security, day, facts.shares_after, facts.added_shares, evidence)


def verify_structural_review_quantities(candidate, review):
    require(candidate.security == review.security and candidate.date == review.date
            and candidate.shares_after == review.shares_after
            and candidate.shares_after - candidate.shares_before == review.added_shares,
            "KIND superseded implementation quantities differ from actual KRX observations")


def observed_structural_review_candidate(security, raw, days, day):
    days, base, _ = _observations(raw, days)
    at = days.get_indexer([pd.Timestamp(day)])[0]
    require(at > 0 and security.active(days[at - 1].date().isoformat()) and security.active(day)
            and len(scheduled_sessions(days[at - 1], days[at])) == 2,
            "KIND structural review requires adjacent actual KRX sessions in one listing")
    return _observed_candidate(security, raw, days, at, base)


def _reason(notice):
    return re.sub(r"\s+", "", notice.facts.reason)


def structural_notice(notice):
    return (notice.final and notice.facts.kind in {"listing", "auction"}
            and bool(STRUCTURAL.search(_reason(notice)) or MERGER.search(_reason(notice))))


def merger_facts(kind, reason):
    return kind in {"listing", "auction"} and bool(MERGER.search(re.sub(r"\s+", "", reason)))


def _issuer_merger_windows(notice, keys, has_session):
    security, day = notice.security, notice.facts.effective
    issuer = notice.company_id[:5]
    if (notice.final and merger_facts(notice.facts.kind, notice.facts.reason)
            and re.fullmatch(r"[0-9A-Z]{5}", issuer) and security.code.startswith(issuer)
            and security.active(day) and has_session(security, day)):
        return {key for key in keys if key.code.startswith(issuer) and key.active(day) and has_session(key, day)}
    return set()


def structural_closure(notices, keys, has_session):
    """Identify the verified structural windows covered by a final correction."""
    structural = [notice for notice in notices if structural_notice(notice)]
    closed = {notice.security for notice in structural
              if notice.security in keys and has_session(notice.security, notice.facts.effective)}
    issuer_windows = [_issuer_merger_windows(notice, keys, has_session) for notice in structural]
    closed.update(key for targets in issuer_windows for key in targets)
    return closed, closed if issuer_windows and all(issuer_windows) else keys


def role_correction_kind(filing, form):
    role = {"70765": "rename", "32002": "new_listing"}.get(form)
    return role if role == kind_topic(filing) else None


def role_correction_windows(filing, form, original, final, keys, has_session):
    """Close only the exact name change or initial listing both versions prove."""
    role, issuer = role_correction_kind(filing, form), filing.company_id
    require(role and issuer and len(original) == len(final) == 1, "KIND correction does not establish one source role")
    source, = original
    notice, = final
    key, day = notice.security, source.effective
    require(source == notice.facts and source.kind == role and notice.final and notice.form == form
            and notice.company_id == issuer and key in keys and key.code.startswith(issuer)
            and key.active(day) and has_session(key, day)
            and (role == "rename" or (source.code, source.isin, day) == (key.code, key.isin, key.listing)),
            "KIND correction changes its verified source role or listing window")
    return {key}


def _division_notice(notice):
    return notice.final and notice.facts.kind != "rename" and bool(STRUCTURAL.search(_reason(notice)))


def issuer_merger_boundaries(notices, keys, has_session):
    """Map recipient windows and dates to the original merger Notices."""
    issuer_keys = defaultdict(set)
    for key in keys:
        issuer_keys[key.code[:5]].add(key)
    direct = {(n.security, n.facts.effective) for n in notices if _division_notice(n)
              or n.final and merger_facts(n.facts.kind, n.facts.reason)}
    boundaries = defaultdict(lambda: defaultdict(list))
    for notice in notices:
        day = notice.facts.effective
        for key in _issuer_merger_windows(notice, issuer_keys.get(notice.company_id[:5], ()), has_session):
            if (key, day) not in direct:
                boundaries[key][day].append(notice)
    return boundaries


def issuer_merger_resolution(security, day, source_notices):
    require(source_notices and all(
        notice.security != security and notice.facts.effective == day
        and _issuer_merger_windows(notice, (security,), lambda _, __: True) for notice in source_notices),
        "Issuer merger evidence does not cover the recipient security and session")
    return _result(security, day, Resolution.SEGMENT_BREAK, ISSUER_MERGER_REASON, source_notices)


def _result(security, day, kind, reason, notices=(), *, factors=None, evidence=(), review=False, failed_check=""):
    price, volume = factors if factors is not None else (None, None)
    return ResolvedEvent(security, day, kind, reason, tuple(dict.fromkeys((*evidence, *_facts_evidence(notices)))),
                      price, volume, review, failed_check)


def _official_bonus(candidate, terms, listing_notice, market, raw, days):
    record = terms.facts
    if record.shares_before != candidate.shares_before:
        return None, "bonus_prior_shares_mismatch"
    sessions = scheduled_sessions(pd.Timestamp(candidate.date), pd.Timestamp(record.effective))
    if len(sessions) != 2 or (record.kind == "bonus_terms" and sessions[-1].date().isoformat() != record.effective):
        return None, "bonus_record_date_mismatch"
    ratio = 1 + record.ratio
    # Treasury shares can change the exchange reference price without changing what each holder receives.
    diluted = Fraction(record.shares_before + record.added_shares, record.shares_before)
    if not any(compatible_base(candidate.base_price, Fraction(candidate.prev_close) / expected, candidate.date, market)
               for expected in (ratio, diluted)):
        return None, "bonus_reference_price_mismatch"
    if listing_notice and (len(listing_notice) != 1 or listing_notice[0].facts.added_shares != record.added_shares):
        return None, "bonus_listing_notice_mismatch"
    listing_day = listing_notice[0].facts.effective if listing_notice else record.listing
    if listing_day and pd.Timestamp(listing_day) in days:
        at = days.get_loc(pd.Timestamp(listing_day))
        if at == 0 or listing_day <= candidate.date:
            return None, "bonus_listing_date_mismatch"
        before, after = raw.ListedShares.iloc[at - 1:at + 1]
        if after - before != record.added_shares or (
            listing_notice and listing_notice[0].facts.shares_after not in {None, after}
        ):
            return None, "bonus_listing_shares_mismatch"
    return (1 / ratio, ratio), ""


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
    return bool(PAR_CHANGE.search(reason) and re.search(r"무상증자|권리락|주식배당", reason))


def _kind_par_change(candidate, prices, listings, market):
    if not any(PAR_CHANGE.search(_reason(notice)) for notice in (*listings, *prices)):
        return None, ""
    for notice in prices:
        if _combined_reference_adjustment(notice):
            return None, "par_combined_reference"
        if notice.facts.kind != "listing_price" or notice.facts.base != candidate.base_price:
            return None, "par_notice_price_mismatch"
    if len(listings) != 1:
        return None, "par_listing_count"
    listed, = listings
    facts = listed.facts
    if not (facts.par_before and facts.par_after and facts.par_before != facts.par_after
            and PAR_CHANGE.search(_reason(listed))):
        return None, "par_change_terms_missing"
    if facts.shares_before not in {None, candidate.shares_before} or facts.shares_after != candidate.shares_after:
        return None, "par_notice_shares_mismatch"
    ratio = Fraction(facts.par_before, facts.par_after)
    expected_shares = ratio * candidate.shares_before
    if ratio < 1:
        expected_shares = math.floor(expected_shares)
    if expected_shares != candidate.shares_after:
        return None, "par_shares_mismatch"
    if not compatible_base(candidate.base_price, Fraction(candidate.prev_close) / ratio, candidate.date, market):
        return None, "par_reference_price_mismatch"
    return ratio, ""


def _kind_reduction(candidate, prices, listings, market, raw, at):
    if not any(re.search(r"감자|자본감소", _reason(notice)) for notice in (*prices, *listings)):
        return None, ""
    if len(prices) != 1 or prices[0].facts.kind != "auction" or len(listings) != 1:
        return None, "reduction_notice_pair_missing"
    if any(_reason(notice) not in REDUCTION_REASONS for notice in (*prices, *listings)):
        return None, "reduction_reason_conflict"
    auction, listed = prices[0].facts, listings[0].facts
    if auction.evaluation is None:
        return None, "reduction_evaluation_price_missing"
    factor = Fraction(auction.evaluation, candidate.prev_close).limit_denominator(10)
    if factor < 1 or not compatible_base(auction.evaluation, candidate.prev_close * factor, candidate.date, market):
        return None, "reduction_evaluation_price_mismatch"
    if math.floor(candidate.shares_before / factor) != candidate.shares_after:
        return None, "reduction_shares_mismatch"
    if (listed.shares_before not in {None, candidate.shares_before}
            or listed.shares_after != candidate.shares_after):
        return None, "reduction_notice_shares_mismatch"
    if (auction.low is None or auction.high is None or not auction.low <= candidate.base_price <= auction.high
            or raw.RawOpen.iloc[at] != candidate.base_price or raw.RawVolume.iloc[at] <= 0):
        return None, "reduction_opening_auction_mismatch"
    return factor, ""


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
    prices = [notice for notice in events
              if notice.facts.kind in {"listing_price", "auction"} and notice.form != "70718"]
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


def _resolve_day(security, raw, days, at, candidate, action, notices, terms, all_listings, complete, blocked, unparsed,
                 issuer_mergers):
    day = days[at].date().isoformat()
    final = [notice for notice in notices if notice.final]
    nonfinal = len(final) != len(notices)
    events = [notice for notice in final if notice.facts.kind != "rename"]
    action_evidence = _action_evidence(action) if action else ()
    if any(_division_notice(notice) for notice in events):
        return _result(security, day, Resolution.SEGMENT_BREAK, "official_division", final, evidence=action_evidence)
    merger = [notice for notice in events if merger_facts(notice.facts.kind, notice.facts.reason)]
    if merger:
        spac = [notice for notice in merger if _spac_issuer(notice, final)]
        if spac:
            if sum(_spac_merger(raw, at, notice) for notice in spac) == 1:
                return _result(security, day, Resolution.SPAC_PREMERGER, "official_spac_merger_listing", final,
                               evidence=action_evidence)
            return _result(security, day, Resolution.SEGMENT_BREAK, "spac_merger_share_observation_disagrees", final,
                           evidence=action_evidence, review=True, failed_check="spac_merger_shares_mismatch")
        return _result(security, day, Resolution.SEGMENT_BREAK, "official_merger", final, evidence=action_evidence)
    if issuer_mergers:
        return issuer_merger_resolution(security, day, issuer_mergers)
    if candidate is None:
        return None
    if blocked:
        return None
    if unparsed:
        if not complete:
            return None
        return _result(security, day, Resolution.SEGMENT_BREAK, "official_notice_format_requires_review", notices,
                       evidence=(*action_evidence, *(ref for failure in unparsed for ref in failure.evidence)),
                       review=True, failed_check=unparsed[0].failed_check)
    if not nonfinal and _official_transfer(security, raw, at, candidate, events):
        if action or any(n.facts.kind in {"ex_price", "listing"} and DISALLOWED_LISTING.search(_reason(n)) for n in events):
            return _result(security, day, Resolution.SEGMENT_BREAK, "transfer_conflicts_with_unit_event", final,
                           evidence=action_evidence, review=True, failed_check="transfer_unit_event_conflict")
        return _result(security, day, Resolution.REFERENCE_RESET, "official_continuous_transfer", final,
                       factors=(Fraction(1), Fraction(1)))
    if action is not None and not nonfinal:
        try:
            verify_action(security.code, raw, days, at, candidate.base_price, action)
        except ValueError:
            return _result(security, day, Resolution.SEGMENT_BREAK, "official_action_disagrees_with_krx", final,
                           evidence=action_evidence, review=True, failed_check="dart_action_krx_observation_mismatch")
        action_kind = ACTION_KIND[action.kind]
        if _compatible_action_notices(action, events, candidate):
            return _result(security, day, action_kind, "verified_dart_and_kind_action", final,
                           factors=(1 / action.factor, action.factor), evidence=action_evidence)
        return _result(security, day, Resolution.SEGMENT_BREAK, "official_action_conflicts_with_kind_notice", final,
                       evidence=action_evidence, review=True, failed_check="dart_action_kind_notice_conflict")

    prices = [notice for notice in events if notice.facts.kind in {"ex_price", "auction", "listing_price"}]
    listings = [notice for notice in events if notice.facts.kind == "listing"]
    market = raw.Market.iloc[at] if "Market" in raw else security.market
    failed_check = "notice_not_final" if nonfinal else ""
    if not nonfinal:
        reduction_factor, failed_check = _kind_reduction(candidate, prices, listings, market, raw, at)
        if reduction_factor is not None:
            kind = Resolution.REFERENCE_RESET if reduction_factor == 1 else Resolution.UNIT_CHANGE
            return _result(security, day, kind, "official_kind_reduction_auction", final,
                           factors=(reduction_factor, 1 / reduction_factor))

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
                first_failed_term = ""
                for term in terms:
                    if (not term.final or term.facts.kind != term_kind or term.facts.effective < day
                        or term.company_id and notice.company_id and term.company_id != notice.company_id):
                        continue
                    later = [item for item in all_listings.get(term.facts.listing, ())
                             if item.final and item.facts.kind == "listing" and "무상증자" in _reason(item)]
                    factors, term_failure = _official_bonus(candidate, term, later, market, raw, days)
                    if factors:
                        matching.append((term, later, factors))
                    else:
                        first_failed_term = first_failed_term or term_failure
                if len(matching) == 1:
                    term, later, factors = matching[0]
                    return _result(security, day, Resolution.BONUS, term_kind, [*final, term, *later], factors=factors)
                failed_check = "bonus_terms_ambiguous" if matching else first_failed_term or "bonus_terms_missing"
            else:
                failed_check = "ex_price_reason_or_form_unsupported"
        elif facts.kind == "ex_price":
            failed_check = ("ex_price_notice_base_mismatch" if facts.base != candidate.base_price
                            else "ex_price_shares_changed")
        if (facts.kind == "auction" and unit_unchanged and RESUME.search(reason) and candidate.paused
            and facts.evaluation == candidate.prev_close and facts.low <= candidate.base_price <= facts.high
            and raw.RawOpen.iloc[at] == candidate.base_price and raw.RawVolume.iloc[at] > 0):
            return _result(security, day, Resolution.REFERENCE_RESET, "official_resumption_auction", final,
                           factors=(Fraction(1), Fraction(1)))

    if not nonfinal:
        ratio, par_failure = _kind_par_change(candidate, prices, listings, market)
        if ratio is not None:
            return _result(security, day, Resolution.UNIT_CHANGE, "official_kind_face_value_and_shares", final,
                           factors=(1 / ratio, ratio))
        failed_check = par_failure or failed_check
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
        failed_check = "listing_shares_mismatch"

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
                   evidence=action_evidence, review=True,
                   failed_check=failed_check or ("official_terms_unmatched" if notices else "official_evidence_missing"))


def resolve_events(security, raw, expected_dates, notices, *, actions=(), coverage_complete=False,
                   covered_dates=frozenset(), blocked_dates=frozenset(), unparsed_dates=None, transfer_anchor=None,
                   transfer_source=None, issuer_mergers=None, structural_reviews=()):
    """Produce one canonical outcome per observed candidate and confirmed structure date."""
    days, base, mask = _observations(raw, expected_dates)
    require(not days.empty and all(security.active(day.date().isoformat()) for day in days),
            "KRX prices lie outside the official listing interval")
    require(all(notice.security == security for notice in notices), "KIND notices mix listing identities")
    reviews = {review.date: review for review in structural_reviews}
    require(len(reviews) == len(structural_reviews), "Multiple proofs of an unresolved structural implementation")
    review_candidates = {}
    for day, review in reviews.items():
        candidate = observed_structural_review_candidate(security, raw, days, day)
        verify_structural_review_quantities(candidate, review)
        review_candidates[day] = candidate
    unparsed_dates = unparsed_dates or {}
    issuer_mergers = issuer_mergers or {}
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
    for notice in notices:
        day = notice.facts.effective
        if notice.final and notice.form == "70718" and day in by_date:
            require(notice.facts.kind == "listing_price" and notice.facts.base == base.iloc[by_date[day]],
                    f"{security.code} {day}: KIND new-listing reference differs from the KRX base")
    outside = sorted(day for day in set(indexed_actions) | set(on_date)
                     if first_day <= day <= max(by_date) and day not in by_date)
    for day in outside:
        if day in indexed_actions or any(
            STRUCTURAL.search(_reason(notice)) or MERGER.search(_reason(notice)) for notice in on_date[day]
        ):
            incomplete.append(day)
    dates = (set(on_date) | set(indexed_actions) | issuer_mergers.keys() | reviews.keys()
             | {days[at].date().isoformat() for at in mask.to_numpy().nonzero()[0]})
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
                           terms, on_date, complete, day in blocked_dates, unparsed_dates.get(day, ()),
                           issuer_mergers.get(day, ()))
        if (anchored_transfer and transfer_source and transfer_source.isin != security.isin
                and (row is None or row.kind in ADJUSTMENTS or row.kind == Resolution.SHARES_ONLY)):
            row = _result(security, day, Resolution.SEGMENT_BREAK, "separate_verified_listing_units", current)
        if proof := reviews.get(day):
            require(row is None or row.review, "KIND structural review conflicts with a verified resolution")
            candidate = review_candidates[day]
            row = _result(security, day, Resolution.SEGMENT_BREAK, STRUCTURAL_REVIEW_REASON,
                          evidence=proof.evidence, review=True, failed_check="structural_implementation_superseded")
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
