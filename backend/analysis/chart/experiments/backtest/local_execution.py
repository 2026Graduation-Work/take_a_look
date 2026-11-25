"""Daily long-only executor. Rules live in backtest/EXECUTION_SPEC.md."""
from math import floor
from pathlib import Path

import numpy as np
import pandas as pd
import vectorbt as vbt
from experiments.train_src.labels import reached_down, reached_up
from shared.io import atomic_json

TRADING_DAYS_PER_YEAR = 252
# KRX daily price limit is ±30% of the base price since 2015-06-15. Rounding the limit to a
# tick moves it by at most ~0.5%, so these ratios to the previous adjusted close detect it.
PRICE_LIMIT_START = pd.Timestamp("2015-06-15")
LIMIT_UP_RATIO = 1.29
LIMIT_DOWN_RATIO = 0.71
LIQUIDITY_WINDOW = 20
# Four ordered events per session: opening exits, opening entries, intraday exits, closing exits.
EVENT_HOURS = (9, 10, 12, 16)
TRADE_COLUMNS = [
    "code", "entry_date", "exit_date", "quantity", "entry_price", "exit_price",
    "entry_fee", "exit_fee", "pnl", "return", "holding_sessions", "exit_reason",
]


class ExecutionResult:
    def __init__(self, portfolio, initial_cash, events, trades, exclusions, open_positions,
                 unfilled_buys=0):
        self.portfolio = portfolio
        self.unfilled_buys = unfilled_buys
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


