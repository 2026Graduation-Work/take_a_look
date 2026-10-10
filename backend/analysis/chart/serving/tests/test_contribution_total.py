import numpy as np
import pandas as pd
import pytest
from jsonschema import ValidationError
from serving.contracts import validate_snapshot
from serving.internal.inference import infer_batch
from serving.publish_preview import load_preview


@pytest.mark.parametrize("target", [0, 1, 2])
def test_denominator_includes_omitted_features_but_excludes_bias(target):
    class Model:
        def feature_name(self):
            return [f"roc_{n}" for n in (5, 10, 20, 30, 60)] + ["ma_5"]

        def predict(self, frame, *, raw_score=False, pred_contrib=False, num_threads=2):
            if pred_contrib:
                blocks = np.ones((3, 7))
                blocks[target] = [-6., -5., -4., 3., 2., 1., 100.]
                return blocks.reshape(1, -1)
            raw = np.full((1, 3), 7.)
            raw[0, target] = 91.
            scores = np.full((1, 3), .15)
            scores[0, target] = .7
            return raw if raw_score else scores

    model = Model()
    _, features, _, total = infer_batch(model, pd.DataFrame([{n: 1. for n in model.feature_name()}]))[0]
    assert len(features) == 5
    assert sum(abs(f["contribution"]) for f in features) == 20
    assert features[0]["contribution"] == -6
    assert total == 21  # Includes the sixth feature; excludes the 100-point bias.


def test_preview_denominators_validate_and_old_snapshots_remain_supported(legacy_preview_pack):
    _, snapshots, _ = load_preview()
    for snapshot in snapshots:
        total = snapshot["inference"].pop("contribution_abs_sum")
        validate_snapshot(snapshot)
        for invalid in (0, -1, float("nan"), float("inf")):
            snapshot["inference"]["contribution_abs_sum"] = invalid
            with pytest.raises((ValueError, ValidationError)):
                validate_snapshot(snapshot)
        snapshot["inference"]["contribution_abs_sum"] = total
        validate_snapshot(snapshot)
