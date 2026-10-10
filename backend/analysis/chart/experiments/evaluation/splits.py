from experiments.experiment_utils import resolve_splits


def get_sliding_splits(config: dict) -> list[dict]:
    data_cfg = config.setdefault("data", {})
    original_strategy = data_cfg.get("split_strategy", "sliding")
    data_cfg["split_strategy"] = "sliding"
    try:
        return resolve_splits(config)
    finally:
        data_cfg["split_strategy"] = original_strategy


def get_regime_splits(config: dict) -> list[dict]:
    data_cfg = config.setdefault("data", {})
    original_strategy = data_cfg.get("split_strategy", "sliding")
    data_cfg["split_strategy"] = "regime"
    try:
        return resolve_splits(config)
    finally:
        data_cfg["split_strategy"] = original_strategy
