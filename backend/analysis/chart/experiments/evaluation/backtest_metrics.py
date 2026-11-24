"""Return and trade metrics. Definitions and hand-computed cases: tests/test_backtest_metrics.py."""
import numpy as np
import pandas as pd

TRADING_DAYS_PER_YEAR = 252
TRADE_METRICS = (
    "win_rate", "average_win", "average_loss", "payoff_ratio", "profit_factor",
    "average_holding_sessions",
)


def calculate_trading_metrics(daily_returns: pd.Series, trades: pd.DataFrame | None = None) -> dict:
    """daily_returns: simple daily returns. trades: executor trade ledger (return, pnl, holding_sessions)."""
    returns = daily_returns.dropna()
    if returns.empty:
        return {}
    total_return = float((1.0 + returns).prod() - 1.0)
    n_days = len(returns)
    # Annualizing less than a year of returns extrapolates; report the total return instead.
    cagr = (
        (1.0 + total_return) ** (TRADING_DAYS_PER_YEAR / n_days) - 1.0
        if n_days >= TRADING_DAYS_PER_YEAR
        else np.nan
    )
    annual_mean = returns.mean() * TRADING_DAYS_PER_YEAR
    volatility = returns.std() * np.sqrt(TRADING_DAYS_PER_YEAR)
    # Downside deviation against a zero target over every day, not the std of losing days.
    downside = np.sqrt((np.minimum(returns, 0.0) ** 2).mean()) * np.sqrt(TRADING_DAYS_PER_YEAR)
    # Include the initial equity (1.0) so a first-day loss counts as drawdown.
    equity = pd.concat([pd.Series([1.0]), (1.0 + returns).cumprod()], ignore_index=True)
    metrics = {
        "total_return": total_return,
        "trading_days": n_days,
        "cagr": float(cagr),
        "annualized_volatility": float(volatility),
        "sharpe_ratio": float(annual_mean / volatility) if volatility > 0 else np.nan,
        "sortino_ratio": float(annual_mean / downside) if downside > 0 else np.nan,
        "max_drawdown": float((equity / equity.cummax() - 1.0).min()),
        "number_of_trades": 0 if trades is None else len(trades),
    }
    metrics.update(dict.fromkeys(TRADE_METRICS, np.nan))
    if trades is None or trades.empty:
        return metrics
    wins = trades["return"] > 0
    average_win = trades.loc[wins, "return"].mean() if wins.any() else 0.0
    average_loss = trades.loc[~wins, "return"].mean() if (~wins).any() else 0.0
    gross_loss = -trades.loc[trades.pnl < 0, "pnl"].sum()
    metrics.update({
        "win_rate": float(wins.mean()),
        "average_win": float(average_win),
        "average_loss": float(average_loss),
        "payoff_ratio": float(average_win / abs(average_loss)) if average_loss else np.nan,
        "profit_factor": float(trades.loc[trades.pnl > 0, "pnl"].sum() / gross_loss)
        if gross_loss > 0 else np.nan,
        "average_holding_sessions": float(trades.holding_sessions.mean()),
    })
    return metrics
