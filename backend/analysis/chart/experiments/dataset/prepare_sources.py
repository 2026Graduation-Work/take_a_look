import json
import tempfile
from argparse import Namespace
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
from shared.data.bulk_prices import (
    MissingListingPrices,
    prepare_source_days,
    supersede_incomplete_days,
)
from shared.data.calendar import scheduled_sessions
from shared.data.disclosures import DisclosureError
from shared.data.kind_market import KindMarket
from shared.data.resolution_snapshot import read_resolution_snapshot
from shared.io import append_collection_event, atomic_json, sha256

from .census_actions import _security_master, build_census, master_security_aliases, source_codes
from .freeze_resolution_snapshot import freeze_resolution_snapshot

SOURCE_ROOT = "workspace/experiments/sources"
KIND_BUDGET = 250
TERMS_LOOKBACK_DAYS = 120
PUBLICATION_TAIL_DAYS = 3


def collection_plan(root, collection, collection_identity, source_root):
    path = root / "collection_source_plan.json"
    if path.is_file():
        plan = json.loads(path.read_text())
        if plan["collection_identity"] != collection_identity:
            raise ValueError("Collection settings changed; use a new dataset root")
        return plan
    today = pd.Timestamp.now(tz="Asia/Seoul").date()
    latest_publication = today - timedelta(days=1)
    requested_end = collection.get("end_date")
    end = pd.Timestamp(requested_end or latest_publication - timedelta(days=PUBLICATION_TAIL_DAYS))
    start = pd.Timestamp(collection["start_date"])
    if start > end:
        raise ValueError("No completed KRX sessions in the requested collection range")
    sessions = scheduled_sessions(start, end)
    if not len(sessions):
        raise ValueError("No completed KRX sessions in the requested collection range")
    publication_end = sessions[-1].date() + timedelta(days=PUBLICATION_TAIL_DAYS)
    if publication_end > latest_publication:
        raise ValueError(f"KIND publication coverage through {publication_end} is still pending; resume after that day")
    first = sessions[0]
    earlier = scheduled_sessions(max(pd.Timestamp("2016-01-01"), first - pd.Timedelta(days=14)), first)
    ledger_start = earlier[-2] if len(earlier) > 1 else first
    plan = {
        "collection_identity": collection_identity,
        "source_root": str(source_root),
        "calendar_settings": {**collection, "start_date": start.date().isoformat(), "end_date": end.date().isoformat()},
        "ledger_start": ledger_start.date().isoformat(),
        "published_start": (ledger_start.date() - timedelta(days=TERMS_LOOKBACK_DAYS)).isoformat(),
        "published_end": publication_end.isoformat(),
        "correction_cutoff": latest_publication.isoformat(),
    }
    atomic_json(path, plan)
    return plan


def _covering_snapshot(destination, source_days, sessions, required_days, plan):
    settings = plan["calendar_settings"]
    codes = {str(code).zfill(6) for code in settings.get("tickers") or ()}
    markets = set(settings["markets"])
    for path in sorted((destination / "snapshots").glob("*.json")):
        snapshot = read_resolution_snapshot(path)
        scope = snapshot.manifest["scope"]
        scope_codes = set(scope["codes"])
        if (not markets <= set(scope.get("markets", ("KOSPI", "KOSDAQ")))
                or scope_codes and (not codes or not codes <= scope_codes)
                or scope.get("universe_start", scope["start"]) > required_days[0].date().isoformat()
                or settings["include_delisted"] and not scope.get("include_delisted", True)
                or scope["published_start"] > plan["published_start"]
                or scope["published_end"] < plan["published_end"]
                or not sessions.isin(snapshot.sessions).all()):
            continue
        hashes = snapshot.manifest["sources"]["krx_sessions"]
        if all((file := source_days / f"{day:%Y-%m-%d}.parquet").is_file()
               and sha256(file) == hashes[day.date().isoformat()] for day in sessions):
            return path
    return None


