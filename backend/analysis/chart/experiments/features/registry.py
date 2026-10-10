"""Select explicit research features; common input order is defined in shared."""
from shared.features.columns import (  # noqa: F401
    BASE_FEATURES,
    FEATURE_VERSION,
    FLOW_FEATURES,
    WINDOWS,
)

from .psychology import FEATURE_COLUMNS as PSYCHOLOGY_COLUMNS
from .psychology import TREATMENT_FEATURES

GROUPS = {"base": BASE_FEATURES, "psychology": TREATMENT_FEATURES, "flow": FLOW_FEATURES}


def resolve_feature_columns(config):
    groups = config.get("groups", ["base"])
    if not isinstance(groups, list) or set(groups) - set(GROUPS):
        raise ValueError(f"Unknown feature groups: {groups}")
    for field in ("include", "exclude"):
        if not isinstance(config.get(field, []), list):
            raise ValueError(f"features.{field} must be a list")
    external = [col for source in config.get("sources", []) for col in source["columns"]]
    known = set(BASE_FEATURES) | set(PSYCHOLOGY_COLUMNS) | set(FLOW_FEATURES) | set(external)
    requested = list(
        dict.fromkeys(
            [col for group in groups for col in GROUPS[group]]
            + config.get("include", [])
            + external
        )
    )
    if unknown := (set(requested) | set(config.get("exclude", []))) - known:
        raise ValueError(f"Unknown model inputs: {sorted(unknown)}")
    selected = [col for col in requested if col not in config.get("exclude", [])]
    if not selected:
        raise ValueError("Select at least one model input")
    return selected
