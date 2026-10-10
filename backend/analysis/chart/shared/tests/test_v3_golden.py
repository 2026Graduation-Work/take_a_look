"""Golden values come from preserved v3 source, not the new serving builder."""
import ast
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from shared.features.builder import build_feature_frame

GOLDEN = json.loads((Path(__file__).parent / "fixtures/v3-golden.json").read_text())

@pytest.mark.parametrize("case", GOLDEN["cases"], ids=lambda case: case["name"])
def test_shared_matches_original_v3(case):
    raw = pd.DataFrame(case["raw"])
    raw.Date = pd.to_datetime(raw.Date)
    result = build_feature_frame(raw, set(raw.Date.dt.date))
    expected = pd.DataFrame(case["expected"], columns=case["columns"]).to_numpy(dtype=float)
    np.testing.assert_allclose(result.loc[case["rows"], case["columns"]].to_numpy(dtype=float),
                               expected, rtol=1e-8, atol=1e-10, equal_nan=True)
    if case["name"] == "regular_unavailable":
        assert result.loc[70, "RegularSessionUnavailable"]
        assert result.loc[70, "Trading_Halt"] == 1
        assert result.loc[70, "Volume"] == 0 < result.loc[70, "RawVolume"]
        assert result.loc[70, "Amount"] == raw.loc[70, "Amount"]


def test_unverified_missing_session_is_rejected():
    raw = pd.DataFrame(GOLDEN["cases"][0]["raw"])
    raw.Date = pd.to_datetime(raw.Date)
    with pytest.raises(ValueError, match="Unverified missing sessions"):
        build_feature_frame(raw.drop(index=70), set(raw.Date.dt.date))


def test_runtime_import_boundaries():
    root = Path(__file__).parents[2]
    for package, forbidden in [("shared", {"experiments", "serving"}), ("serving", {"experiments"})]:
        for path in (root / package).rglob("*.py"):
            if "tests" in path.parts:
                continue
            for node in ast.walk(ast.parse(path.read_text())):
                if isinstance(node, ast.Import):
                    imports = [item.name.split(".")[0] for item in node.names]
                elif isinstance(node, ast.ImportFrom):
                    imports = [(node.module or "").split(".")[0]] if node.level == 0 else []
                else:
                    continue
                assert not forbidden.intersection(imports), str(path)
