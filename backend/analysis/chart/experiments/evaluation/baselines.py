import numpy as np
import pandas as pd


def _universe_mask(price_df: pd.DataFrame, template: pd.DataFrame) -> pd.DataFrame:
    if "UniverseEligible" not in price_df:
        return pd.DataFrame(True, index=template.index, columns=template.columns)
    return price_df.pivot(index="Date", columns="Code", values="UniverseEligible").reindex(
        index=template.index, columns=template.columns
    ).fillna(False).astype(bool)


def restrict_signals_to_test_folds(
    entries: pd.DataFrame,
    weights: pd.DataFrame,
    splits: list[dict],
) -> tuple[pd.DataFrame, pd.DataFrame]:
    index = pd.DatetimeIndex(entries.index).tz_localize(None)
    eligible = pd.Series(False, index=index)
    for split in splits:
        eligible |= (index >= pd.to_datetime(split["test_start"])) & (
            index <= pd.to_datetime(split["test_end"])
        )

    restricted_entries = entries.copy()
    restricted_entries.index = index
    restricted_entries.loc[~eligible.to_numpy(), :] = False

    restricted_weights = weights.copy()
    restricted_weights.index = index
    restricted_weights = restricted_weights.where(restricted_entries, np.nan)
    return restricted_entries, restricted_weights


def generate_random_top_k_signals(
    price_df: pd.DataFrame, top_n: int, seed: int = 42
) -> tuple[pd.DataFrame, pd.DataFrame]:
    raw_open_price = price_df.pivot(index="Date", columns="Code", values="Open")
    open_price = raw_open_price.ffill()
    trading_halt = price_df.pivot(index="Date", columns="Code", values="Trading_Halt").fillna(0)

    eligible = _universe_mask(price_df, raw_open_price)
    valid_mask = raw_open_price.notna() & (open_price > 1.0) & (trading_halt == 0) & eligible

    np.random.seed(seed)
    random_scores = pd.DataFrame(
        np.random.rand(*open_price.shape),
        index=open_price.index,
        columns=open_price.columns,
    )

    random_scores = random_scores.where(valid_mask)
    rankings = random_scores.rank(axis=1, method="first", ascending=False)
    raw_entries = rankings <= top_n

    equal_weight = 1.0 / top_n
    weights = pd.DataFrame(
        np.where(raw_entries, equal_weight, 0.0),
        index=open_price.index,
        columns=open_price.columns,
    )

    # T일 시그널 -> T+1일 진입
    entries = raw_entries.shift(1).fillna(False)
    weights = weights.shift(1).fillna(0.0)

    entries = entries & raw_open_price.notna() & (trading_halt == 0) & eligible
    weights = weights.where(entries, np.nan)

    return entries, weights


def generate_momentum_signals(
    price_df: pd.DataFrame, top_n: int, horizon: int = 5
) -> tuple[pd.DataFrame, pd.DataFrame]:
    raw_open_price = price_df.pivot(index="Date", columns="Code", values="Open")
    raw_close_price = price_df.pivot(index="Date", columns="Code", values="Close")
    open_price = raw_open_price.ffill()
    close_price = raw_close_price.ffill()
    trading_halt = price_df.pivot(index="Date", columns="Code", values="Trading_Halt").fillna(0)

    momentum_score = close_price.pct_change(periods=horizon)

    eligible = _universe_mask(price_df, raw_open_price)
    valid_mask = raw_open_price.notna() & (open_price > 1.0) & (trading_halt == 0) & eligible
    momentum_score = momentum_score.where(valid_mask)

    rankings = momentum_score.rank(axis=1, method="first", ascending=False)
    raw_entries = rankings <= top_n

    equal_weight = 1.0 / top_n
    weights = pd.DataFrame(
        np.where(raw_entries, equal_weight, 0.0),
        index=open_price.index,
        columns=open_price.columns,
    )

    # T일 시그널 -> T+1일 진입
    entries = raw_entries.shift(1).fillna(False)
    weights = weights.shift(1).fillna(0.0)

    entries = entries & raw_open_price.notna() & (trading_halt == 0) & eligible
    weights = weights.where(entries, np.nan)

    return entries, weights


def generate_ma_breakout_signals(
    price_df: pd.DataFrame, top_n: int, window: int = 20
) -> tuple[pd.DataFrame, pd.DataFrame]:
    raw_open_price = price_df.pivot(index="Date", columns="Code", values="Open")
    raw_close_price = price_df.pivot(index="Date", columns="Code", values="Close")
    open_price = raw_open_price.ffill()
    close_price = raw_close_price.ffill()
    trading_halt = price_df.pivot(index="Date", columns="Code", values="Trading_Halt").fillna(0)

    ma = close_price.rolling(window=window).mean()
    breakout_mask = close_price > ma
    spread = close_price / ma - 1.0

    eligible = _universe_mask(price_df, raw_open_price)
    valid_mask = raw_open_price.notna() & (open_price > 1.0) & (trading_halt == 0) & breakout_mask & eligible
    spread = spread.where(valid_mask)

    rankings = spread.rank(axis=1, method="first", ascending=False)
    raw_entries = rankings <= top_n

    equal_weight = 1.0 / top_n
    weights = pd.DataFrame(
        np.where(raw_entries, equal_weight, 0.0),
        index=open_price.index,
        columns=open_price.columns,
    )

    # T일 시그널 -> T+1일 진입
    entries = raw_entries.shift(1).fillna(False)
    weights = weights.shift(1).fillna(0.0)

    entries = entries & raw_open_price.notna() & (trading_halt == 0) & eligible
    weights = weights.where(entries, np.nan)

    return entries, weights
