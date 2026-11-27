"""Rust 확장(#534)이 Python 계산과 같은 칸별 분위수를 내는지. 확장이 없으면 건너뛴다."""

import numpy as np
import pandas as pd
import pytest


def reference(window_start, window_end, return_day, cell, value, min_cell):
    """`e0_range.monthly_ranges` 안의 분위수 단계와 같은 계산(정수 날짜 버전)."""
    frame = pd.DataFrame({"return_day": return_day, "cell": cell, "value": value})
    rows = []
    for month, (start, end) in enumerate(zip(window_start, window_end)):
        past = frame.loc[(frame.return_day >= start) & (frame.return_day < end)].groupby("cell").value
        if not past.ngroups:
            continue
        q = past.quantile([0.1, 0.5, 0.9]).unstack().set_axis(["q10", "q50", "q90"], axis=1)
        q = q.assign(n=past.size()).loc[lambda t: t.n >= min_cell]
        rows.append(q.reset_index().assign(month=month))
    columns = ["month", "cell", "q10", "q50", "q90", "n"]
    return pd.concat(rows)[columns].reset_index(drop=True) if rows else pd.DataFrame(columns=columns)


def synthetic(seed=0, rows=20_000, months=24, cells=15):
    rng = np.random.default_rng(seed)
    starts = np.arange(months, dtype=np.int64) * 30
    # 같은 값이 많은 경우와 칸이 비는 달도 섞는다
    value = np.round(rng.normal(0, 0.05, rows), 3)
    return (starts - 360, starts, rng.integers(-400, months * 30, rows).astype(np.int64),
            rng.integers(0, cells, rows).astype(np.int64), value)


def test_reference_drops_small_cells():
    out = reference(*synthetic(), min_cell=200)
    assert (out.n >= 200).all() and out.q10.le(out.q50).all() and out.q50.le(out.q90).all()


@pytest.mark.parametrize("min_cell", [1, 200])
def test_native_matches_reference(min_cell):
    native = pytest.importorskip("takealook_native")
    data = synthetic()
    try:
        got = native.monthly_quantiles(*data, min_cell)
    except NotImplementedError:
        pytest.skip("뼈대 단계: #534에서 구현")
    expected = reference(*data, min_cell=min_cell)
    actual = pd.DataFrame(dict(zip(expected.columns, got)))
    pd.testing.assert_frame_equal(actual, expected, check_dtype=False, rtol=1e-12, atol=1e-12)
