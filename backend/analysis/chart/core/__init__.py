"""Load optional configuration and training helpers only when requested."""

__all__ = ["load_config", "cfg", "generate_full_alpha158_features", "normalize_trading_halts"]


def __getattr__(name):
    if name in {"load_config", "cfg"}:
        from . import config
        return getattr(config, name)
    if name in {"generate_full_alpha158_features", "normalize_trading_halts"}:
        from . import features
        return getattr(features, name)
    raise AttributeError(name)
