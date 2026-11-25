"""Hand-computed execution scenarios. Each row is one rule in backtest/EXECUTION_SPEC.md.

Signal day 0 closes at 100 with Sigma 0.1, so every position entered on day 1 has
profit line 110 (up 1.0), soft stop 90 (down 1.0) and hard stop 85 (hard 1.5).
Cash 1000 at open 101 buys 9 shares.
"""
import pandas as pd
import pytest
from backtest_harness import DAYS, bars, check_ledger, config, signals
from experiments.backtest.local_execution import save_execution, simulate

SIGNAL = (100, 100, 100, 100)
FLAT = (101, 101, 101, 101)
HALT = {"O": 101, "H": 101, "L": 101, "C": 101, "halt": 1}

SCENARIOS = {
    # name: (path from day 0, backtest overrides, [(entry, exit, exit price, reason, sessions)])
    "expiry_sells_at_close_of_last_session": (
        [SIGNAL, FLAT, FLAT, FLAT, FLAT], {}, [(1, 3, 101, "holding_expiry", 3)]),
    "high_exactly_at_the_profit_line_takes_profit": (
        [SIGNAL, (100, 110, 100, 100), FLAT, FLAT], {}, [(1, 1, 110, "intraday_profit", 1)]),
    "high_just_below_the_profit_line_does_not": (
        [SIGNAL, (100, 109.99, 100, 100), FLAT, FLAT, FLAT], {}, [(1, 3, 101, "holding_expiry", 3)]),
    "intraday_profit_fills_at_line": (
        [SIGNAL, FLAT, (101, 112, 100, 105), FLAT], {}, [(1, 2, 110, "intraday_profit", 2)]),
    "dual_touch_takes_the_stop": (
        [SIGNAL, FLAT, (101, 112, 80, 100), FLAT], {}, [(1, 2, 85, "intraday_stop", 2)]),
    "close_below_soft_stop_sells_next_open": (
        [SIGNAL, FLAT, (101, 101, 89, 89), (95, 96, 94, 95), FLAT], {},
        [(1, 3, 95, "close_stop_next_open", 2)]),
    "gap_below_hard_stop_sells_at_open": (
        [SIGNAL, FLAT, (80, 81, 79, 80), FLAT], {}, [(1, 2, 80, "stop_gap", 1)]),
    "gap_above_profit_sells_at_open": (
        [SIGNAL, FLAT, (115, 116, 114, 115), FLAT], {}, [(1, 2, 115, "profit_gap", 1)]),
    "halted_session_does_not_count": (
        [SIGNAL, FLAT, HALT, FLAT, FLAT, FLAT], {}, [(1, 4, 101, "holding_expiry", 3)]),
    "expiry_wins_over_soft_stop_on_last_session": (
        [SIGNAL, FLAT, FLAT, (101, 101, 89, 89), FLAT], {}, [(1, 3, 89, "holding_expiry", 3)]),
    "period_end_liquidates_at_final_close": (
        [SIGNAL, FLAT, FLAT], {"max_holding_days": 10}, [(1, 2, 101, "period_end", 2)]),
    "open_beyond_profit_line_skips_entry": (
        [SIGNAL, (111, 112, 110, 111), FLAT], {}, []),
    "upper_limit_open_is_not_filled": (
        [SIGNAL, (130, 130, 130, 130), FLAT], {"up_mult": None}, []),
    "locked_lower_limit_defers_the_stop_to_next_open": (
        [SIGNAL, FLAT, (70.7, 70.7, 70.7, 70.7), (72, 75, 70, 74), FLAT], {},
        [(1, 3, 72, "limit_down_locked", 2)]),
    "open_at_lower_limit_defers_the_opening_sell_even_if_it_unlocks": (
        [SIGNAL, FLAT, (70.7, 71.5, 70.7, 70.7), FLAT], {}, [(1, 3, 101, "limit_down_locked", 2)]),
    "unlocked_lower_limit_day_still_sells": (
        [SIGNAL, FLAT, (75, 76, 70.7, 70.7), FLAT], {}, [(1, 2, 75, "stop_gap", 1)]),
}


