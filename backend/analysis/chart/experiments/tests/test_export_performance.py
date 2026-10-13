import numpy as np
import pandas as pd
import pytest
from experiments.export_performance import (
    checked_manifest,
    metric_row,
    paired_frames,
    validate_pair_contract,
)


def predictions():
    return pd.DataFrame({"Date": pd.to_datetime(["2019-01-07", "2019-01-07", "2020-01-07", "2020-01-07"]),
                         "Code": ["005930", "000660"] * 2, "fold_id": [0, 0, 1, 1],
                         "Y_Label": [0, 2, 0, 2], "label_observed": True,
                         "Prob": [.2, .8, .8, .2], "prob_up": [.2, .8, .8, .2]})


def test_export_means_are_independent_annual_results_and_volatile_strategy_is_unavailable():
    backtest = pd.DataFrame({"sharpe_ratio": [1., -1.], "max_drawdown": [-.1, -.2],
                             "total_return": [.2, -.1], "number_of_trades": [2, 3]})
    arguments = dict(profile="stable", variant="A", feature_count=170)
    row = metric_row(predictions(), backtest, sample="all", **arguments)
    assert row['auc'] == .5
    assert row['cumulative_return'] == pytest.approx(.05)  # Not compounded across independent years.
    assert row['trade_count'] == 5
    assert row['sample_dates'] == 2 and row['sample_rows'] == 4
    volatile = metric_row(predictions(), None, sample="volatile_top_20pct", **arguments)
    assert all(volatile[key] is None for key in ('sharpe', 'mdd', 'cumulative_return', 'trade_count'))


def test_export_rejects_different_samples_labels_duplicates_and_score_columns():
    a = predictions()
    paired_frames(a, a.iloc[::-1])
    changed = a.copy()
    changed.loc[0, 'Y_Label'] = 2
    with pytest.raises(ValueError, match='samples or labels'):
        paired_frames(a, changed)
    with pytest.raises(ValueError, match='Duplicate'):
        paired_frames(a, pd.concat([a, a.iloc[:1]]))
    changed = a.copy()
    changed.loc[0, 'Prob'] = np.nan
    with pytest.raises(ValueError, match='score columns'):
        paired_frames(a, changed)


def test_pinned_manifests_and_full_pair_contract(tmp_path):
    import copy

    from experiments.features.psychology.market_psychology import RAW_FEATURES
    from shared.io import sha256
    from shared.settings import BASE_FEATURES, FLOW_FEATURES
    path = tmp_path / "run_manifest.json"
    path.write_text('{"config": {}}')
    digest = sha256(path)
    assert checked_manifest(path, digest) == {"config": {}}
    path.write_text('{"config": {"changed": true}}')
    with pytest.raises(ValueError, match="manifest changed"):
        checked_manifest(path, digest)
    a = {"config": {key: {} for key in ("labels", "model", "strategy", "backtest", "dataset")},
         "feature_columns": list(BASE_FEATURES) + list(FLOW_FEATURES), "processing_contract": {"sha256": "same"}}
    a["config"].update(data={"price_dir": "a", "point_in_time": False}, features={"groups": ["base", "flow"]})
    b = copy.deepcopy(a)
    b["config"]["data"]["price_dir"] = "b"
    b["config"]["features"]["groups"].append("psychology")
    b["feature_columns"] += list(RAW_FEATURES)
    validate_pair_contract(a, b)
    changed = copy.deepcopy(b)
    changed["config"]["data"]["point_in_time"] = True
    with pytest.raises(ValueError, match="data settings"):
        validate_pair_contract(a, changed)
    changed = copy.deepcopy(b)
    changed["feature_columns"][-1] = "arbitrary_treatment"
    with pytest.raises(ValueError, match="treatment feature"):
        validate_pair_contract(a, changed)
