import experiments.live_record as live
import pandas as pd
from experiments.live_record import score, strong_lists


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
