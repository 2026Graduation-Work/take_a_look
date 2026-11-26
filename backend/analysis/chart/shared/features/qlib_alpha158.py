import ast
import operator
import re
from importlib import metadata
from uuid import uuid4

import numpy as np
import pandas as pd

from shared.io import sha256

ENGINE = "qlib_alpha158_v097"
QLIB_VERSION = "0.9.7"
PRICE_COLUMNS = ("Open", "High", "Low", "Close", "Volume", "VWAP")


def upstream_identity():
    installed = metadata.version("pyqlib")
    if installed != QLIB_VERSION:
        raise ValueError(f"Alpha158 requires pyqlib=={QLIB_VERSION}, found {installed}")
    distribution = metadata.distribution("pyqlib")
    sources = ("qlib/contrib/data/loader.py", "qlib/data/ops.py", "qlib/data/base.py")
    return {
        "package": "pyqlib",
        "version": installed,
        "source_sha256": {name: sha256(distribution.locate_file(name)) for name in sources},
        "numeric_versions": {name: metadata.version(name) for name in ("numpy", "pandas", "scipy")},
        "input_dtype": "float32",
    }


def local_name(name):
    if name in {"KMID2", "KUP2", "KLOW2", "KSFT2"}:
        return name[:-1].lower() + "_2"
    if name in {"KMID", "KLEN", "KUP", "KLOW", "KSFT"}:
        return name.lower()
    match = re.fullmatch(r"([A-Z]+)(\d+)", name)
    if match is None:
        raise ValueError(f"Unknown upstream Alpha158 name: {name}")
    return f"{match[1].lower()}_{match[2]}"


def generate_alpha158_features(frame: pd.DataFrame) -> pd.DataFrame:
    """Append all 158 original factors, preserving source rows and local column names."""
    upstream_identity()
    error_policy = np.geterr()
    try:
        from qlib.contrib.data.loader import Alpha158DL
        from qlib.data import ops
        from qlib.data.base import Feature
        from qlib.data.cache import H
    finally:
        np.seterr(**error_policy)

    missing = set(PRICE_COLUMNS) - set(frame)
    if missing:
        raise ValueError(f"Actual OHLCV/VWAP columns required: {sorted(missing)}")
    if "Date" in frame:
        dates = pd.to_datetime(frame.Date)
        if dates.isna().any() or dates.duplicated().any() or not dates.is_monotonic_increasing:
            raise ValueError("Alpha158 requires unique ascending dates")
    fields, names = Alpha158DL.get_feature_config()
    columns = [local_name(name) for name in names]
    if set(columns) & set(frame):
        raise ValueError("Alpha158 input already contains feature columns")
    if frame.empty:
        return frame.join(pd.DataFrame(index=frame.index, columns=columns, dtype=float))
    prices = frame[list(PRICE_COLUMNS)].astype("float32").reset_index(drop=True)

    class FrameFeature(Feature):
        def _load_internal(self, instrument, start_index, end_index, freq):
            return prices[self._name.capitalize() if self._name != "vwap" else "VWAP"].loc[
                max(0, start_index):end_index
            ].copy()

    binary = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
              ast.Div: operator.truediv}
    comparisons = {ast.Gt: operator.gt, ast.Lt: operator.lt}

    def expression(node):
        if isinstance(node, ast.Constant) and isinstance(node.value, (str, int, float)):
            return node.value
        if isinstance(node, ast.BinOp) and type(node.op) in binary:
            return binary[type(node.op)](expression(node.left), expression(node.right))
        if isinstance(node, ast.Compare) and len(node.ops) == 1 and type(node.ops[0]) in comparisons:
            return comparisons[type(node.ops[0])](expression(node.left), expression(node.comparators[0]))
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and not node.keywords:
            constructor = FrameFeature if node.func.id == "Feature" else getattr(ops, node.func.id)
            return constructor(*(expression(arg) for arg in node.args))
        raise ValueError(f"Unsupported official Alpha158 expression: {ast.dump(node)}")

    instrument = "takealook-alpha158-" + uuid4().hex
    cache = H["f"]
    result = {}
    try:
        with np.errstate(divide="ignore", invalid="ignore"):
            for field, column in zip(fields, columns, strict=True):
                parsed = ast.parse(re.sub(r"\$(\w+)", r'Feature("\1")', field), mode="eval")
                values = expression(parsed.body).load(instrument, 0, len(frame) - 1, "day")
                result[column] = values.reindex(prices.index).to_numpy(dtype="float32", copy=True)
    finally:
        for key in list(cache.od):
            if key[1] == instrument:
                cache.pop(key)
    return pd.concat([frame.copy(), pd.DataFrame(result, index=frame.index)], axis=1)
