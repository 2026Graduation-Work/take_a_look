"""Integer orders and explicit zero-recovery delisting losses."""

import pandas as pd
import pytest
from experiments.backtest.local_execution import save_execution, simulate


def inputs(cash=1000, price=100):
    days = pd.bdate_range("2024-01-02", periods=3)
    config = {"strategy": {"top_n": 1}, "backtest": {
        "initial_cash": cash, "fee": 0.01, "max_holding_days": 5}}
    entries = pd.DataFrame({"000700": [True, False, False]}, index=days)
    entries.attrs["signal_sigma"] = pd.DataFrame(0.1, index=days, columns=entries.columns)
    prices = pd.DataFrame({"Date": days, "Code": "000700", "Open": price,
                           "High": price, "Low": price, "Close": price,
                           "Sigma": 0.1, "Trading_Halt": 0})
    return config, entries, prices


@pytest.mark.parametrize("cash,price", [(1000, 100), (2.3283064365386963e-10, 7120), (100, 100)])
def test_integer_orders_and_fee_inclusive_unaffordable_order_is_skipped(cash, price):
    config, entries, prices = inputs(cash, price)
    result = simulate(config, entries, entries.astype(float), prices)
    if cash == 1000:
        assert result.events.iloc[0].quantity == 9
        assert result.portfolio.cash().iloc[-1] == pytest.approx(91)
        assert result.value().iloc[-1] == pytest.approx(991)
    else:
        assert result.value().iloc[-1] == pytest.approx(cash)
        assert result.events.empty
        assert result.open_positions == []
        assert result.exclusions[0]["reason"] == "insufficient_cash"


def test_confirmed_delisting_writes_off_without_cash_or_fake_sale(tmp_path):
    config, entries, prices = inputs()
    date = entries.index[-1]
    pd.DataFrame({"Code": ["000700"], "DelistingDate": [date]}).to_csv(
        tmp_path / "ticker_metadata.csv", index=False)
    config["dataset"] = {"root": str(tmp_path)}
    prices = prices.iloc[:-1]
    result = simulate(config, entries, entries.astype(float), prices)
    assert result.value().tolist() == pytest.approx([991, 991, 91])
    assert result.portfolio.cash().iloc[-1] == pytest.approx(91)
    assert result.open_positions == []
    assert result.events.side.tolist() == ["buy", "writeoff"]
    record = result.trade_records().iloc[0]
    assert record.Status == "Closed"
    assert record["Avg Exit Price"] == 0
    assert record["Exit Timestamp"] == date + pd.Timedelta(hours=9)
    assert record.PnL == pytest.approx(-909)
    assert record.Return == pytest.approx(-1.01)  # Full principal loss plus entry fee.
    (tmp_path / "output").mkdir()
    save_execution(result, tmp_path / "output")
    assert pd.read_csv(tmp_path / "output/trades.csv").iloc[0].PnL == pytest.approx(-909)


def test_ordinary_missing_price_is_still_an_error():
    config, entries, prices = inputs()
    with pytest.raises(ValueError, match="lost valuation"):
        simulate(config, entries, entries.astype(float), prices.iloc[:-1])


def test_confirmed_delisting_is_not_applied_before_its_date(tmp_path):
    config, entries, prices = inputs()
    pd.DataFrame({"Code": ["000700"], "DelistingDate": [entries.index[-1] + pd.Timedelta(days=1)]}).to_csv(
        tmp_path / "ticker_metadata.csv", index=False)
    config["dataset"] = {"root": str(tmp_path)}
    with pytest.raises(ValueError, match="lost valuation"):
        simulate(config, entries, entries.astype(float), prices.iloc[:-1])