def prepare_sources(dataset_root, source_root, calendar, plan, *, kind_budget):
    from shared.data.listing_history import prepare_listing_masters

    start = date.fromisoformat(plan["ledger_start"])
    end = date.fromisoformat(calendar["observed_end"])
    sessions = scheduled_sessions(pd.Timestamp(start), pd.Timestamp(end))
    days = source_root / "krx_days"
    destination = source_root / "official_actions"
    required_days = pd.DatetimeIndex(pd.to_datetime(calendar["trading_days"]))
    if path := _covering_snapshot(destination, days, sessions, required_days, plan):
        return path, days

    def record(event):
        append_collection_event(dataset_root, {**event, "stage": "source_krx_days"})

    supersede_incomplete_days(days, plan.get("incomplete_krx_days", {}))
    prepare_source_days(days, sessions, record)
    kind = KindMarket(source_root / "kind", budget=kind_budget)
    settings = plan["calendar_settings"]
    requested = {str(code).zfill(6) for code in settings.get("tickers") or ()}
    selected_codes = source_codes(days, sessions, requested, settings["markets"])
    master_observed_on = date.fromisoformat(plan["master_observed_on"]) if plan.get("master_observed_on") else (
        pd.Timestamp.now(tz="Asia/Seoul").date())
    plan_path = dataset_root / "collection_source_plan.json"

    def record_missing_prices(error):
        plan["incomplete_krx_days"] = {day: sha256(days / f"{day}.parquet") for day in error.days}
        atomic_json(plan_path, plan)

    try:
        active, delisted = prepare_listing_masters(
            source_root, days, sessions, observed_on=master_observed_on,
            kind=kind, codes=tuple(sorted(selected_codes)), required_markets=settings["markets"],
            required_codes=requested, required_days=required_days,
            include_delisted=settings["include_delisted"], record=record,
        )
    except MissingListingPrices as exc:
        record_missing_prices(exc)
        raise
    if "master_observed_on" not in plan or "incomplete_krx_days" in plan:
        plan["master_observed_on"] = master_observed_on.isoformat()
        plan.pop("incomplete_krx_days", None)
        atomic_json(plan_path, plan)
    scoped = ()
    if requested:
        equity_codes = {key.code for key in master_security_aliases(_security_master(active, delisted))}
        scoped = sorted(requested | (selected_codes & equity_codes))

    with tempfile.TemporaryDirectory(dir=source_root, prefix="census-") as staging:
        work = Path(staging)
        try:
            report = build_census(Namespace(
                start=start, end=end, published_start=date.fromisoformat(plan["published_start"]),
                published_end=date.fromisoformat(plan["published_end"]), krx_days=days,
                active_master=active, delisted_master=delisted, output=work, kind_company_cache=None,
                sample=None, code=scoped, markets=settings["markets"], action_snapshot=(), automated=True,
                universe_start=required_days[0].date(), include_delisted=settings["include_delisted"],
                correction_cutoff=date.fromisoformat(plan.get("correction_cutoff", plan["published_end"])),
            ), kind)
            coverage = json.loads((work / "coverage.json").read_text())
            incomplete = [row for row in coverage["failures"]
                          if row["Stage"] in {"identity", "kind_document", "resolver", "krx_candidate"}]
            if incomplete:
                first = incomplete[0]
                context = " ".join(str(first[field]) for field in ("Code", "Date", "AcptNo") if first.get(field))
                raise DisclosureError(f"{first['Stage']} {context}: {first['Reason']}")
            atomic_json(dataset_root / "source_coverage.json", coverage)
            result = freeze_resolution_snapshot(
                work, destination, krx_days=days, active_master=active, delisted_master=delisted,
                evidence_archives=(kind.root,),
            )
        except MissingListingPrices as exc:
            record_missing_prices(exc)
            raise
        except (ValueError, OSError) as exc:
            if (work / "coverage.json").is_file():
                atomic_json(dataset_root / "source_coverage.json", json.loads((work / "coverage.json").read_text()))
            raise DisclosureError(f"Corporate-action sources incomplete after {kind.calls} KIND requests: {exc}") from exc
    atomic_json(dataset_root / "source_preparation.json", {
        "snapshot": result.stem, "sessions": len(sessions), "kind_requests": kind.calls,
        "training_reviews": report["training_review_count"], "publication_through": plan["published_end"],
    })
    return result, days
