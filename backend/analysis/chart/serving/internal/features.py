"""Serving inputs use the same causal builder as the corrected local models."""

import numpy as np
import pandas as pd
from core.local_features import build_feature_frame as build_local_features
from core.local_features import (  # noqa: F401
    generate_full_alpha158_features,
)
from experiments.features.flow import build_flow_features

from .calendar import reindex_to_krx_trading_days

SETTINGS = {"sigma_window": 20, "sigma_min_periods": 10,
            "barrier_feature_up_mult": 1.5, "barrier_feature_down_mult": 1.2}
BUILDER_ID = "local_v3_uniform_ohlc_flow_v1"


def build_feature_frame(raw, trading_days):
    if "VWAP" not in raw:
        raise ValueError("Actual VWAP is required")
    frame = build_local_features(raw, trading_days, SETTINGS)
    if "Amount" in raw and "Code" in raw:
        days = pd.to_datetime(sorted(trading_days))
        flow = build_flow_features(raw, days).drop(columns=["Code", "AvailableDate"])
        frame = frame.drop(columns=[c for c in flow if c.startswith("flow_")], errors="ignore")
        frame = frame.merge(flow, on="Date", how="left", validate="one_to_one")
    return frame


def normalize_trading_halts(df: pd.DataFrame, trading_days=None) -> pd.DataFrame:
    """
    거래정지·권리락일 처리 (표준 퀀트 관례 적용)

    1. 전체 시장 영업일 인덱스로 재구성 -> 누락일에 NaN 생성
    2. Close 0 값을 NaN으로 마킹 (0-값 행이 들어온 경우)
    3. Trading_Halt 플래그 생성 (0/누락값인 날 = 거래정지)
    4. Close -> ffill (직전 거래일 종가 유지)
    5. Open/High/Low -> 당일 Close 와 동일 (변동 없음 표시)
    6. Volume -> 0
    7. Log_Ret -> 0 (수익률 없음)
    """
    df = df.copy()

    # 1. 종목의 실제 거래 기간(상장~상폐)을 KRX 개장일로만 재구성
    df = reindex_to_krx_trading_days(df, trading_days)
    if "VWAP" not in df.columns:
        raise ValueError(
            "실제 VWAP 컬럼이 없습니다. 거래대금 기반 VWAP을 포함한 입력이 필요합니다."
        )
    traded_without_vwap = df["Volume"].fillna(0).gt(0) & (
        df["VWAP"].isna() | df["VWAP"].le(0)
    )
    if traded_without_vwap.any():
        raise ValueError("거래가 존재하는 원본 행에 실제 VWAP 값이 없습니다.")

    # 2. OHLCV 0 값 -> NaN
    for col in ["Open", "High", "Low", "Close", "Volume", "VWAP"]:
        if col in df.columns:
            df[col] = df[col].replace(0.0, np.nan)

    # 3. Trading_Halt 플래그: Close가 NaN인 날 = 거래정지
    df["Trading_Halt"] = df["Close"].isna().astype(int)

    # 4. Close -> ffill (직전 거래일 종가 유지)
    df["Close"] = df["Close"].ffill()

    # 5. Open / High / Low -> 당일 Close 와 동일 (가격 변화 없음)
    for col in ["Open", "High", "Low"]:
        if col in df.columns:
            df[col] = df[col].fillna(df["Close"])

    # 거래정지일에는 체결 VWAP이 없으므로 보존 종가와 동일하게 정규화
    df["VWAP"] = df["VWAP"].fillna(df["Close"])

    # 6. Volume -> 0
    if "Volume" in df.columns:
        df["Volume"] = df["Volume"].fillna(0.0)
    for col in ["Amount", "RawVolume"]:
        if col in df.columns:
            df[col] = df[col].fillna(0.0)

    # 비수정 종가와 수정계수는 새로 생성된 거래정지 행에 직전 값을 유지
    for col in ["RawClose", "AdjustmentFactor"]:
        if col in df.columns:
            df[col] = df[col].ffill()

    # 7. Change / Log_Ret -> 0
    for col in ["Change", "Log_Ret"]:
        if col in df.columns:
            df[col] = df[col].fillna(0.0)

    # 메타 컬럼(Code, Name, IsDelisted) ffill
    for col in ["Code", "Name", "IsDelisted"]:
        if col in df.columns:
            df[col] = df[col].ffill()

    return df.reset_index()
