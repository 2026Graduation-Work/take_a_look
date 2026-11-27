"""Measure resolved segment retention on preserved KRX prices without training a model."""

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np
import pandas as pd
from experiments.features.local_panel import feature_lookback
from experiments.train_src.labels import barrier_labels
from experiments.train_src.loaders import eligible_samples
from shared.data.actions import action_from_record
from shared.data.events import verify_events
from shared.data.resolution_snapshot import (
    ResolutionSnapshot,
    _load_tables,
    _scope,
    _table_paths,
    segment_id,
)
from shared.data.segmented_prices import adjust_price_history
from shared.features.builder import add_sigma_barriers, normalize_trading_halts
from shared.features.columns import BASE_FEATURES
from shared.io import sha256
from shared.settings import PREPROCESSING

from .census_actions import _price_frame, _security_master, _windows

LABEL_RULES = {5: (1.75, 1.5), 20: (3.75, 3.)}


def eligible_keys(prices, sessions, feature_columns=BASE_FEATURES, settings=PREPROCESSING):
    parts = [add_sigma_barriers(normalize_trading_halts(segment, sessions), settings)
             for _, segment in prices.groupby("SegmentId", sort=False)]
    prices = pd.concat(parts, ignore_index=True)
    groups = prices.groupby("SegmentId", sort=False)
    warmup = groups.cumcount().lt(feature_lookback(feature_columns))
    prices["SampleEligible"] = ~warmup
    results = {}
    for horizon, (up, down) in LABEL_RULES.items():
        maturity = pd.Series(False, index=prices.index)
        for positions in groups.indices.values():
            days = prices.Trading_Halt.iloc[positions].ne(1).to_numpy().cumsum()
            targets = np.searchsorted(days, days + horizon)
            maturity.iloc[positions] = (targets < len(days)) & (targets <= np.arange(len(days)) + int(horizon * 2.5))
        labels = barrier_labels(prices, horizon, up_mult=up, down_mult=down)
        eligible = labels.notna() & eligible_samples(prices)
        results[horizon] = (pd.DatetimeIndex(prices.loc[eligible, "Date"]), {
            "warmup": int(warmup.sum()), "horizon_not_mature": int((~maturity).sum()),
            "warmup_and_horizon_not_mature": int((warmup & ~maturity).sum()),
            "warmup_or_horizon_not_mature": int((warmup | ~maturity).sum()),
            "additional_ineligible": int((~eligible & ~warmup & maturity).sum()),
            "eligible": int(eligible.sum()),
        })
    return results


