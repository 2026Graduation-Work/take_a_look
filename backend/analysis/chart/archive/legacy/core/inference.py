import os

import lightgbm as lgb
import pandas as pd

from .features import (
    calculate_dynamic_triple_barrier,
    generate_full_alpha158_features,
    normalize_trading_halts,
)

# 학습 과정에서 정의된 특성(Feature) 목록 (Alpha158 컬럼들 + 기타 가공 피처들)
# 모델에 입력되는 피처 순서와 개수(161개)가 정확히 일치해야 정상적인 추론이 가능합니다.
FEATURE_COLS = [
    "Change",
    "kmid",
    "klen",
    "kmid_2",
    "kup",
    "kup_2",
    "klow",
    "klow_2",
    "ksft",
    "ksft_2",
    "open_0",
    "high_0",
    "low_0",
    "vwap_0",
]
# W일 Window 기반 피처 동적 추가 (5, 10, 20, 30, 60)
for w in [5, 10, 20, 30, 60]:
    FEATURE_COLS.extend(
        [
            f"roc_{w}",
            f"ma_{w}",
            f"max_{w}",
            f"min_{w}",
            f"rsv_{w}",
            f"std_{w}",
            f"beta_{w}",
            f"rsqr_{w}",
            f"resi_{w}",
            f"rank_{w}",
            f"qtlu_{w}",
            f"qtld_{w}",
            f"imax_{w}",
            f"imin_{w}",
            f"imxd_{w}",
            f"cntp_{w}",
            f"cntn_{w}",
            f"cntd_{w}",
            f"sump_{w}",
            f"sumn_{w}",
            f"sumd_{w}",
            f"corr_{w}",
            f"cord_{w}",
            f"vma_{w}",
            f"vstd_{w}",
            f"wvma_{w}",
            f"vsump_{w}",
            f"vsumn_{w}",
            f"vsumd_{w}",
        ]
    )
FEATURE_COLS.extend(["Barrier_Up", "Barrier_Down"])


def load_prediction_model(model_path: str) -> lgb.Booster:
    """
    저장된 LightGBM Booster 모델(txt 포맷)을 로드합니다.
    """
    if not os.path.exists(model_path):
        raise FileNotFoundError(f"[ERROR] 모델 파일 ({model_path})을 찾을 수 없습니다.")

    # Booster 객체로 모델 복원
    model = lgb.Booster(model_file=model_path)
    return model


def predict_success_probability(df: pd.DataFrame, model: lgb.Booster) -> pd.Series:
    """
    일봉 OHLCV 데이터프레임이 주어졌을 때,
    기술적 피처를 추출하고 학습 완료된 모델을 통해 '상승 성공(Class 2)' 확률을 리턴합니다.

    Parameters:
    -----------
    df : pd.DataFrame
        컬럼으로 ['Date', 'Open', 'High', 'Low', 'Close', 'Volume', 'VWAP']을 포함해야 합니다.
        VWAP은 거래대금/거래량으로 계산하고 수정주가 배율을 적용한 일별 값이어야 합니다.
    model : lgb.Booster
        load_prediction_model() 함수로 사전에 로드된 모델 객체

    Returns:
    --------
    pd.Series
        각 영업일별 주가 상승 성공 확률 (0.0 ~ 1.0 범위)
    """
    df_processed = df.copy()

    # 1. 거래정지 및 누락일 보정
    # 거래일은 범위를 덮는 캐시가 있으면 네트워크 없이 캐시에서 받는다(#107)
    df_processed = normalize_trading_halts(df_processed)

    # 2. 기술적 지표 생성
    df_processed = generate_full_alpha158_features(df_processed)

    # 3. 동적 배리어 생성 (Barrier_Up, Barrier_Down 피처 공급)
    df_processed = calculate_dynamic_triple_barrier(df_processed)

    # 4. 모델 피처 추출
    # 누락 데이터 방지를 위해 피처 계산에 필요한 최소 행(60일 이상) 확인
    if len(df_processed) < 65:
        # 데이터가 부족하면 빈 결과를 리턴
        return pd.Series([0.0] * len(df_processed), index=df_processed["Date"])

    X = df_processed[FEATURE_COLS]

    # 5. 다중 클래스 확률 예측 수행
    # 3개의 클래스 예측 결과 반환: [Fail, Hold, Success]
    probs = model.predict(X)

    # 6. Success(상방 배리어 도달) 확률인 2번째 인덱스 반환
    success_prob = probs[:, 2]

    # 원본 인덱스와 Date를 맞춰주기 위해 Series 형태로 변환
    return pd.Series(success_prob, index=df_processed["Date"])
