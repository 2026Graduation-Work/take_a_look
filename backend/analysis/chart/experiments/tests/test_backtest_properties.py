"""Seeded random markets: ledger invariants, order invariance, and label-execution agreement."""
import numpy as np
import pandas as pd
import pytest
from backtest_harness import check_ledger, config
from experiments.backtest.local_execution import simulate
from experiments.train_src.labels import barrier_labels

CODES = ["000001", "000002", "000003", "000004", "000005"]


def random_market(rng, codes=CODES, n_days=30, halt_rate=0.05):
    days = pd.bdate_range("2024-01-02", periods=n_days)
    rows = []
    for code in codes:
        close = 100.0
        for day in days:
            previous = close
            if rng.random() < halt_rate:
                rows.append({"Date": day, "Code": code, "Open": close, "High": close, "Low": close,
                             "Close": close, "Sigma": 0.03, "Trading_Halt": 1})
                continue
            open_ = previous * np.exp(rng.normal(0, 0.015))
            close = previous * np.exp(rng.normal(0, 0.03))
            high = max(open_, close) * np.exp(abs(rng.normal(0, 0.01)))
            low = min(open_, close) * np.exp(-abs(rng.normal(0, 0.01)))
            rows.append({"Date": day, "Code": code, "Open": open_, "High": high, "Low": low,
                         "Close": close, "Sigma": rng.uniform(0.02, 0.05), "Trading_Halt": 0})
    return pd.DataFrame(rows)


def random_config(rng):
    def multiplier():
        return None if rng.random() < 0.2 else float(rng.uniform(0.5, 3.0))
    return config(top_n=3, initial_cash=float(rng.uniform(1e3, 1e7)),
                  fee=float(rng.choice([0.0, 0.00105, 0.0025])),
                  max_holding_days=int(rng.integers(1, 7)),
                  up_mult=multiplier(), down_mult=multiplier(), hard_sl_mult=multiplier())


def random_entries(rng, prices, top_n=3):
    days = pd.DatetimeIndex(sorted(prices.Date.unique()))
    entries = pd.DataFrame(False, index=days, columns=CODES)
    for day in days[1:]:
        picks = rng.choice(CODES, size=int(rng.integers(0, top_n + 1)), replace=False)
        entries.loc[day, list(picks)] = True
    return entries


@pytest.mark.parametrize("seed", range(25))
def test_random_markets_keep_an_exact_ledger(seed):
    rng = np.random.default_rng(seed)
    prices = random_market(rng)
    cfg = random_config(rng)
    entries = random_entries(rng, prices)
    result = simulate(cfg, entries, prices)
    check_ledger(result, cfg, prices)
    reordered = simulate(cfg, entries[entries.columns[::-1]], prices)
    pd.testing.assert_series_equal(result.value(), reordered.value())


LABEL = {"horizon": 5, "up_mult": 1.75, "down_mult": 1.5}
UP_EXITS = {"intraday_profit", "profit_gap"}
HARD_STOP_EXITS = {"intraday_stop", "stop_gap"}


def executed_class(trade, anchor, sigma):
    if trade.exit_reason in UP_EXITS:
        return 1
    if trade.exit_reason == "close_stop_next_open":
        return -1
    assert trade.exit_reason == "holding_expiry", trade.exit_reason
    return -1 if trade.exit_price <= anchor * (1 - LABEL["down_mult"] * sigma) else 0


@pytest.mark.parametrize("hard_sl_mult", [None, 1.2])
@pytest.mark.parametrize("seed", range(8))
def test_execution_resolves_the_same_barrier_event_as_the_label(seed, hard_sl_mult):
    """A trade entered on a signal must end where barrier_labels says that signal ended.

    Allowed differences, both execution-only rules the label does not have:
    a session that touches the profit line intraday and closes below the soft stop (the label
    calls it down; a resting order sells at profit), and the hard stop on the intraday low.
    """
    rng = np.random.default_rng(seed)
    prices = random_market(rng, codes=["000001"], n_days=45)
    labels = barrier_labels(prices, LABEL["horizon"], up_mult=LABEL["up_mult"],
                            down_mult=LABEL["down_mult"])
    cfg = config(max_holding_days=LABEL["horizon"], up_mult=LABEL["up_mult"],
                 down_mult=LABEL["down_mult"], hard_sl_mult=hard_sl_mult)
    days = pd.DatetimeIndex(prices.Date)
    compared = 0
    for t in range(len(days) - 1):
        if np.isnan(labels.iloc[t]) or prices.Trading_Halt.iloc[t + 1]:
            continue
        entries = pd.DataFrame(False, index=days, columns=["000001"])
        entries.iloc[t + 1] = True
        result = simulate(cfg, entries, prices)
        if result.trades.empty:
            assert result.exclusions[0]["reason"] == "open_beyond_barrier"
            continue
        trade = result.trades.iloc[0]
        if trade.exit_reason == "period_end":
            continue
        if trade.exit_reason in HARD_STOP_EXITS:
            assert hard_sl_mult is not None
            continue
        anchor, sigma = prices.Close.iloc[t], prices.Sigma.iloc[t]
        executed = executed_class(trade, anchor, sigma)
        if executed != labels.iloc[t]:
            exit_bar = prices.loc[prices.Date.eq(trade.exit_date)].iloc[0]
            assert (executed, labels.iloc[t]) == (1, -1)
            assert exit_bar.Close <= anchor * (1 - LABEL["down_mult"] * sigma)
        compared += 1
    assert compared >= 10