def simulate(config, entries, price_df, priority=None, daily_buys=None):
    """entries: candidate stocks per day. With priority and daily_buys, candidates are tried in
    priority order until that day's buy count is reached (the random baseline uses this)."""
    bt = config["backtest"]
    lag = bt.get("signal_lag_days", 1)
    horizon = bt["max_holding_days"]
    fee = bt["fee"]
    slippage = bt["slippage_bps"] / 10_000
    participation = bt["max_participation"]
    top_n = config["strategy"]["top_n"]
    codes = list(entries.columns)
    days = pd.DatetimeIndex(entries.index)
    if days.min() < PRICE_LIMIT_START:
        raise ValueError("Price-limit rules assume the ±30% regime from 2015-06-15")
    if participation is not None and "Amount" not in price_df:
        raise ValueError("backtest.max_participation requires the Amount (traded value) column")
    price_df = price_df.copy()
    price_df["Date"] = pd.to_datetime(price_df.Date).dt.normalize()
    if price_df.duplicated(["Date", "Code"]).any():
        raise ValueError("Duplicate execution price rows")
    fields = {
        column: price_df.pivot(index="Date", columns="Code", values=column).reindex(
            index=days, columns=codes
        )
        for column in ("Open", "High", "Low", "Close", "Trading_Halt", "Sigma", "Amount")
        if column in price_df
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
    previous_close = fields["Close"].shift(1)
    # Near the lower limit, sell orders may find no buyer. At the open only the open is known;
    # later in the day a session that traded at one lower-limit price is treated as locked.
    open_at_lower = fields["Open"] / previous_close <= LIMIT_DOWN_RATIO
    locked_down = (fields["High"] == fields["Low"]) & (
        fields["Close"] / previous_close <= LIMIT_DOWN_RATIO)
    limit_up_open = fields["Open"] / previous_close >= LIMIT_UP_RATIO
    average_value = (
        fields["Amount"].shift(1).rolling(LIQUIDITY_WINDOW, min_periods=1).mean()
        if participation is not None else None
    )

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
    unfilled_buys = 0
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
        blocked = open_at_lower if row.hour == EVENT_HOURS[0] else locked_down
        if blocked.loc[row.normalize(), code]:
            positions[code]["pending"] = "limit_down_locked"
            return
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
                sell(code, rows[0], open_price, pos["pending"])
            elif reached_down(open_price, stop):
                sell(code, rows[0], open_price, "stop_gap")
            elif reached_up(open_price, profit):
                sell(code, rows[0], open_price, "profit_gap")

        # 10:00 opening entries. Each signal gets one of top_n × horizon equal slots of equity,
        # so every day's picks are held side by side; cash / top_n keeps the day within cash.
        # Both are snapshotted so ticker order cannot change sizes.
        equity_at_open = cash + sum(
            pos["quantity"] * fields["Open"].loc[day, code] for code, pos in positions.items())
        budget = min(equity_at_open / (top_n * horizon), cash / top_n)
        selected = [code for code in codes if entries.loc[day, code] and code not in positions]
        target = top_n
        if priority is not None:
            selected.sort(key=lambda code: -priority.loc[day, code])
            target = int(daily_buys.get(day, 0))
            if target > top_n:
                raise ValueError("Daily buy target exceeds top_n")
        elif len(selected) > top_n:
            raise ValueError("Entry count exceeds top_n")
        bought = 0
        for code in selected:
            if bought == target:
                break
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
            if limit_up_open.loc[day, code]:
                # Buy orders queue at an upper-limit open; assume ours is not filled.
                exclusions.append({"date": str(day.date()), "code": code, "reason": "limit_up_open"})
                continue
            if reached_down(open_price, stop) or reached_up(open_price, profit):
                # An open beyond a barrier exits at that same open: a forced fee-only round trip.
                exclusions.append({"date": str(day.date()), "code": code, "reason": "open_beyond_barrier"})
                continue
            price = open_price * (1 + slippage)
            quantity = floor(max(0.0, budget) / (price * (1 + fee)))
            capped = False
            if participation is not None and pd.isna(average_value.loc[day, code]):
                exclusions.append({"date": str(day.date()), "code": code, "reason": "liquidity_unknown"})
                continue
            if participation is not None:
                cap = floor(participation * average_value.loc[day, code] / price)
                capped = cap < quantity
                quantity = min(quantity, cap)
            cost = quantity * price * (1 + fee)
            if quantity < 1 or cost > cash:
                reason = "liquidity_capped" if capped else "insufficient_cash"
                exclusions.append({"date": str(day.date()), "code": code, "reason": reason})
                continue
            if capped:
                exclusions.append({"date": str(day.date()), "code": code, "reason": "liquidity_capped"})
            cash -= cost
            bought += 1
            positions[code] = {**candidate, "quantity": quantity, "price": price,
                               "fee": quantity * price * fee, "sessions": 0, "pending": None,
                               "entry_date": day}
            sizes.loc[rows[1], code] = quantity
            order_prices.loc[rows[1], code] = price
            events.append({"date": rows[1], "code": code, "side": "buy", "quantity": quantity,
                           "price": price, "reference_price": open_price,
                           "fee": quantity * price * fee, "reason": "top_n"})

        if priority is not None:
            unfilled_buys += target - bought

        # 12:00 intraday barriers. Ambiguous dual touch is downside first.
        for code in list(positions):
            if halted[code]:
                continue
            pos = positions[code]
            pos["sessions"] += 1
            if pos["pending"]:
                continue  # A deferred sale waits for the next open; it is not re-judged today.
            stop, profit, _ = lines(pos)
            open_price = fields["Open"].loc[day, code]
            low, high = fields["Low"].loc[day, code], fields["High"].loc[day, code]
            # Fills stay inside the day's range when the line equals the low or high.
            if reached_down(low, stop):
                sell(code, rows[2], max(low, min(open_price, stop)), "intraday_stop")
            elif reached_up(high, profit):
                sell(code, rows[2], min(high, max(open_price, profit)), "intraday_profit")

        # 16:00 closing exits: horizon expiry and period end sell at the close.
        for code in list(positions):
            if halted[code]:
                continue
            pos = positions[code]
            if pos["pending"]:
                continue
            close_price = fields["Close"].loc[day, code]
            if pos["sessions"] >= horizon:
                sell(code, rows[3], close_price, "holding_expiry")
            elif last_day:
                sell(code, rows[3], close_price, "period_end")
            elif reached_down(close_price, lines(pos)[2]):
                pos["pending"] = "close_stop_next_open"

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
        pd.DataFrame(trades, columns=TRADE_COLUMNS), exclusions, open_positions, unfilled_buys,
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
