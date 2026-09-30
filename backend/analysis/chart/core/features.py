"""Training labels; feature calculations are shared with serving."""

import numpy as np
import pandas as pd

try:
    from ..data_collectors.trading_calendar import reindex_to_krx_trading_days
    from ..serving.internal.features import (
        generate_full_alpha158_features as generate_full_alpha158_features,
    )
    from ..serving.internal.features import normalize_trading_halts as _normalize
except ImportError:
    from data_collectors.trading_calendar import reindex_to_krx_trading_days
    from serving.internal.features import (
        generate_full_alpha158_features as generate_full_alpha158_features,
    )
    from serving.internal.features import normalize_trading_halts as _normalize


def normalize_trading_halts(df, trading_days=None):
    indexed = reindex_to_krx_trading_days(df, trading_days)
    return _normalize(indexed, indexed.index)


def calculate_dynamic_triple_barrier(
    df: pd.DataFrame, horizon=5, up_mult=1.5, down_mult=1.2
) -> pd.DataFrame:
    """
    동적 트리플 배리어 타겟팅 (Dynamic Triple Barrier Method)

    매수 시점의 최근 20일 로그수익률의 변동성(Sigma)에 기반하여 상/하방 배리어를 가변 설정하고,
    미래 N영업일(horizon) 동안 주가가 어디에 먼저 닿았는지 라벨(1, 0, -1)을 부여합니다.
    """
    df = df.copy()

    # 1. 일일 로그 수익률
    df["Log_Ret"] = np.log(df["Close"] / (df["Close"].shift(1) + 1e-8))
    if "Trading_Halt" in df.columns:
        df.loc[df["Trading_Halt"] == 1, "Log_Ret"] = 0.0

    # 2. 최근 20 실거래일 변동성 (거래정지일 제외)
    trading_log_ret = df["Log_Ret"].where(df.get("Trading_Halt", pd.Series(0, index=df.index)) == 0)
    df["Sigma"] = trading_log_ret.rolling(20, min_periods=10).std()

    # 3. 동적 배리어 설정
    df["Barrier_Up"] = df["Close"] * (1 + up_mult * df["Sigma"])
    df["Barrier_Down"] = df["Close"] * (1 - down_mult * df["Sigma"])

    df["Y_Label"] = 0

    hit_up_day = pd.Series(999, index=df.index)
    hit_down_day = pd.Series(999, index=df.index)
    halt_flag = df.get("Trading_Halt", pd.Series(0, index=df.index))

    # 4. 미래 horizon 영업일 추적 (거래정지일 스킵 및 horizon 연장)
    trading_day_cumsum = (1 - halt_flag).cumsum()
    max_search_days = int(horizon * 2.5)

    for d in range(1, max_search_days + 1):
        future_high = df["High"].shift(-d)
        future_close = df["Close"].shift(-d)
        future_halt = halt_flag.shift(-d).fillna(1)

        # 미래 d 시점까지 경과한 실제 거래일 수
        passed_trading_days = (trading_day_cumsum.shift(-d) - trading_day_cumsum).fillna(999)

        # 실제 거래일 기준 horizon 이내이고 거래정지가 아닌 날짜만 유효
        active = (future_halt == 0) & (passed_trading_days <= horizon)

        is_hit_up = active & (future_high >= df["Barrier_Up"])
        is_hit_down = active & (future_close <= df["Barrier_Down"])

        hit_up_day = np.where((is_hit_up) & (hit_up_day == 999), passed_trading_days, hit_up_day)
        hit_down_day = np.where(
            (is_hit_down) & (hit_down_day == 999), passed_trading_days, hit_down_day
        )

    # 5. 최종 라벨링
    success_mask = (hit_up_day != 999) & (hit_up_day < hit_down_day)
    fail_mask = (hit_down_day != 999) & (hit_down_day <= hit_up_day)

    df.loc[success_mask, "Y_Label"] = 1
    df.loc[fail_mask, "Y_Label"] = -1

    # 6. 미래 참조 누수 차단
    if len(df) > horizon:
        df.loc[df.index[-horizon:], "Y_Label"] = np.nan

    return df