def run(path, entry_days=((1, "000001"),), **backtest):
    prices = bars(path)
    cfg = config(**backtest)
    result = simulate(cfg, signals(prices, entry_days), prices)
    check_ledger(result, cfg, prices)
    return result


def as_rows(trades):
    return [(DAYS.get_loc(t.entry_date), DAYS.get_loc(t.exit_date), round(t.exit_price, 9), t.exit_reason,
             t.holding_sessions) for t in trades.itertuples()]


@pytest.mark.parametrize("name", SCENARIOS)
def test_execution_scenario(name):
    path, backtest, expected = SCENARIOS[name]
    assert as_rows(run(path, **backtest).trades) == expected


def test_forced_exit_then_same_open_reentry_uses_new_signal_anchor():
    # Day 3 sells the soft stop at the open and re-enters on day 2's signal: anchor 89,
    # profit line 97.9. Day 4 opens at 101, above that line, so it sells at the open.
    path = [SIGNAL, FLAT, (101, 101, 89, 89), (95, 96, 94, 95), FLAT, FLAT]
    result = run(path, ((1, "000001"), (3, "000001")))
    assert as_rows(result.trades) == [
        (1, 3, 95, "close_stop_next_open", 2), (3, 4, 101, "profit_gap", 1)]


def test_fees_charge_both_sides_and_size_includes_entry_fee():
    result = run([SIGNAL, FLAT, FLAT, FLAT, FLAT], fee=0.01)
    assert result.trades.quantity.tolist() == [9]
    assert result.value().iloc[-1] == pytest.approx(1000 - 9 * 101 * 1.01 + 9 * 101 * 0.99)


def test_slippage_worsens_both_fills_and_sizes_on_the_slipped_price():
    result = run([SIGNAL, FLAT, FLAT, FLAT, FLAT], slippage_bps=10)
    buy, sell = 101 * 1.001, 101 * 0.999
    assert result.trades.quantity.tolist() == [9]
    assert result.trades.entry_price.iloc[0] == pytest.approx(buy)
    assert result.trades.exit_price.iloc[0] == pytest.approx(sell)
    assert result.value().iloc[-1] == pytest.approx(1000 - 9 * buy + 9 * sell)


def test_locked_lower_limit_on_the_final_day_leaves_the_position_open():
    result = run([SIGNAL, FLAT, (70.7, 70.7, 70.7, 70.7)], max_holding_days=10)
    assert result.trades.empty
    assert [position["code"] for position in result.open_positions] == ["000001"]
    assert result.value().iloc[-1] == pytest.approx(1000 - 9 * 101 + 9 * 70.7)


def test_order_is_capped_at_share_of_prior_average_traded_value():
    # 1% of the prior average traded value 50,000 is 500 won: 4 shares at 101.
    path = [{"O": 100, "H": 100, "L": 100, "C": 100, "amount": 50_000}] + [
        {"O": 101, "H": 101, "L": 101, "C": 101, "amount": 50_000}] * 3
    result = run(path, max_participation=0.01)
    assert result.trades.quantity.tolist() == [4]
    assert result.exclusions == [{"date": "2024-01-03", "code": "000001", "reason": "liquidity_capped"}]


def test_opening_decision_does_not_depend_on_the_rest_of_the_day():
    # Same open (at the lower limit) and low; only the day's high differs. Nothing may sell at 09:00.
    for high in (70.7, 71.5):
        result = run([SIGNAL, FLAT, (70.7, high, 70.7, 70.7), FLAT])
        opening = result.events.loc[pd.to_datetime(result.events.date).eq(DAYS[2] + pd.Timedelta(hours=9))]
        assert opening.empty


def test_a_sale_deferred_at_the_open_waits_for_the_next_open():
    # Day 2 opens at the lower limit (gap stop blocked). It later trades above the profit line,
    # but the deferred sale is not re-judged intraday: it sells at day 3's open.
    path = [SIGNAL, FLAT, (70.7, 111, 70.7, 100), (98, 99, 97, 98), FLAT]
    assert as_rows(run(path).trades) == [(1, 3, 98, "limit_down_locked", 2)]


