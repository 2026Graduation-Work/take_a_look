import json

import experiments.live_record as live
import numpy as np
import pandas as pd
import pytest
from experiments.live_record import score, strong_lists
from shared.features.builder import add_sigma_barriers


@pytest.fixture
def pack():
    return {"pack_id": "evaluation-pack", "processing_contract": {"preprocessing": {
        "sigma_window": 5, "sigma_min_periods": 3,
        "barrier_feature_up_mult": 1.5, "barrier_feature_down_mult": 1.2,
    }}, "horizons": {"h5": {"label_barriers": {"up_mult": 1.75, "down_mult": 1.5}},
                     "h20": {"label_barriers": {"up_mult": 3.75, "down_mult": 3.0}}}}


def price_path(pack, direction, multiple):
    prices = pd.DataFrame({"stock_code": "A", "trade_date": pd.date_range("2026-01-01", periods=60),
                           "close": 100.0, "high": 100.0, "volume": 1000.0})
    prices.loc[:28, "close"] += 2 * np.sin(np.arange(29))
    frame = prices.rename(columns={"close": "Close"}).assign(Trading_Halt=0)
    sigma = add_sigma_barriers(frame, pack["processing_contract"]["preprocessing"]).Sigma.iloc[29]
    column, sign = ("high", 1) if direction == "up" else ("close", -1)
    prices.loc[30, column] = 100 * (1 + sign * multiple * sigma)
    return prices


@pytest.mark.parametrize("direction,multiple,expected", [
    ("up", 1.6, (0, 0)), ("up", 2.0, (1, 0)),
    ("down", 1.3, (0, 0)), ("down", 2.0, (-1, 0)),
])
def test_labels_use_horizon_targets_instead_of_input_feature_barriers(pack, direction, multiple, expected):
    prices = price_path(pack, direction, multiple)
    for horizon, target in zip((5, 20), expected, strict=True):
        labels = live.labels_for(prices, horizon, pack)
        assert labels.label.iloc[29] == target


@pytest.mark.parametrize("value", [0, -1, float("nan"), float("inf"), True])
def test_invalid_pack_label_cannot_produce_a_score(pack, value):
    prices = price_path(pack, "up", 2.0)
    pack["horizons"]["h5"]["label_barriers"]["up_mult"] = value
    with pytest.raises(ValueError, match="Invalid H5 label barrier"):
        live.labels_for(prices, 5, pack)


def test_main_records_verified_evaluation_pack_and_distinct_horizon_labels(pack, tmp_path, monkeypatch):
    prices = price_path(pack, "up", 2.0)
    day = prices.trade_date.iloc[29].date().isoformat()
    log = [{"stock_code": "A", "as_of": day, "horizon": h,
            "prob_down": 0.05, "prob_neutral": 0.05, "prob_up": 0.9} for h in (5, 20)]
    config = tmp_path / "config.yaml"
    config.write_text("active_pack:\n  pack_id: evaluation-pack\n")
    monkeypatch.setattr(live, "config_path", lambda: config)
    monkeypatch.setattr(live, "serving_root", lambda: tmp_path)
    def verified_pack(path):
        assert path == tmp_path / "packs/evaluation-pack"
        return pack, {}
    monkeypatch.setattr(live, "load_pack", verified_pack)
    monkeypatch.setattr(live, "fetch", lambda table, _: log if table == "chart_prediction_log"
                        else prices.assign(trade_date=prices.trade_date.dt.strftime("%Y-%m-%d")).to_dict("records"))
    monkeypatch.setattr(live, "MIN_UNIVERSE", 1)
    monkeypatch.setattr(live, "OUT", tmp_path / "record.json")
    live.main()
    result = json.loads(live.OUT.read_text())
    assert result["evaluation_status"] == "computed"
    assert result["evaluation_basis"] == "fixed_pack_labels"
    assert result["evaluation_pack_id"] == "evaluation-pack"
    assert result["horizons"]["5"]["label_barriers"] == {"up_mult": 1.75, "down_mult": 1.5}
    assert result["horizons"]["20"]["label_barriers"] == {"up_mult": 3.75, "down_mult": 3.0}
    assert result["horizons"]["5"]["up"]["list_rate"] == 1
    assert result["horizons"]["20"]["up"]["list_rate"] == 0


def test_exact_ties_follow_dashboard_down_neutral_up_priority():
    day = pd.DataFrame({"stock_code": ["A", "B", "C", "D"],
                        "prob_down": [0.45, 0.1, 0.45, 1 / 3],
                        "prob_neutral": [0.1, 0.45, 0.45, 1 / 3],
                        "prob_up": [0.45, 0.45, 0.1, 1 / 3]})
    assert strong_lists(day) == {"up": [], "down": ["A", "C", "D"]}


def test_lists_follow_dashboard_rule_and_rates_use_labelled_rows(monkeypatch):
    monkeypatch.setattr(live, "MIN_UNIVERSE", 1)
    day = pd.DataFrame({"stock_code": ["A", "B", "C", "D"], "as_of": "2026-10-01",
                        "prob_down": [0.1, 0.2, 0.7, 0.3], "prob_neutral": [0.2, 0.5, 0.2, 0.3],
                        "prob_up": [0.7, 0.3, 0.1, 0.4]})
    assert strong_lists(day) == {"up": ["A", "D"], "down": ["C"]}  # B는 중립 1위라 빠진다
    labels = pd.DataFrame({"stock_code": ["A", "C", "D"], "as_of": "2026-10-01", "label": [1.0, 1.0, -1.0]})
    out = score(day, labels)
    assert out["days"] == 1 and not out["sufficient"]
    assert out["up"] == {"list_rate": 0.5, "list_n": 2, "list_unscored": 0, "all_rate": round(2 / 3, 4), "all_n": 3}
    assert out["down"]["list_rate"] == 0.0


def test_halted_stocks_are_not_list_candidates(monkeypatch):
    monkeypatch.setattr(live, "MIN_UNIVERSE", 1)
    day = pd.DataFrame({"stock_code": ["H", "T"], "as_of": "2026-10-01", "prob_down": [0.9, 0.7],
                        "prob_neutral": [0.05, 0.2], "prob_up": [0.05, 0.1], "volume": [0.0, 1200.0]})
    labels = pd.DataFrame({"stock_code": ["H", "T"], "as_of": "2026-10-01", "label": [None, -1.0]})
    out = score(day, labels)
    assert out["down"]["list_n"] == 1 and out["down"]["list_unscored"] == 0 and out["down"]["list_rate"] == 1.0