def measure(census, krx_days, active_master, delisted_master, *, prior_actions=()):
    manifest = json.loads((census / "manifest.json").read_bytes())
    _table_paths(census, manifest)
    coverage, windows, sessions, ledgers, notices, refs = _load_tables(census, manifest)
    _, end, codes = _scope(manifest)
    sources = manifest["sources"]
    if (sha256(active_master) != sources["active_master_sha256"]
            or sha256(delisted_master) != sources["delisted_master_sha256"]
            or [sha256(path) for path in prior_actions] != sources["official_action_snapshots"]):
        raise ValueError("Diagnostic census master or legacy action hashes differ")
    raw, hashes = _price_frame(krx_days, sessions, set(codes))
    if hashes != sources["krx_sessions"]:
        raise ValueError("Diagnostic KRX day hashes differ from the census")
    master = _security_master(active_master, delisted_master)
    securities, _, _, _, training, _, _, failures = _windows(raw, master, sessions, {})
    if windows.keys() != securities.keys():
        raise ValueError("Diagnostic listing scope differs from the census windows")
    del raw, master
    snapshot = ResolutionSnapshot(census / "manifest.json", manifest, coverage, windows, sessions, ledgers,
                                  dict.fromkeys(training), notices, refs, "", "")
    old_actions = {}
    for path in prior_actions:
        for item in json.loads(path.read_bytes())["securities"]:
            key = item["security"]
            actions = old_actions.setdefault((key["code"], key["isin"], key["listing"], key["delisting"],
                                              key["market"], key["share_class"]), set())
            actions.update(map(action_from_record, item["actions"]))
    baseline_rejected, source_failed = set(), set()
    for failure in failures:
        source_failed.add(failure["Code"])
    for item in coverage["unassigned_market_observations"]:
        source_failed.add(item["Code"])
    for security in training:
        if not windows[security]["complete"]:
            source_failed.add(security.code)
    per_horizon = {horizon: Counter() for horizon in LABEL_RULES}
    usable_codes = {horizon: set() for horizon in LABEL_RULES}
    collected_codes, retained_codes = set(), set()
    code_windows = defaultdict(list)
    for security in sorted(training, key=lambda key: (key.code, key.listing)):
        code_windows[security.code].append(security)
    price_failures = {}
    review_codes = {key.code for key in training if any(row.review for row in ledgers[key].resolutions)}
    raw_rows, counted_rows, removed_spac, review_rows = 0, 0, 0, 0
    for code, keys in code_windows.items():
        raw_rows += sum(len(securities[key]) for key in keys)
        price_windows = [(key, snapshot.days(key)) for key in keys]
        for key, days in price_windows:
            if len(days) != len(securities[key]):
                continue
            try:
                verify_events(code, securities[key], days, tuple(old_actions.get(tuple(vars(key).values()), ())))
            except ValueError:
                baseline_rejected.add(code)
        if code in source_failed:
            continue
        combined = pd.concat([securities[key] for key in keys], ignore_index=True)
        days = pd.DatetimeIndex(sorted(day for _, sessions in price_windows for day in sessions))
        try:
            adjusted, _ = adjust_price_history([(key, code) for key in keys], combined, days, end, snapshot)
        except (ValueError, OSError) as exc:
            price_failures[code] = str(exc)
            continue
        collected_codes.add(code)
        counted_rows += len(adjusted)
        review_rows += sum(row.review for key in keys for row in ledgers[key].resolutions)
        for key, days in price_windows:
            window = adjusted.loc[adjusted.Date.isin(days)]
            price_path = window.loc[~window.SegmentId.isin(snapshot.excluded_segment_ids(key))]
            removed_spac += len(window) - len(price_path)
            if price_path.empty:
                continue
            retained_codes.add(code)
            treatment = eligible_keys(price_path, days)
            control = eligible_keys(price_path.assign(SegmentId=segment_id(key, key.listing)), days)
            for h in LABEL_RULES:
                treatment_keys, counts = treatment[h]
                control_keys, _ = control[h]
                per_horizon[h].update(counts)
                per_horizon[h]["without_corporate_boundaries"] += len(control_keys)
                per_horizon[h]["removed_by_corporate_boundaries"] += len(control_keys.difference(treatment_keys))
                per_horizon[h]["added_by_corporate_boundaries"] += len(treatment_keys.difference(control_keys))
                if len(treatment_keys):
                    usable_codes[h].add(code)
    excluded_before_preprocessing = set(code_windows) - collected_codes
    new_excluded = {"unresolved_corporate_action": excluded_before_preprocessing & review_codes - source_failed,
                    "spac_policy": collected_codes - retained_codes,
                    "source_or_identity_failure": source_failed,
                    "other_price_stage_failure": set(price_failures) - review_codes}
    comparisons = {reason: {"new_codes": sorted(keys), "old_and_new_codes": sorted(baseline_rejected & keys),
                             "removed_from_old_codes": sorted(baseline_rejected - keys),
                             "added_to_old_codes": sorted(keys - baseline_rejected)}
                   for reason, keys in new_excluded.items()}
    for horizon in per_horizon:
        missing = retained_codes - usable_codes[horizon]
        comparisons[f"no_eligible_training_rows_h{horizon}"] = {
            "new_codes": sorted(missing), "old_and_new_codes": sorted(baseline_rejected & missing),
            "removed_from_old_codes": sorted(baseline_rejected - missing),
            "added_to_old_codes": sorted(missing - baseline_rejected),
        }
    return {"scope": manifest["scope"], "market_ledger_complete": manifest["ledger_complete"],
            "measurement": "collector_price_stage_replay_on_preserved_krx_days_then_base_sample_eligibility",
            "sample_policy": {"feature_group": "base", "lookback": feature_lookback(BASE_FEATURES),
                              "preprocessing": PREPROCESSING, "label_up_down_multipliers": LABEL_RULES},
            "source_complete_for_training_codes": not source_failed,
            "expected_training_code_keys": sorted(code_windows), "collected_price_code_keys": sorted(collected_codes),
            "excluded_before_preprocessing_code_keys": sorted(excluded_before_preprocessing),
            "price_stage_failures": price_failures,
            "census_manifest_sha256": sha256(census / "manifest.json"),
            "training_codes": len({key.code for key in training}), "training_raw_rows": raw_rows,
            "source_verified_rows": counted_rows, "spac_excluded_rows": removed_spac,
            "review_queue_rows_from_verified_windows": review_rows,
            "reviewed_codes_with_retained_price_path": sorted(review_codes & retained_codes),
            "strict_legacy_rejection_codes": sorted(baseline_rejected),
            "strict_legacy_official_action_snapshots": len(prior_actions),
            "ticker_exclusions_compared_with_strict_legacy": comparisons,
            "horizons": {str(h): {**counts, "no_eligible_training_rows": sorted(retained_codes - usable_codes[h])}
                         for h, counts in per_horizon.items()}}


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    for field in ("census-dir", "krx-days", "active-master", "delisted-master"):
        cli.add_argument(f"--{field}", required=True, type=Path)
    cli.add_argument("--action-snapshot", action="append", type=Path, default=[])
    args = cli.parse_args()
    print(json.dumps(measure(args.census_dir, args.krx_days, args.active_master, args.delisted_master,
                             prior_actions=args.action_snapshot), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
