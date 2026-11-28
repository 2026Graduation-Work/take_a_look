//! `experiments.e0_range.monthly_ranges`의 칸별 분위수 계산을 Rust로 옮기는 자리(#534).
//! 뼈대 단계라 아직 계산하지 않는다. 계약은 `experiments/tests/test_native_monthly_quantiles.py`의 `reference`다.

use numpy::PyReadonlyArray1;
use pyo3::exceptions::PyNotImplementedError;
use pyo3::prelude::*;

/// 달 m마다 `window_start[m] <= return_day < window_end[m]`인 행을 칸(`cell`)별로 모아
/// `value`의 10, 50, 90% 분위수(pandas 기본 linear 보간)를 구한다. 표본이 `min_cell` 미만인 칸은 뺀다.
/// 반환: (달 번호, 칸, q10, q50, q90, 표본 수) 배열 여섯 개, 달 번호와 칸 순서로 정렬.
#[pyfunction]
#[allow(unused_variables)]
fn monthly_quantiles(
    window_start: PyReadonlyArray1<i64>,
    window_end: PyReadonlyArray1<i64>,
    return_day: PyReadonlyArray1<i64>,
    cell: PyReadonlyArray1<i64>,
    value: PyReadonlyArray1<f64>,
    min_cell: usize,
) -> PyResult<()> {
    Err(PyNotImplementedError::new_err("monthly_quantiles: #534에서 구현 예정"))
}

#[pymodule]
fn takealook_native(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(monthly_quantiles, m)?)
}
