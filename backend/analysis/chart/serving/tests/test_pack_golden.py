import json
from pathlib import Path

import pytest
from shared.golden import GoldenError, check_coverage, compare

PACK_ID = "kospi_shared_v3_flow_train2023_2025_20261014"
GOLDEN_PATH = Path(__file__).parents[1] / "golden" / f"{PACK_ID}.json"


@pytest.fixture
def golden():
    return json.loads(GOLDEN_PATH.read_text())


@pytest.mark.parametrize("replacement", [0.5, None])
def test_compare_names_changed_feature_and_case(golden, replacement):
    name = "kmid"
    index = golden["feature_names"].index(name)
    golden["cases"][0]["expected"][0][index] = replacement

    with pytest.raises(GoldenError, match="normal: feature values differ: kmid"):
        compare(golden, [name])


def test_coverage_rejects_missing_feature(golden):
    golden["feature_names"].remove("kmid")
    with pytest.raises(GoldenError, match="kmid"):
        check_coverage(golden, ["kmid"])


@pytest.mark.parametrize("replacement", [0.5, None])
def test_coverage_rejects_uninformative_feature(golden, replacement):
    name = "kmid"
    index = golden["feature_names"].index(name)
    for case in golden["cases"]:
        for row in case["expected"]:
            row[index] = replacement

    with pytest.raises(GoldenError, match="kmid"):
        check_coverage(golden, [name])


def test_coverage_requires_corporate_event(golden):
    golden["cases"] = [case for case in golden["cases"] if case["kind"] != "corporate_event"]
    with pytest.raises(GoldenError, match="corporate_event"):
        check_coverage(golden, golden["feature_names"])
