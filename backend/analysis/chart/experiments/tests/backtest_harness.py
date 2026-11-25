"""Builders and an independent ledger replay for executor tests.

check_ledger recomputes cash, holdings and equity from orders alone, without the
executor or VectorBT, so a test that passes it cannot hide an accounting error.
"""
import pandas as pd
import pytest

DAYS = pd.bdate_range("2024-01-02", periods=12)


def bars(path, code="000001", days=DAYS):
    """path: list of (open, high, low, close) or dicts with optional halt/sigma per day."""
    rows = []
    for day, bar in zip(days, path, strict=False):
        bar = bar if isinstance(bar, dict) else dict(zip("OHLC", bar, strict=True))
        rows.append({"Date": day, "Code": code, "Open": bar["O"], "High": bar["H"],
                     "Low": bar["L"], "Close": bar["C"], "Sigma": bar.get("sigma", 0.1),
                     "Trading_Halt": bar.get("halt", 0), "Amount": bar.get("amount", 1e12)})
    return pd.DataFrame(rows)


def signals(prices, entry_days):
    days = pd.DatetimeIndex(sorted(prices.Date.unique()))
    codes = sorted(prices.Code.unique())
    entries = pd.DataFrame(False, index=days, columns=codes)
    for day, code in entry_days:
        entries.iloc[day, codes.index(code)] = True
    return entries


def config(**backtest):
    return {"strategy": {"top_n": backtest.pop("top_n", 1)}, "backtest": {
        "initial_cash": 1000.0, "fee": 0.0, "slippage_bps": 0, "max_participation": None,
        "max_holding_days": 3, "signal_lag_days": 1,
        "up_mult": 1.0, "down_mult": 1.0, "hard_sl_mult": 1.5, **backtest}}


def check_ledger(result, cfg, prices):
    bt = cfg["backtest"]
    fee = bt["fee"]
    participation = bt.get("max_participation")
    slippage = bt["slippage_bps"] / 10_000
    bar = prices.assign(Date=pd.to_datetime(prices.Date)).sort_values("Date")
    bar["PreviousClose"] = bar.groupby("Code").Close.shift(1)
    # Traded value known before the session: mean of up to 20 prior sessions, never today's.
    bar["PriorValue"] = bar.groupby("Code").Amount.transform(
        lambda values: values.shift(1).rolling(20, min_periods=1).mean())
    bar = bar.set_index(["Date", "Code"])
    cash, held, lots, rebuilt = float(bt["initial_cash"]), {}, {}, []
    events = result.events
    days = result.value().index
    for day in days:
        todays = events.loc[pd.to_datetime(events.date).dt.normalize().eq(day)] if len(events) else []
        for event in (todays.itertuples() if len(todays) else []):
            row = None if event.side == "writeoff" else bar.loc[(day, event.code)]
            notional = event.quantity * event.price
            assert event.fee == pytest.approx(notional * fee if event.side != "writeoff" else 0)
            if event.side == "buy":
                assert event.code not in held, "bought a held code"
                assert row.Trading_Halt == 0, "filled on a halted session"
                assert event.reference_price == row.Open, "entry must fill at the open"
                assert not row.Open >= 1.29 * row.PreviousClose, "bought an upper-limit open"
                if participation is not None:
                    assert notional <= participation * row.PriorValue + 1e-9, "liquidity cap exceeded"
                assert event.price == pytest.approx(event.reference_price * (1 + slippage))
                cash -= notional + event.fee
                held[event.code] = event.quantity
                lots[event.code] = (day, event.price, event.fee)
            else:
                assert held.pop(event.code) == event.quantity, "sold a different quantity"
                entry_day, entry_price, entry_fee = lots.pop(event.code)
                pnl = event.quantity * (event.price - entry_price) - entry_fee - event.fee
                rebuilt.append({"code": event.code, "entry_date": entry_day, "exit_date": day,
                                "quantity": event.quantity, "entry_price": entry_price,
                                "exit_price": event.price, "entry_fee": entry_fee,
                                "exit_fee": event.fee, "pnl": pnl,
                                "return": pnl / (event.quantity * entry_price + entry_fee),
                                "exit_reason": event.reason})
                if event.side == "sell":
                    assert row.Trading_Halt == 0, "filled on a halted session"
                    assert not (row.High == row.Low and row.Close <= 0.71 * row.PreviousClose), \
                        "sold into a locked lower limit"
                    opening = pd.Timestamp(event.date).hour == 9
                    assert not (opening and row.Open <= 0.71 * row.PreviousClose), \
                        "sold at an open already at the lower limit"
                    assert row.Low <= event.reference_price <= row.High, "fill outside the day's range"
                    assert event.price == pytest.approx(event.reference_price * (1 - slippage))
                    cash += notional - event.fee
                else:
                    assert event.price == 0.0
            assert cash >= -1e-9, "cash went negative"
        equity = cash + sum(qty * bar.loc[(day, code)].Close for code, qty in held.items())
        assert result.value().loc[day] == pytest.approx(equity, rel=1e-12, abs=1e-9)
    assert sorted(held) == sorted(pos["code"] for pos in result.open_positions)

    # The trade ledger must be exactly what the orders alone imply, return included.
    trades = result.trades
    expected = pd.DataFrame(rebuilt, columns=["code", "entry_date", "exit_date", "quantity",
                                              "entry_price", "exit_price", "entry_fee",
                                              "exit_fee", "pnl", "return", "exit_reason"])
    pd.testing.assert_frame_equal(
        trades[expected.columns].reset_index(drop=True), expected,
        check_dtype=False, check_datetimelike_compat=True, rtol=1e-12)
    if trades.empty:
        return
    assert (trades.holding_sessions >= 1).all()
    # Only a sale deferred by a lower-limit lock may outlive the horizon.
    overdue = trades.holding_sessions > bt["max_holding_days"]
    assert trades.loc[overdue, "exit_reason"].eq("limit_down_locked").all()
    if not result.open_positions:
        assert trades.pnl.sum() == pytest.approx(result.value().iloc[-1] - bt["initial_cash"])
