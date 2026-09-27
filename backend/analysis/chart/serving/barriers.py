"""Independent observed barrier events; class label retains the training tie rule."""

import math

import numpy as np
import pandas as pd

MULTIPLIERS = {5: (1.75, 1.50), 20: (3.75, 3.00)}


def observe(frame: pd.DataFrame, position: int, horizon: int, sigma: float) -> dict:
    """Observe exactly the next H traded sessions, within the legacy search cap."""
    if horizon not in MULTIPLIERS:
        raise ValueError("Only H5 and H20 are supported")
    if not math.isfinite(sigma) or sigma < 0:
        raise ValueError("Sigma must be finite and nonnegative")
    frame = frame.reset_index(drop=True)
    if position < 0 or position >= len(frame):
        raise IndexError(position)
    start = frame.iloc[position]
    close = float(start.Close)
    if not math.isfinite(close) or close <= 0:
        raise ValueError("Invalid adjusted close")
    up_mult, down_mult = MULTIPLIERS[horizon]
    upper, lower = close * (1 + up_mult * sigma), close * (1 - down_mult * sigma)
    if bool(start.get("Trading_Halt", 0)):
        return {"complete": False, "reason": "base_halted", "up_barrier": upper,
                "down_barrier": lower, "up_hit": False, "down_hit": False,
                "up_first_date": None, "down_first_date": None,
                "observed_through": None, "outcome_class": None}
    up_day = down_day = None
    up_date = down_date = observed_through = None
    sessions = 0
    for offset in range(1, min(int(horizon * 2.5), len(frame) - position - 1) + 1):
        row = frame.iloc[position + offset]
        if bool(row.get("Trading_Halt", 0)):
            continue
        high, future_close = float(row.High), float(row.Close)
        if not all(math.isfinite(v) and v > 0 for v in (high, future_close)):
            return {"complete": False, "reason": "missing_price", "up_barrier": upper,
                    "down_barrier": lower}
        sessions += 1
        observed_through = pd.Timestamp(row.Date).date().isoformat()
        if high >= upper and up_day is None:
            up_day, up_date = sessions, observed_through
        if future_close <= lower and down_day is None:
            down_day, down_date = sessions, observed_through
        if sessions == horizon:
            break
    complete = sessions == horizon
    label = None if not complete else (
        2 if up_day is not None and (down_day is None or up_day < down_day)
        else 0 if down_day is not None else 1
    )
    return {
        "complete": complete,
        "reason": None if complete else "observation_incomplete",
        "up_barrier": upper, "down_barrier": lower,
        "up_hit": up_day is not None, "down_hit": down_day is not None,
        "up_first_date": up_date, "down_first_date": down_date,
        "observed_through": observed_through, "outcome_class": label,
    }


def observe_many(frame: pd.DataFrame, horizon: int) -> pd.DataFrame:
    """Vectorized equivalent for every base date in one stock's processed history."""
    if horizon not in MULTIPLIERS:
        raise ValueError("Only H5 and H20 are supported")
    frame = frame.sort_values("Date").reset_index(drop=True)
    if frame.Date.duplicated().any():
        raise ValueError("Duplicate price dates")
    n = len(frame)
    close = frame.Close.to_numpy(dtype=float)
    high = frame.High.to_numpy(dtype=float)
    sigma = frame.Sigma.to_numpy(dtype=float)
    halted = frame.Trading_Halt.to_numpy(dtype=bool)
    up_mult, down_mult = MULTIPLIERS[horizon]
    upper = close * (1 + up_mult * sigma)
    lower = close * (1 - down_mult * sigma)
    valid_base = ~halted & np.isfinite(close) & (close > 0) & np.isfinite(sigma) & (sigma >= 0)
    sessions = np.zeros(n, dtype=np.int16)
    up_day = np.zeros(n, dtype=np.int16)
    down_day = np.zeros(n, dtype=np.int16)
    bad_price = np.zeros(n, dtype=bool)
    up_date = np.empty(n, dtype=object)
    down_date = np.empty(n, dtype=object)
    through = np.empty(n, dtype=object)
    up_date[:] = down_date[:] = through[:] = None
    dates = pd.to_datetime(frame.Date).dt.date.astype(str).to_numpy()
    for offset in range(1, min(int(horizon * 2.5), n - 1) + 1):
        length = n - offset
        active = (~halted[offset:]) & (sessions[:length] < horizon)
        count = sessions[:length]
        count[active] += 1
        valid = np.isfinite(high[offset:]) & (high[offset:] > 0) & (
            np.isfinite(close[offset:]) & (close[offset:] > 0))
        bad_price[:length] |= active & ~valid
        through[:length][active] = dates[offset:][active]
        hit_up = active & valid & (high[offset:] >= upper[:length]) & (up_day[:length] == 0)
        hit_down = active & valid & (close[offset:] <= lower[:length]) & (down_day[:length] == 0)
        up_day[:length][hit_up] = count[hit_up]
        down_day[:length][hit_down] = count[hit_down]
        up_date[:length][hit_up] = dates[offset:][hit_up]
        down_date[:length][hit_down] = dates[offset:][hit_down]
    complete = valid_base & ~bad_price & (sessions == horizon)
    up_day[halted] = 0
    down_day[halted] = 0
    up_date[halted] = None
    down_date[halted] = None
    through[halted] = None
    label = np.where((up_day > 0) & ((down_day == 0) | (up_day < down_day)), 2,
                     np.where(down_day > 0, 0, 1)).astype(object)
    label[~complete] = None
    reason = np.full(n, None, dtype=object)
    reason[~complete] = "observation_incomplete"
    reason[bad_price] = "missing_price"
    reason[~valid_base] = "invalid_sigma_or_close"
    reason[halted] = "base_halted"
    return pd.DataFrame({
        "Date": frame.Date, "complete": complete, "reason": reason,
        "up_barrier": upper, "down_barrier": lower,
        "up_hit": up_day > 0, "down_hit": down_day > 0,
        "up_first_date": up_date, "down_first_date": down_date,
        "observed_through": through, "outcome_class": label,
    })
