import numpy as np
import pandas as pd


def calculate_trading_metrics(daily_returns: pd.Series, trades_df: pd.DataFrame = None) -> dict:
    metrics = {}

    if daily_returns.empty:
        return metrics

    total_ret = (1.0 + daily_returns).prod() - 1.0
    metrics["total_return"] = float(total_ret)

    ann_factor = 252

    n_days = len(daily_returns)
    if n_days > 0:
        cagr = (total_ret + 1.0) ** (ann_factor / n_days) - 1.0
        metrics["cagr"] = float(cagr)
    else:
        metrics["cagr"] = np.nan

    ann_vol = daily_returns.std() * np.sqrt(ann_factor)
    metrics["annualized_volatility"] = float(ann_vol)

    if ann_vol > 0:
        metrics["sharpe_ratio"] = float((daily_returns.mean() * ann_factor) / ann_vol)
    else:
        metrics["sharpe_ratio"] = np.nan

    downside_returns = daily_returns[daily_returns < 0]
    if not downside_returns.empty:
        downside_vol = downside_returns.std() * np.sqrt(ann_factor)
        if downside_vol > 0:
            metrics["sortino_ratio"] = float(
                (daily_returns.mean() * ann_factor) / downside_vol
            )
        else:
            metrics["sortino_ratio"] = np.nan
    else:
        metrics["sortino_ratio"] = np.nan

    # Include the initial equity (1.0). Without it, a loss on day one becomes
    # the first running maximum and is incorrectly reported as zero drawdown.
    cum_returns = (1.0 + daily_returns).cumprod()
    equity = pd.concat(
        [pd.Series([1.0], dtype=float), cum_returns], ignore_index=True
    )
    running_max = equity.cummax()
    drawdowns = (equity - running_max) / running_max
    mdd = drawdowns.min()
    metrics["max_drawdown"] = float(mdd)

    if trades_df is not None and not trades_df.empty:
        # vectorbt records_readable의 컬럼명은 'PnL', 'Return', 'Duration'이다.
        pnl_col = "PnL" if "PnL" in trades_df.columns else "pnl"
        ret_col = "Return" if "Return" in trades_df.columns else "return"
        dur_col = "Duration" if "Duration" in trades_df.columns else "duration"

        returns_series = trades_df[ret_col] if ret_col in trades_df.columns else pd.Series()
        pnl_series = trades_df[pnl_col] if pnl_col in trades_df.columns else pd.Series()
        duration_series = trades_df[dur_col] if dur_col in trades_df.columns else pd.Series()

        n_trades = len(trades_df)
        metrics["number_of_trades"] = int(n_trades)

        if n_trades > 0:
            wins = returns_series > 0
            win_rate = wins.mean()
            metrics["win_rate"] = float(win_rate)

            avg_win = returns_series[wins].mean() if wins.any() else 0.0
            avg_loss = returns_series[~wins].mean() if (~wins).any() else 0.0
            metrics["average_win"] = float(avg_win)
            metrics["average_loss"] = float(avg_loss)

            if abs(avg_loss) > 0:
                metrics["payoff_ratio"] = float(avg_win / abs(avg_loss))
            else:
                metrics["payoff_ratio"] = np.nan

            total_win_val = pnl_series[pnl_series > 0].sum()
            total_loss_val = pnl_series[pnl_series < 0].sum()
            if abs(total_loss_val) > 0:
                metrics["profit_factor"] = float(total_win_val / abs(total_loss_val))
            else:
                metrics["profit_factor"] = np.nan

            if not duration_series.empty:
                # vectorbt duration은 보통 timedelta 형식이나 float 일수일 수 있음
                if pd.api.types.is_timedelta64_dtype(duration_series):
                    avg_holding = duration_series.dt.total_seconds().mean() / (24 * 3600)
                else:
                    avg_holding = duration_series.mean()
                metrics["average_holding_days"] = float(avg_holding)
            else:
                metrics["average_holding_days"] = np.nan
        else:
            metrics["win_rate"] = np.nan
            metrics["average_win"] = np.nan
            metrics["average_loss"] = np.nan
            metrics["payoff_ratio"] = np.nan
            metrics["profit_factor"] = np.nan
            metrics["average_holding_days"] = np.nan
    else:
        metrics["number_of_trades"] = 0
        metrics["win_rate"] = np.nan
        metrics["average_win"] = np.nan
        metrics["average_loss"] = np.nan
        metrics["payoff_ratio"] = np.nan
        metrics["profit_factor"] = np.nan
        metrics["average_holding_days"] = np.nan

    metrics["turnover"] = 0.0

    return metrics
