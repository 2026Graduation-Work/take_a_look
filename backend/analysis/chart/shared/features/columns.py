"""Versioned, explicit model inputs. Source columns never become features implicitly."""


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
