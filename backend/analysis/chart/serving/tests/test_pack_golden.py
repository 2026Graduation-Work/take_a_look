import json
from pathlib import Path

import pytest
import yaml
from shared.golden import GoldenError, check_coverage, compare
from shared.io import sha256_file

SERVING = Path(__file__).parents[1]
ACTIVE_PACK = yaml.safe_load((SERVING / "config.yaml").read_text())["active_pack"]
GOLDEN_PATH = SERVING / "golden" / f'{ACTIVE_PACK["pack_id"]}.json'


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


def test_active_pack_reproduces_expected_features(golden):
    compare(golden, golden["feature_names"])


def test_active_pack_expected_features_have_coverage(golden):
    check_coverage(golden, golden["feature_names"])


def test_active_pack_golden_checksum():
    assert sha256_file(GOLDEN_PATH) == ACTIVE_PACK["golden_sha256"]
