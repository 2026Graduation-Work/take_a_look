"""Cash-aware daily execution, then VectorBT accounting of the actual orders."""

from math import floor
from pathlib import Path

import numpy as np
import pandas as pd
import vectorbt as vbt
from core.local_config import atomic_json


class DailyPortfolio:
    """Expose daily marked values while retaining VectorBT orders and trades."""

    def __init__(self, portfolio, initial_cash, exclusions):
        self.portfolio = portfolio
        self.initial_cash = initial_cash
        self.exclusions = exclusions
        self.trades = portfolio.trades

    def value(self):
        return self.portfolio.value().groupby(lambda date: date.normalize()).last()

    def returns(self):
        values = self.value()
        returns = values.pct_change(fill_method=None)
        returns.iloc[0] = values.iloc[0] / self.initial_cash - 1
        return returns

    def stats(self):
        return self.portfolio.stats()

    def plot(self):
        return self.value().vbt.plot()

    def trade_records(self):
        records = self.trades.records_readable.copy()
        for loss in self.writeoffs:
            mask = records.Column.eq(loss["code"]) & records.Status.eq("Open")
            if mask.sum() != 1:
                raise ValueError("Delisting loss disagrees with VectorBT position")
            records.loc[mask, "Status"] = "Closed"
            records.loc[mask, "Exit Timestamp"] = loss["date"]
            records.loc[mask, "Avg Exit Price"] = 0.0
            records.loc[mask, "Exit Fees"] = 0.0
            records.loc[mask, "Exit Reason"] = "delisting_zero_recovery"
        return records


