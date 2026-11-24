"""Daily long-only executor. Rules live in backtest/EXECUTION_SPEC.md."""
from math import floor
from pathlib import Path

import numpy as np
import pandas as pd
import vectorbt as vbt
from shared.io import atomic_json

TRADING_DAYS_PER_YEAR = 252
# Four ordered events per session: opening exits, opening entries, intraday exits, closing exits.
EVENT_HOURS = (9, 10, 12, 16)
TRADE_COLUMNS = [
    "code", "entry_date", "exit_date", "quantity", "entry_price", "exit_price",
    "entry_fee", "exit_fee", "pnl", "return", "holding_sessions", "exit_reason",
]


class ExecutionResult:
    def __init__(self, portfolio, initial_cash, events, trades, exclusions, open_positions):
        self.portfolio = portfolio
        self.initial_cash = initial_cash
        self.events = events
        self.trades = trades
        self.exclusions = exclusions
        self.open_positions = open_positions

    def value(self):
        return self.portfolio.value().groupby(lambda date: date.normalize()).last()

    def returns(self):
        values = self.value()
        returns = values.pct_change(fill_method=None)
        returns.iloc[0] = values.iloc[0] / self.initial_cash - 1
        return returns

    def turnover(self):
        """Annualized one-way turnover: half of traded notional over mean equity."""
        if self.events.empty:
            return 0.0
        fills = self.events.loc[self.events.side.isin(["buy", "sell"])]
        traded = float((fills.quantity * fills.price).sum()) / 2
        equity = self.value()
        return traded / float(equity.mean()) * TRADING_DAYS_PER_YEAR / len(equity)


