import numpy as np
import pandas as pd
from stock_master import classify, grade_for, is_preferred, parse_managed_names


def _prices(code, closes, amount):
    dates = pd.bdate_range("2026-01-01", periods=len(closes))
    return pd.DataFrame({"Code": code, "Date": dates, "Close": closes, "Amount": amount})


def test_rules():
    rng = np.random.default_rng(0)
    calm = 50_000 * np.exp(np.cumsum(rng.normal(0, 0.005, 120)))
    wild = 50_000 * np.exp(np.cumsum(rng.normal(0, 0.05, 120)))
    universe = pd.DataFrame({
        "Code": ["000010", "000020", "000025", "000030", "000040", "000050", "247540"],
        "Name": ["안정", "급등락", "안정우", "동전", "관리기업", "거래정지", "에코프로비엠"],
    })
    prices = pd.concat([
        _prices("000010", calm, 9e10),
        _prices("000020", wild, 9e10),
        _prices("000025", calm, 9e10),
        _prices("000030", np.full(120, 900.0), 1e6),
        _prices("000040", calm, 9e10),
        _prices("000050", np.full(120, 5_000.0), 9e10),
        _prices("247540", calm[:30], 9e10),  # 변동성 미확인
    ])
    rows = {row["code"]: row for row in classify(universe, prices, {"관리기업"}, {"000010"})}

    assert rows["000020"]["risk_flags"] == ["high_volatility"]
    assert rows["000025"]["risk_flags"] == ["preferred_stock"]
    assert set(rows["000030"]["risk_flags"]) == {"penny_stock", "low_liquidity"}
    assert rows["000040"]["risk_flags"] == ["managed_stock"] and rows["000040"]["risk_grade"] == 1
    assert rows["000020"]["risk_grade"] < rows["000010"]["risk_grade"]
    assert rows["000050"]["risk_grade"] == 1  # 가격이 안 움직임 → 변동성 미확인
    assert rows["247540"]["risk_grade"] == 1 and rows["247540"]["market"] == "KOSDAQ"
    assert rows["000010"]["market"] == "KOSPI"
    assert rows["000020"]["volatility_percentile"] == 1.0 and rows["247540"]["volatility_percentile"] is None
    assert rows["000010"]["volatility_annual"] < rows["000020"]["volatility_annual"]


def test_preferred_and_kind_parsing():
    assert is_preferred("005935", "삼성전자우") and is_preferred("00104K", "CJ4우(전환)")
    assert not is_preferred("005930", "삼성전자") and not is_preferred("000105", "유한양행")
    page = ('<td class="first"><img alt="유가증권"> 모나미</a> <img alt="관리종목"/> </td>'
            '<td class="first">SG&amp;글로벌</td>')
    assert parse_managed_names(page) == {"모나미", "SG&글로벌"}


def test_absolute_grade_with_large_cap_relief():
    assert [grade_for(v, False) for v in (0.2, 0.3, 0.5, 0.7, 1.0)] == [5, 4, 3, 2, 1]
    assert grade_for(0.868, True) == 3  # 삼성전자(2026-10 실측 연 변동성) → 대형주 완화로 3
    assert grade_for(0.691, True) == 3 and grade_for(0.2, True) == 5
    assert grade_for(float("nan"), True) == 1
    assert type(grade_for(np.float64(0.5), False)) is int  # JSON으로 보낸다
