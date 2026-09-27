import json
from pathlib import Path

from serving.frontend_handoff import chart_detail_fields


def snapshot():
    value = json.loads((Path(__file__).parents[1] / "contracts/examples/normal.json").read_text())
    value["contract"] = "chart_signal_detail_v2"
    value["pack_id"] = "pack-1"
    del value["cases"]
    value["distribution"] = {
        "status": "available", "reason": None,
        "policy_id": "multi_stock_up_sigma_001_005_v1",
        "current": {"up": value["inference"]["scores"]["up"],
                    "sigma": value["inference"]["sigma"]},
        "tolerances": {"up_absolute": .01, "sigma_relative": .05},
        "sample_count": 2, "stock_count": 2,
        "period_start": "2020-01-01", "period_end": "2021-01-01",
        "observed_through": "2021-02-01", "by_fold": {"1": 2},
        "histogram": {"bins": [{"left": -3, "right": 0, "count": 1},
                               {"left": 0, "right": 4, "count": 1}],
                      "central_68": {"low": -2, "high": 3}},
    }
    return value


def test_handoff_maps_actual_chart_fields_without_inventing_other_blocks():
    result = chart_detail_fields(snapshot())
    patch = result["stockDetailPatch"]
    assert result["contract"] == "frontend_chart_handoff_v1"
    assert patch["returnBand"] == {"low": -2, "high": 3, "ciLevel": .68}
    assert patch["realizedReturns"] == [
        {"from": -3, "to": 0, "count": 1}, {"from": 0, "to": 4, "count": 1}]
    assert patch["similarCaseCount"] == 2
    assert result["model"]["scores"] == snapshot()["inference"]["scores"]
    assert not {"hitRate", "rankPercentile", "horizonAgreement", "riskGrade"} & patch.keys()


def test_handoff_omits_band_when_there_are_no_cases():
    value = snapshot()
    value["distribution"].update({"status": "no_cases", "sample_count": 0, "stock_count": 0,
                                  "period_start": None, "period_end": None,
                                  "observed_through": None, "by_fold": {},
                                  "histogram": {"bins": [], "central_68": None}})
    patch = chart_detail_fields(value)["stockDetailPatch"]
    assert "returnBand" not in patch
    assert "realizedReturns" not in patch
