"""Versioned, explicit model inputs. Source columns never become features implicitly."""

from .psychology import FEATURE_COLUMNS as PSYCHOLOGY_COLUMNS
from .psychology import TREATMENT_FEATURES

FEATURE_VERSION = 3
WINDOWS = (5, 10, 20, 30, 60)
BASE_FEATURES = (
    "Change",
    "kmid",
    "klen",
    "kmid_2",
    "kup",
    "kup_2",
    "klow",
    "klow_2",
    "ksft",
    "ksft_2",
    "open_0",
    "high_0",
    "low_0",
    "vwap_0",
    *(
        f"{name}_{w}"
        for w in WINDOWS
        for name in (
            "roc",
            "ma",
            "max",
            "min",
            "rsv",
            "std",
            "beta",
            "rsqr",
            "resi",
            "rank",
            "qtlu",
            "qtld",
            "imax",
            "imin",
            "imxd",
            "cntp",
            "cntn",
            "cntd",
            "sump",
            "sumn",
            "sumd",
            "corr",
            "cord",
            "vma",
            "vstd",
            "wvma",
            "vsump",
            "vsumn",
            "vsumd",
        )
    ),
    "Barrier_Up",
    "Barrier_Down",
)
FLOW_FEATURES = tuple(
    f"flow_{investor}_{w}"
    for investor in ("individual", "institution", "foreign")
    for w in (1, 5, 20)
)
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
