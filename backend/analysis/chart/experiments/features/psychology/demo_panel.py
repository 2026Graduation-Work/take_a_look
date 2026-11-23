from __future__ import annotations

import numpy as np
import pandas as pd

DEMO_SEED = 20260817
DEMO_CODES = ("000001", "000002", "000003")


def build_demo_price_panel(
    codes: tuple[str, ...] = DEMO_CODES,
    periods: int = 180,
    start: str = "2024-01-02",
    seed: int = DEMO_SEED,
) -> pd.DataFrame:
    """종목마다 추세·변동성·거래량을 달리해 심리 피처가 상수로 붕괴하지 않게 한다."""
    if periods < 2 or not codes:
        raise ValueError("periods는 2 이상, codes는 한 개 이상이어야 합니다.")

    dates = pd.bdate_range(start=start, periods=periods)
    frames = []
    for index, code in enumerate(codes):
        generator = np.random.default_rng(seed + index)
        drift = 0.0004 * (index - 1)
        volatility = 0.012 + 0.004 * index
        returns = generator.normal(drift, volatility, size=periods)
        close = 50_000.0 * (1.0 + 10_000.0 * index / 50_000.0) * np.exp(np.cumsum(returns))
        # 거래량은 당일 변동폭이 클수록 늘어나는 형태로 만들어 군집·처분효과 피처가
        # 의미 있는 분산을 갖게 한다.
        base_volume = 1_000_000.0 * (index + 1)
        volume = base_volume * (1.0 + 3.0 * np.abs(returns) / volatility)
        volume = np.round(volume * generator.uniform(0.8, 1.2, size=periods))
        intraday = np.abs(generator.normal(0.0, volatility / 2.0, size=periods))
        frames.append(
            pd.DataFrame(
                {
                    "Date": dates,
                    "Code": code,
                    "Open": close * (1.0 - intraday / 2.0),
                    "High": close * (1.0 + intraday),
                    "Low": close * (1.0 - intraday),
                    "Close": close,
                    "Volume": volume,
                }
            )
        )
    return pd.concat(frames, ignore_index=True)
