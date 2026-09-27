"""Structural and cross-field validation of public chart snapshots."""

import json
import math
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker

V2_SCHEMA = json.loads((Path(__file__).parent / "chart_signal_detail_v2.schema.json").read_text())
V2_VALIDATOR = Draft202012Validator(V2_SCHEMA, format_checker=FormatChecker())


def validate_snapshot(value):
    V2_VALIDATOR.validate(value)
    inference, distribution = value["inference"], value["distribution"]
    if (value["horizon"] == 5) != (value["profile"] == "aggressive"):
        raise ValueError("Horizon/profile mismatch")
    if inference["status"] == "available":
        if inference["scores"] is None or inference["sigma"] is None or inference["barriers"] is None:
            raise ValueError("Available inference lacks outputs")
        if not math.isclose(sum(inference["scores"].values()), 1, rel_tol=1e-6, abs_tol=1e-8):
            raise ValueError("Scores do not sum to one")
        if any(item is None for item in value["sources"].values()):
            raise ValueError("Available inference requires all source hashes")
    elif inference["reason"] is None:
        raise ValueError("Unavailable inference requires reason")
    count = distribution["sample_count"]
    bins = distribution["histogram"]["bins"]
    band = distribution["histogram"]["central_68"]
    if sum(item["count"] for item in bins) != count:
        raise ValueError("Histogram counts disagree with sample count")
    if any(item["right"] <= item["left"] for item in bins):
        raise ValueError("Histogram bins require positive width")
    if any(left["right"] > right["left"] for left, right in zip(bins, bins[1:])):
        raise ValueError("Histogram bins overlap")
    if distribution["stock_count"] > count or sum(distribution["by_fold"].values()) != count:
        raise ValueError("Distribution metadata disagrees with sample count")
    if distribution["status"] == "available":
        if not count or not bins or band is None or band["high"] < band["low"]:
            raise ValueError("Available distribution requires an observed histogram")
        if distribution["current"] is None or inference["status"] != "available":
            raise ValueError("Distribution requires current inference")
        if (not distribution["stock_count"] or not distribution["period_start"] or
                not distribution["period_end"] or not distribution["observed_through"]):
            raise ValueError("Available distribution requires period and stock count")
    elif distribution["status"] == "no_cases":
        if count or distribution["stock_count"] or bins or band is not None:
            raise ValueError("No cases must have an empty histogram")
    elif distribution["reason"] is None:
        raise ValueError("Unavailable distribution requires reason")
    return value