def simulate(config, entries, weights, price_df):
    bt = config["backtest"]
    codes = list(entries.columns)
    days = pd.DatetimeIndex(entries.index)
    price_df = price_df.copy()
    price_df["Date"] = pd.to_datetime(price_df.Date).dt.normalize()
    if price_df.duplicated(["Date", "Code"]).any():
        raise ValueError("Duplicate execution price rows")
    fields = {}
    for column in ("Open", "High", "Low", "Close", "Trading_Halt", "Sigma"):
        fields[column] = price_df.pivot(index="Date", columns="Code", values=column).reindex(
            index=days, columns=codes
        )
    eligible = (
        price_df.pivot(index="Date", columns="Code", values="UniverseEligible")
        .reindex(index=days, columns=codes)
        .fillna(False)
        if "UniverseEligible" in price_df
        else fields["Open"].notna()
    )
    signal_sigma = entries.attrs.get("signal_sigma")
    if signal_sigma is None:
        raise ValueError("Signal-time Sigma required; regenerate strategy signals")
    cash = float(bt["initial_cash"])
    fee = bt["fee"]
    positions = {}
    exclusions, events, writeoffs = [], [], []
    delisting_dates = {}
    if config.get("dataset", {}).get("root"):
        metadata = pd.read_csv(Path(config["dataset"]["root"]) / "ticker_metadata.csv",
                               dtype={"Code": str}, parse_dates=["DelistingDate"])
        for code, rows in metadata.dropna(subset=["DelistingDate"]).groupby("Code"):
            delisting_dates[code] = rows.DelistingDate.tolist()
    # Four ordered events: opening exits, opening entries, intraday exits, closing marks.
    event_index = pd.DatetimeIndex(
        [day + pd.Timedelta(hours=hour) for day in days for hour in (9, 10, 12, 16)]
    )
    sizes = pd.DataFrame(0.0, index=event_index, columns=codes)
    order_prices = pd.DataFrame(np.nan, index=event_index, columns=codes)
    marks = pd.DataFrame(np.nan, index=event_index, columns=codes)
    top_n = config["strategy"]["top_n"]

    def sell(code, row, price, reason):
        nonlocal cash
        position = positions.pop(code)
        proceeds = position["quantity"] * price
        cash += proceeds * (1 - fee)
        sizes.loc[row, code] = -position["quantity"]
        order_prices.loc[row, code] = price
        events.append(
            {
                "date": row,
                "code": code,
                "side": "sell",
                "quantity": position["quantity"],
                "price": price,
                "fee": proceeds * fee,
                "reason": reason,
            }
        )

    for day in days:
        event_rows = [day + pd.Timedelta(hours=hour) for hour in (9, 10, 12, 16)]
        available = fields["Open"].loc[day].notna() & fields["Close"].loc[day].notna()
        for code in list(positions):
            pos = positions[code]
            if any(pd.Timestamp(pos["entry_date"]) < date <= day
                   for date in delisting_dates.get(code, [])):
                if available[code]:
                    raise ValueError(f"Price exists after confirmed delisting: {code} {day}")
                loss = {"date": event_rows[0], "code": code, "side": "writeoff",
                        "quantity": pos["quantity"], "price": 0.0, "fee": 0.0,
                        "reason": "delisting_zero_recovery",
                        "loss_including_entry_fee": pos["quantity"] * pos["price"] * (1 + fee)}
                writeoffs.append(loss)
                events.append(loss)
                del positions[code]
                continue
            if not available[code]:
                raise ValueError(
                    f"Held position lost valuation price: {code} {day}; position={positions[code]}"
                )
        for row in event_rows[:3]:
            marks.loc[row] = fields["Open"].loc[day]
        marks.loc[event_rows[-1]] = fields["Close"].loc[day]
        # A writeoff changes valuation only. No fictitious sale or cash proceeds.
        for loss in writeoffs:
            code = loss["code"]
            if available[code]:
                raise ValueError(f"New price path after writeoff requires corporate-event mapping: {code}")
            marks.loc[event_rows, code] = 0.0
        # Open exits (expiry, previously confirmed close stop and gaps).
        for code in list(positions):
            if fields["Trading_Halt"].loc[day, code] != 0:
                continue
            pos = positions[code]
            open_price = fields["Open"].loc[day, code]
            pos["age"] += 1
            sigma = pos["sigma"]
            hard_stop = (
                pos["price"] * (1 - bt["hard_sl_mult"] * sigma)
                if bt.get("hard_sl_mult") is not None
                else -np.inf
            )
            profit = (
                pos["price"] * (1 + bt["up_mult"] * sigma)
                if bt.get("up_mult") is not None
                else np.inf
            )
            reason = None
            if pos["pending"]:
                reason = "close_stop_next_open"
            elif pos["age"] >= bt["max_holding_days"]:
                reason = "holding_expiry"
            elif open_price <= hard_stop:
                reason = "stop_gap"
            elif open_price >= profit:
                reason = "profit_gap"
            if reason:
                sell(code, event_rows[0], open_price, reason)
        # Snapshot budget once: order of tickers cannot change equal allocation.
        budget = cash / top_n
        selected = [code for code in codes if entries.loc[day, code] and code not in positions]
        if len(selected) > top_n:
            raise ValueError("Entry count exceeds top_n")
        for code in selected:
            if (
                not available[code]
                or fields["Trading_Halt"].loc[day, code] != 0
                or not eligible.loc[day, code]
            ):
                exclusions.append(
                    {"date": str(day.date()), "code": code, "reason": "entry_ineligible"}
                )
                continue
            sigma = signal_sigma.loc[day, code]
            if np.isinf(sigma):
                raise ValueError("Non-finite signal Sigma")
            if pd.isna(sigma) or sigma <= 0:
                exclusions.append(
                    {"date": str(day.date()), "code": code, "reason": "signal_sigma_warmup" if pd.isna(sigma) else "constant_volatility"}
                )
                continue
            if bt.get("hard_sl_mult") is not None and bt["hard_sl_mult"] * sigma >= 1:
                raise ValueError("Hard stop lies at a non-positive price")
            price = fields["Open"].loc[day, code]
            quantity = floor(max(0.0, budget) / (price * (1 + fee)))
            cost = quantity * price + quantity * price * fee
            if quantity < 1 or cost > cash:
                exclusions.append(
                    {"date": str(day.date()), "code": code, "reason": "insufficient_cash"}
                )
                continue
            cash -= cost
            positions[code] = {
                "quantity": quantity,
                "price": price,
                "sigma": sigma,
                "age": 0,
                "pending": False,
                "entry_date": str(day.date()),
            }
            sizes.loc[event_rows[1], code] = quantity
            order_prices.loc[event_rows[1], code] = price
            events.append(
                {
                    "date": event_rows[1],
                    "code": code,
                    "side": "buy",
                    "quantity": quantity,
                    "price": price,
                    "fee": quantity * price * fee,
                    "reason": "top_n",
                }
            )
        # New entries participate in intraday stops. Ambiguous dual touch is downside first.
        for code in list(positions):
            if fields["Trading_Halt"].loc[day, code] != 0:
                continue
            pos = positions[code]
            stop = (
                pos["price"] * (1 - bt["hard_sl_mult"] * pos["sigma"])
                if bt.get("hard_sl_mult") is not None
                else -np.inf
            )
            profit = (
                pos["price"] * (1 + bt["up_mult"] * pos["sigma"])
                if bt.get("up_mult") is not None
                else np.inf
            )
            if fields["Low"].loc[day, code] <= stop:
                sell(code, event_rows[2], min(fields["Open"].loc[day, code], stop), "intraday_stop")
            elif fields["High"].loc[day, code] >= profit:
                sell(
                    code,
                    event_rows[2],
                    max(fields["Open"].loc[day, code], profit),
                    "intraday_profit",
                )
            elif bt.get("down_mult") is not None and fields["Close"].loc[day, code] <= pos[
                "price"
            ] * (1 - bt["down_mult"] * pos["sigma"]):
                pos["pending"] = True
    portfolio = vbt.Portfolio.from_orders(
        close=marks,
        size=sizes,
        price=order_prices,
        size_type="amount",
        fees=fee,
        init_cash=bt["initial_cash"],
        cash_sharing=True,
        group_by=True,
        freq="6h",
        allow_partial=False,
        raise_reject=True,
    )
    daily = DailyPortfolio(portfolio, bt["initial_cash"], exclusions)
    daily.writeoffs = writeoffs
    daily.events = pd.DataFrame(events)
    daily.open_positions = [
        {
            "code": code,
            **pos,
            "valuation_price": fields["Close"].iloc[-1][code],
            "unrealized_pnl_before_exit_fee": pos["quantity"]
            * (fields["Close"].iloc[-1][code] - pos["price"])
            - pos["quantity"] * pos["price"] * fee,
        }
        for code, pos in positions.items()
    ]
    expected_value = cash + sum(
        pos["quantity"] * fields["Close"].iloc[-1][code] for code, pos in positions.items()
    )
    if (not np.isclose(daily.value().iloc[-1], expected_value, rtol=1e-9)
            or not np.isclose(portfolio.cash().iloc[-1], cash, rtol=1e-9, atol=1e-7)):
        raise ValueError("VectorBT accounting disagrees with actual execution cash/positions")
    return daily


def save_execution(portfolio, out_dir):
    out = Path(out_dir)
    portfolio.events.to_csv(out / "orders.csv", index=False)
    records = portfolio.trade_records()
    records.to_csv(out / "trades.csv", index=False)
    portfolio.value().rename("Equity").to_csv(out / "equity_curve.csv")
    portfolio.returns().rename("Portfolio").to_csv(out / "daily_returns.csv")
    atomic_json(
        out / "execution_report.json",
        {
            "exclusions": portfolio.exclusions,
            "open_positions": portfolio.open_positions,
            "closed_trades": int(records.Status.eq("Closed").sum()),
            "unclosed_positions": len(portfolio.open_positions),
            "writeoffs": portfolio.writeoffs,
            "execution_policy": {"quantity": "integer_floor_on_existing_adjusted_price_basis",
                                 "delisting": "zero_valuation_zero_cash_recovery"},
            "end_valuation": "final close",
        },
    )
