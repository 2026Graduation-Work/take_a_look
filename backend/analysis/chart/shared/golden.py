"""Compare serving features against frozen inputs and expected values."""
import numpy as np
import pandas as pd

from .features.builder import build_feature_frame

REQUIRED_KINDS = {"normal", "adjusted", "regular_unavailable", "flow_missing", "corporate_event"}


class GoldenError(ValueError):
    pass


def compute(cases, feature_names):
    results = []
    for case in cases:
        raw = pd.DataFrame(case["raw"])
        raw.Date = pd.to_datetime(raw.Date)
        frame = build_feature_frame(raw, set(raw.Date.dt.date))
        missing = set(feature_names) - set(frame.columns)
        if missing:
            raise GoldenError(f'{case["name"]}: missing calculated features: {", ".join(sorted(missing))}')
        results.append(frame.loc[case["rows"], feature_names].to_numpy(dtype=float))
    return results


def check_coverage(golden, model_features):
    names = golden["feature_names"]
    missing = set(model_features) - set(names)
    if missing:
        raise GoldenError(f'Missing expected features: {", ".join(sorted(missing))}')
    cases = golden["cases"]
    missing_kinds = REQUIRED_KINDS - {case["kind"] for case in cases}
    if missing_kinds:
        raise GoldenError(f'Missing golden case kinds: {", ".join(sorted(missing_kinds))}')
    values = np.concatenate([np.asarray(case["expected"], dtype=float) for case in cases])
    for name in sorted(set(model_features)):
        column = values[:, names.index(name)]
        valid = column[np.isfinite(column)]
        if not valid.size:
            raise GoldenError(f"{name}: no finite expected values")
        if np.unique(valid.round(12)).size < 2:
            raise GoldenError(f"{name}: fewer than two distinct expected values")


def compare(golden, model_features):
    cases = golden["cases"]
    names = golden["feature_names"]
    selected = set(model_features)
    features = [name for name in names if name in selected]
    missing = selected - set(features)
    if missing:
        raise GoldenError(f'Missing expected features: {", ".join(sorted(missing))}')
    columns = [names.index(name) for name in features]
    tolerance = golden["tolerance"]
    for case, actual in zip(cases, compute(cases, features), strict=True):
        expected = np.asarray(case["expected"], dtype=float)[:, columns]
        try:
            np.testing.assert_allclose(actual, expected, **tolerance, equal_nan=True)
        except AssertionError as error:
            if actual.shape != expected.shape:
                raise GoldenError(f'{case["name"]}: expected shape {expected.shape}, calculated {actual.shape}') from error
            different = ~np.isclose(actual, expected, **tolerance, equal_nan=True).all(axis=0)
            changed = ", ".join(name for name, mismatch in zip(features, different, strict=True) if mismatch)
            raise GoldenError(f'{case["name"]}: feature values differ: {changed}') from error
