import numpy as np
import pandas as pd


def _is_valid_benchmark(series: pd.Series) -> tuple[bool, str]:
    if series.empty:
        return False, "empty benchmark"
    if series.isna().all():
        return False, "all NaN"
    filled = series.fillna(0.0)
    if filled.abs().sum() == 0.0:
        return False, "all zero returns"
    total_return = (1.0 + filled).prod() - 1.0
    if abs(total_return) < 1e-12:
        return False, "0.00% total return"
    return True, "valid"


def _attach_benchmark_attrs(series: pd.Series, source: str, reason: str) -> pd.Series:
    valid, validity_reason = _is_valid_benchmark(series)
    result = series.rename("Benchmark_Custom_KRX")
    result.attrs["benchmark_source"] = source
    result.attrs["benchmark_reason"] = reason
    result.attrs["benchmark_valid"] = valid
    result.attrs["benchmark_validity_reason"] = validity_reason
    return result


def configured_benchmark(config, index, price_df):
    path = config.get("evaluation", {}).get("benchmark_file")
    if not path:
        raise ValueError("evaluation.benchmark_file must identify a frozen dataset index")
    from experiments.config import chart_path
    path = chart_path(path)
    frame = pd.read_parquet(path) if path.suffix == ".parquet" else pd.read_csv(path, parse_dates=["Date"])
    frame["Date"] = pd.to_datetime(frame["Date"])
    frame = frame.set_index("Date")
    if frame.index.duplicated().any():
        raise ValueError("Duplicate benchmark dates")
    returns = frame["Close"].sort_index().pct_change(fill_method=None).reindex(index)
    if returns.isna().any() or not np.isfinite(returns).all():
        raise ValueError("Benchmark must cover every evaluation day and preceding close")
    return _attach_benchmark_attrs(returns, str(path), "frozen daily closes; no dividends")