def simulate(config, entries, price_df):
    bt = config["backtest"]
    lag = bt.get("signal_lag_days", 1)
    horizon = bt["max_holding_days"]
    fee = bt["fee"]
    slippage = bt["slippage_bps"] / 10_000
    top_n = config["strategy"]["top_n"]
    codes = list(entries.columns)
    days = pd.DatetimeIndex(entries.index)
    price_df = price_df.copy()
    price_df["Date"] = pd.to_datetime(price_df.Date).dt.normalize()
    if price_df.duplicated(["Date", "Code"]).any():
        raise ValueError("Duplicate execution price rows")
    fields = {
        column: price_df.pivot(index="Date", columns="Code", values=column).reindex(
            index=days, columns=codes
        )
        for column in ("Open", "High", "Low", "Close", "Trading_Halt", "Sigma")
    }
    eligible = (
        price_df.pivot(index="Date", columns="Code", values="UniverseEligible")
        .reindex(index=days, columns=codes)
        .fillna(False)
        if "UniverseEligible" in price_df
        else fields["Open"].notna()
    )
    # Barriers are anchored where the label is: the signal day's close and Sigma.
    signal_close = fields["Close"].shift(lag)
    signal_sigma = fields["Sigma"].shift(lag)

    delisting_dates = {}
    if config.get("dataset", {}).get("root"):
        metadata = pd.read_csv(Path(config["dataset"]["root"]) / "ticker_metadata.csv",
                               dtype={"Code": str}, parse_dates=["DelistingDate"])
        for code, rows in metadata.dropna(subset=["DelistingDate"]).groupby("Code"):
            delisting_dates[code] = rows.DelistingDate.tolist()

    event_index = pd.DatetimeIndex(
        [day + pd.Timedelta(hours=hour) for day in days for hour in EVENT_HOURS]
    )
    sizes = pd.DataFrame(0.0, index=event_index, columns=codes)
    order_prices = pd.DataFrame(np.nan, index=event_index, columns=codes)
    marks = pd.DataFrame(np.nan, index=event_index, columns=codes)
    cash = float(bt["initial_cash"])
    positions, events, trades, exclusions, written_off = {}, [], [], [], set()
    equity_at_close = []

    def lines(pos):
        hard = bt.get("hard_sl_mult")
        up = bt.get("up_mult")
        down = bt.get("down_mult")
        anchor, sigma = pos["anchor"], pos["sigma"]
        return (
            anchor * (1 - hard * sigma) if hard is not None else -np.inf,
            anchor * (1 + up * sigma) if up is not None else np.inf,
            anchor * (1 - down * sigma) if down is not None else -np.inf,
        )

    def close_trade(code, row, price, exit_fee, reason, side, reference=0.0):
        pos = positions.pop(code)
        quantity = pos["quantity"]
        pnl = quantity * (price - pos["price"]) - pos["fee"] - exit_fee
        trades.append({
            "code": code, "entry_date": pos["entry_date"], "exit_date": row.normalize(),
            "quantity": quantity, "entry_price": pos["price"], "exit_price": price,
            "entry_fee": pos["fee"], "exit_fee": exit_fee, "pnl": pnl,
            "return": pnl / (quantity * pos["price"] + pos["fee"]),
            "holding_sessions": pos["sessions"], "exit_reason": reason,
        })
        events.append({"date": row, "code": code, "side": side, "quantity": quantity,
                       "price": price, "reference_price": reference, "fee": exit_fee,
                       "reason": reason})

    def sell(code, row, reference, reason):
        nonlocal cash
        quantity = positions[code]["quantity"]
        price = reference * (1 - slippage)
        proceeds = quantity * price
        cash += proceeds * (1 - fee)
        sizes.loc[row, code] = -quantity
        order_prices.loc[row, code] = price
        close_trade(code, row, price, proceeds * fee, reason, "sell", reference)

    for day_number, day in enumerate(days):
        rows = [day + pd.Timedelta(hours=hour) for hour in EVENT_HOURS]
        last_day = day_number == len(days) - 1
        available = fields["Open"].loc[day].notna() & fields["Close"].loc[day].notna()
        halted = fields["Trading_Halt"].loc[day] != 0
        for code in list(positions):
            if any(pd.Timestamp(positions[code]["entry_date"]) < date <= day
                   for date in delisting_dates.get(code, [])):
                if available[code]:
                    raise ValueError(f"Price exists after confirmed delisting: {code} {day}")
                close_trade(code, rows[0], 0.0, 0.0, "delisting_zero_recovery", "writeoff")
                written_off.add(code)
                continue
            if not available[code]:
                raise ValueError(
                    f"Held position lost valuation price: {code} {day}; position={positions[code]}"
                )
        for row in rows[:3]:
            marks.loc[row] = fields["Open"].loc[day]
        marks.loc[rows[3]] = fields["Close"].loc[day]
        for code in written_off:
            if available[code]:
                raise ValueError(f"New price path after writeoff requires corporate-event mapping: {code}")
            marks.loc[rows, code] = 0.0

        # 09:00 opening exits.
        for code in list(positions):
            if halted[code]:
                continue
            pos = positions[code]
            open_price = fields["Open"].loc[day, code]
            stop, profit, _ = lines(pos)
            if pos["pending"]:
                sell(code, rows[0], open_price, "close_stop_next_open")
            elif open_price <= stop:
                sell(code, rows[0], open_price, "stop_gap")
            elif open_price >= profit:
                sell(code, rows[0], open_price, "profit_gap")

        # 10:00 opening entries. Budget is snapshotted so ticker order cannot change sizes.
        budget = cash / top_n
        selected = [code for code in codes if entries.loc[day, code] and code not in positions]
        if len(selected) > top_n:
            raise ValueError("Entry count exceeds top_n")
        for code in selected:
            if not available[code] or halted[code] or not eligible.loc[day, code]:
                exclusions.append({"date": str(day.date()), "code": code, "reason": "entry_ineligible"})
                continue
            sigma, anchor = signal_sigma.loc[day, code], signal_close.loc[day, code]
            if np.isinf(sigma):
                raise ValueError("Non-finite signal Sigma")
            if pd.isna(sigma) or sigma <= 0 or pd.isna(anchor):
                reason = "constant_volatility" if sigma == 0 else "signal_sigma_warmup"
                exclusions.append({"date": str(day.date()), "code": code, "reason": reason})
                continue
            if bt.get("hard_sl_mult") is not None and bt["hard_sl_mult"] * sigma >= 1:
                raise ValueError("Hard stop lies at a non-positive price")
            open_price = fields["Open"].loc[day, code]
            candidate = {"anchor": anchor, "sigma": sigma}
            stop, profit, _ = lines(candidate)
            if open_price <= stop or open_price >= profit:
                # An open beyond a barrier exits at that same open: a forced fee-only round trip.
                exclusions.append({"date": str(day.date()), "code": code, "reason": "open_beyond_barrier"})
                continue
            price = open_price * (1 + slippage)
            quantity = floor(max(0.0, budget) / (price * (1 + fee)))
            cost = quantity * price * (1 + fee)
            if quantity < 1 or cost > cash:
                exclusions.append({"date": str(day.date()), "code": code, "reason": "insufficient_cash"})
                continue
            cash -= cost
            positions[code] = {**candidate, "quantity": quantity, "price": price,
                               "fee": quantity * price * fee, "sessions": 0, "pending": False,
                               "entry_date": day}
            sizes.loc[rows[1], code] = quantity
            order_prices.loc[rows[1], code] = price
            events.append({"date": rows[1], "code": code, "side": "buy", "quantity": quantity,
                           "price": price, "reference_price": open_price,
                           "fee": quantity * price * fee, "reason": "top_n"})

        # 12:00 intraday barriers. Ambiguous dual touch is downside first.
        for code in list(positions):
            if halted[code]:
                continue
            pos = positions[code]
            pos["sessions"] += 1
            stop, profit, _ = lines(pos)
            open_price = fields["Open"].loc[day, code]
            if fields["Low"].loc[day, code] <= stop:
                sell(code, rows[2], min(open_price, stop), "intraday_stop")
            elif fields["High"].loc[day, code] >= profit:
                sell(code, rows[2], max(open_price, profit), "intraday_profit")

        # 16:00 closing exits: horizon expiry and period end sell at the close.
        for code in list(positions):
            if halted[code]:
                continue
            pos = positions[code]
            close_price = fields["Close"].loc[day, code]
            if pos["sessions"] >= horizon:
                sell(code, rows[3], close_price, "holding_expiry")
            elif last_day:
                sell(code, rows[3], close_price, "period_end")
            elif close_price <= lines(pos)[2]:
                pos["pending"] = True

        equity_at_close.append(
            cash + sum(pos["quantity"] * fields["Close"].loc[day, code] for code, pos in positions.items())
        )

    portfolio = vbt.Portfolio.from_orders(
        close=marks, size=sizes, price=order_prices, size_type="amount", fees=fee,
        init_cash=bt["initial_cash"], cash_sharing=True, group_by=True, freq="6h",
        allow_partial=False, raise_reject=True,
    )
    open_positions = [
        {"code": code, **pos, "valuation_price": fields["Close"].iloc[-1][code]}
        for code, pos in positions.items()
    ]
    result = ExecutionResult(
        portfolio, bt["initial_cash"], pd.DataFrame(events),
        pd.DataFrame(trades, columns=TRADE_COLUMNS), exclusions, open_positions,
    )
    # VectorBT replays the same orders as an independent ledger; every close must agree.
    if not np.allclose(result.value().to_numpy(), equity_at_close, rtol=1e-9, atol=1e-6):
        raise ValueError("VectorBT daily equity disagrees with the execution ledger")
    if not np.isclose(portfolio.cash().iloc[-1], cash, rtol=1e-9, atol=1e-6):
        raise ValueError("VectorBT cash disagrees with the execution ledger")
    return result


def save_execution(result, out_dir):
    out = Path(out_dir)
    result.events.to_csv(out / "orders.csv", index=False)
    result.trades.to_csv(out / "trades.csv", index=False)
    result.value().rename("Equity").to_csv(out / "equity_curve.csv")
    atomic_json(
        out / "execution_report.json",
        {
            "exclusions": result.exclusions,
            "open_positions": result.open_positions,
            "closed_trades": len(result.trades),
            "unclosed_positions": len(result.open_positions),
            "execution_policy": {"quantity": "integer_floor_on_existing_adjusted_price_basis",
                                 "delisting": "zero_valuation_zero_cash_recovery",
                                 "barrier_anchor": "signal_close_and_sigma",
                                 "expiry": "close_of_max_holding_session",
                                 "period_end": "liquidate_at_final_close"},
        },
    )