def test_cap_uses_prior_traded_value_not_the_same_day():
    # Prior value 4,000 × 2.5% = 100 won: 1 share at 100, although today's value is 400,000.
    path = [{"O": 100, "H": 100, "L": 100, "C": 100, "amount": 4_000},
            {"O": 100, "H": 100, "L": 100, "C": 100, "amount": 400_000}, FLAT]
    result = run(path, max_participation=0.025)
    assert result.trades.quantity.tolist() == [1]


def test_unknown_traded_value_blocks_entry_when_the_cap_is_on():
    path = [{"O": 100, "H": 100, "L": 100, "C": 100, "amount": float("nan")}] + [
        {"O": 101, "H": 101, "L": 101, "C": 101, "amount": float("nan")}] * 3
    result = run(path, max_participation=0.025)
    assert result.events.empty
    assert result.exclusions[0]["reason"] == "liquidity_unknown"


def test_turnover_is_half_traded_notional_over_mean_equity_annualized():
    result = run([SIGNAL, FLAT, FLAT, FLAT, FLAT])
    assert result.turnover() == pytest.approx((9 * 101 * 2 / 2) / 1000 * 252 / 5)


@pytest.mark.parametrize("cash", [100, 2.3283064365386963e-10])
def test_unaffordable_order_is_skipped(cash):
    result = run([SIGNAL, FLAT, FLAT], initial_cash=cash)
    assert result.events.empty
    assert result.value().iloc[-1] == pytest.approx(cash)
    assert result.exclusions[0]["reason"] == "insufficient_cash"


def delisted_inputs(tmp_path, delisting_day):
    prices = bars([SIGNAL, FLAT, FLAT, FLAT])
    prices = prices.loc[prices.Date.ne(DAYS[3])]
    pd.DataFrame({"Code": ["000001"], "DelistingDate": [delisting_day]}).to_csv(
        tmp_path / "ticker_metadata.csv", index=False)
    cfg = config(max_holding_days=10, fee=0.01)
    cfg["dataset"] = {"root": str(tmp_path)}
    entries = signals(bars([SIGNAL, FLAT, FLAT, FLAT]), [(1, "000001")])
    return cfg, entries, prices


def test_confirmed_delisting_writes_off_without_cash_or_fake_sale(tmp_path):
    cfg, entries, prices = delisted_inputs(tmp_path, DAYS[3])
    result = simulate(cfg, entries, prices)
    check_ledger(result, cfg, prices)
    cost = 9 * 101 * 1.01
    assert result.value().tolist() == pytest.approx([1000, 1000 - cost + 909, 1000 - cost + 909, 1000 - cost])
    assert result.events.side.tolist() == ["buy", "writeoff"]
    trade = result.trades.iloc[0]
    assert trade.exit_reason == "delisting_zero_recovery"
    assert trade.exit_price == 0
    assert trade.pnl == pytest.approx(-cost)
    assert trade["return"] == pytest.approx(-1.0)  # Every won spent, entry fee included.
    (tmp_path / "output").mkdir()
    save_execution(result, tmp_path / "output")
    assert pd.read_csv(tmp_path / "output/trades.csv").iloc[0].pnl == pytest.approx(-cost)


def test_ordinary_missing_price_is_still_an_error():
    prices = bars([SIGNAL, FLAT, FLAT])
    entries = signals(bars([SIGNAL, FLAT, FLAT, FLAT]), [(1, "000001")])
    with pytest.raises(ValueError, match="lost valuation"):
        simulate(config(), entries, prices)


def test_confirmed_delisting_is_not_applied_before_its_date(tmp_path):
    cfg, entries, prices = delisted_inputs(tmp_path, DAYS[3] + pd.Timedelta(days=1))
    with pytest.raises(ValueError, match="lost valuation"):
        simulate(cfg, entries, prices)
