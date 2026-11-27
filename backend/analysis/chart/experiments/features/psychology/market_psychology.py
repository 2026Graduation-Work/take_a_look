"""가격·거래량 계열만으로 시장 심리 피처를 계산한다.

설계 원칙은 세 가지다.

1. **미래 정보 금지.** 모든 값은 기준일 ``t``의 종가·거래량까지만 사용하는 닫힌
   롤링 윈도우로 계산하고, 산출물의 ``AvailableDate``는 항상 ``t`` 다음 거래일이다.
   즉 ``t``에 계산한 값은 ``t+1`` 행부터만 학습·평가에 쓰인다.
2. **결정론.** 난수·피팅·전역 통계(전체 기간 표준화)를 쓰지 않는다. 같은 입력과
   같은 :class:`PsychologyFeatureConfig`면 항상 같은 출력이 나온다.
3. **행동재무학 1:1 대응.** 각 원지표는 하나의 개념 프록시이며 대응 관계와 한계는
   ``experiments/features/PSYCHOLOGY_FEATURES.md``에 적는다.

A/B 실험의 ``features.treatment``에는 원지표 4개를 넣는다. 요약 축 2개는 원지표의
동일가중 평균이며(가중치 탐색·튜닝 없음), 모델 인풋이 아니라 화면·정렬·설명용
요약이다. 둘을 함께 학습에 넣으면 완전한 선형종속이 생기므로 그렇게 쓰지 않는다.
"""

from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass
from typing import Any

import numpy as np
import pandas as pd
from shared.data.segmented_prices import validate_segments

FEATURE_PROFILE = "psychology_market_v1"
GENERATOR_VERSION = "1.0.0"

#: 원지표. 각 값은 하나의 행동재무학 개념 프록시이며 모델 인풋으로 쓴다.
RAW_FEATURES = (
    "psych_fear_greed",
    "psych_herding",
    "psych_overreaction",
    "psych_disposition",
)
#: 요약 축. 원지표의 동일가중 평균이며 설명·정렬용이다(기본 학습 인풋 아님).
SUMMARY_AXES = (
    "psych_greed_fear_axis",
    "psych_crowd_pressure_axis",
)
#: A/B 러너 ``features.treatment``의 권장 구성.
TREATMENT_FEATURES = RAW_FEATURES
FEATURE_COLUMNS = RAW_FEATURES + SUMMARY_AXES

KEY_COLUMNS = ("Date", "Code", "AvailableDate")
REQUIRED_INPUT_COLUMNS = ("Date", "Code", "Close", "Volume")
OUTPUT_COLUMNS = (*KEY_COLUMNS, *FEATURE_COLUMNS)

_EPSILON = 1e-12


class PsychologyInputError(ValueError):
    """입력 가격 패널이 계산 계약을 어긴 경우 발생한다."""


@dataclass(frozen=True)
class PsychologyFeatureConfig:
    """윈도우와 압축 상수. 값을 바꾸면 새 profile 이름·경로를 쓴다.

    압축 상수는 데이터로 적합한 값이 아니라 사람이 고른 고정 상수다. 학습 데이터를
    보고 조정하면 결정론과 해석 가능성이 함께 깨지므로 실험 중에는 바꾸지 않는다.
    """

    fear_greed_window: int = 20
    herding_window: int = 20
    overreaction_short_window: int = 5
    overreaction_long_window: int = 60
    disposition_window: int = 60
    #: 과잉반응 z-score를 tanh로 압축할 때의 나눗수(z=2가 약 0.76이 된다).
    overreaction_squash_z: float = 2.0
    #: 미실현 손익 비율을 tanh로 압축할 때의 나눗수(10% 괴리가 약 0.76이 된다).
    disposition_squash_ratio: float = 0.10

    def __post_init__(self) -> None:
        windows = {
            "fear_greed_window": self.fear_greed_window,
            "herding_window": self.herding_window,
            "overreaction_short_window": self.overreaction_short_window,
            "overreaction_long_window": self.overreaction_long_window,
            "disposition_window": self.disposition_window,
        }
        for name, value in windows.items():
            if not isinstance(value, int) or isinstance(value, bool) or value < 2:
                raise PsychologyInputError(f"{name}은 2 이상의 정수여야 합니다: {value!r}")
        if self.overreaction_short_window >= self.overreaction_long_window:
            raise PsychologyInputError(
                "overreaction_short_window는 overreaction_long_window보다 짧아야 합니다."
            )
        for name, value in (
            ("overreaction_squash_z", self.overreaction_squash_z),
            ("disposition_squash_ratio", self.disposition_squash_ratio),
        ):
            if not isinstance(value, (int, float)) or isinstance(value, bool) or value <= 0:
                raise PsychologyInputError(f"{name}은 양수여야 합니다: {value!r}")

    @property
    def warmup_trading_days(self) -> int:
        """첫 값이 나오기까지 필요한 종목별 최소 거래일 수."""
        return max(
            self.fear_greed_window + 1,
            self.herding_window + 1,
            self.overreaction_short_window + self.overreaction_long_window,
            self.disposition_window,
        )


def _validate_input(frame: pd.DataFrame) -> pd.DataFrame:
    missing = [column for column in REQUIRED_INPUT_COLUMNS if column not in frame.columns]
    if missing:
        raise PsychologyInputError(f"가격 패널에 필수 컬럼이 없습니다: {missing}")

    columns = [*REQUIRED_INPUT_COLUMNS, *(["SegmentId"] if "SegmentId" in frame else [])]
    panel = frame[columns].copy()

    dates = pd.to_datetime(panel["Date"], errors="coerce")
    if dates.isna().any():
        sample = panel.loc[dates.isna(), "Date"].head(3).tolist()
        raise PsychologyInputError(f"해석할 수 없는 Date가 있습니다: {sample}")
    normalized = dates.dt.normalize()
    if dates.ne(normalized).any():
        raise PsychologyInputError("Date는 시간 정보 없는 일자여야 합니다.")
    panel["Date"] = normalized

    codes = panel["Code"].astype("string").str.strip()
    invalid = codes.isna() | ~codes.str.fullmatch(r"(?:\d{1,6}|\d{4}[0-9A-Z]{2})")
    if invalid.any():
        raise PsychologyInputError(
            f"Code는 앞자리 0을 보존한 숫자 또는 KRX 영문 포함 단축코드여야 합니다: {codes[invalid].head(3).tolist()}"
        )
    panel["Code"] = codes.str.zfill(6).astype(object)

    for column in ("Close", "Volume"):
        numeric = pd.to_numeric(panel[column], errors="coerce")
        if numeric.isna().any():
            raise PsychologyInputError(f"{column}에 숫자가 아닌 값이 있습니다.")
        panel[column] = numeric.astype(float)
    if (panel["Close"] <= 0).any():
        raise PsychologyInputError("Close는 0보다 커야 합니다(로그수익률 계산 불가).")
    if (panel["Volume"] < 0).any():
        raise PsychologyInputError("Volume은 음수일 수 없습니다.")

    if panel.duplicated(["Code", "Date"]).any():
        sample = panel.loc[panel.duplicated(["Code", "Date"]), ["Code", "Date"]].head(3)
        raise PsychologyInputError(f"(Code, Date) 중복 행이 있습니다: {sample.to_dict('records')}")

    panel = panel.sort_values(["Code", "Date"], kind="stable").reset_index(drop=True)
    validate_segments(panel)
    return panel


def _safe_divide(numerator: pd.Series, denominator: pd.Series) -> pd.Series:
    """분모가 0에 가까우면 값을 만들지 않고 결측으로 남긴다."""
    guarded = denominator.where(denominator.abs() > _EPSILON)
    return numerator / guarded


def _code_features(panel: pd.DataFrame, config: PsychologyFeatureConfig) -> pd.DataFrame:
    """한 종목의 시계열에서 심리 피처를 계산한다. 모든 창은 기준일까지만 본다."""
    close = panel["Close"]
    volume = panel["Volume"]
    log_return = np.log(close / close.shift(1))

    # 1) 공포·탐욕: 위험 대비 모멘텀. 같은 상승폭이라도 변동성이 낮으면 더 탐욕적이다.
    window = config.fear_greed_window
    cumulative = log_return.rolling(window, min_periods=window).sum()
    deviation = log_return.rolling(window, min_periods=window).std(ddof=1)
    fear_greed = np.tanh(_safe_divide(cumulative, deviation * np.sqrt(window)))

    # 2) 군집행동: 거래량이 실린 날의 방향이 한쪽으로 몰린 정도.
    window = config.herding_window
    signed_volume = np.sign(log_return) * volume
    herding = _safe_divide(
        signed_volume.rolling(window, min_periods=window).sum(),
        volume.rolling(window, min_periods=window).sum(),
    )

    # 3) 과잉반응: 단기 수익률이 자기 종목의 최근 분포에서 얼마나 벗어났는가.
    short = config.overreaction_short_window
    long = config.overreaction_long_window
    short_return = np.log(close / close.shift(short))
    mean_short = short_return.rolling(long, min_periods=long).mean()
    std_short = short_return.rolling(long, min_periods=long).std(ddof=1)
    overreaction = np.tanh(
        _safe_divide(short_return - mean_short, std_short) / config.overreaction_squash_z
    )

    # 4) 처분효과: 최근 거래량가중 평균단가 대비 미실현 손익(capital gains overhang).
    window = config.disposition_window
    turnover = (close * volume).rolling(window, min_periods=window).sum()
    traded = volume.rolling(window, min_periods=window).sum()
    reference_price = _safe_divide(turnover, traded)
    disposition = np.tanh(
        _safe_divide(close - reference_price, reference_price) / config.disposition_squash_ratio
    )

    features = pd.DataFrame(
        {
            "Date": panel["Date"].to_numpy(),
            "Code": panel["Code"].to_numpy(),
            "psych_fear_greed": fear_greed.to_numpy(dtype=float),
            "psych_herding": herding.to_numpy(dtype=float),
            "psych_overreaction": overreaction.to_numpy(dtype=float),
            "psych_disposition": disposition.to_numpy(dtype=float),
        }
    )
    # 요약 축은 동일가중 평균이다. 학습 데이터를 본 가중치 탐색을 하지 않는다.
    features["psych_greed_fear_axis"] = (
        features["psych_fear_greed"] + features["psych_disposition"]
    ) / 2.0
    features["psych_crowd_pressure_axis"] = (
        features["psych_herding"] + features["psych_overreaction"]
    ) / 2.0

    next_date = panel["Date"].shift(-1)
    if "SegmentId" in panel:
        features["SegmentId"] = panel["SegmentId"].to_numpy()
    else:
        next_date = next_date.fillna(panel["Date"].iloc[-1] + pd.tseries.offsets.BusinessDay(1))
    features["AvailableDate"] = next_date.to_numpy()
    return features


def build_psychology_features(
    prices: pd.DataFrame,
    config: PsychologyFeatureConfig | None = None,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """가격 패널에서 심리 피처 표와 산출 메타데이터를 만든다.

    Parameters
    ----------
    prices:
        ``Date``, ``Code``, ``Close``, ``Volume``을 가진 일별 패널. 여러 종목을 한
        DataFrame에 넣어도 되고, 행 순서는 결과에 영향을 주지 않는다.
    config:
        윈도우와 압축 상수. 생략하면 기본값을 쓴다.

    Returns
    -------
    (features, metadata)
        ``features``는 ``Date``/``Code``/``AvailableDate`` + 피처 6개이며 결측이
        없다(워밍업 구간은 행 자체가 없다). ``metadata``에는 설정·버전·입력
        지문이 들어간다.
    """
    config = config or PsychologyFeatureConfig()
    panel = _validate_input(prices)
    if panel.empty:
        raise PsychologyInputError("가격 패널이 비어 있습니다.")

    input_fingerprint = _fingerprint(panel)
    input_rows = int(len(panel))

    keys = ["Code", "SegmentId"] if "SegmentId" in panel else ["Code"]
    frames = [
        _code_features(group.reset_index(drop=True), config)
        for _, group in panel.groupby(keys, sort=True, observed=True)
    ]
    features = pd.concat(frames, ignore_index=True)
    features = features[[*OUTPUT_COLUMNS, *keys[1:]]]

    complete = features.AvailableDate.notna() & features[list(FEATURE_COLUMNS)].notna().all(axis=1)
    finite = np.isfinite(features[list(FEATURE_COLUMNS)].to_numpy(dtype=float)).all(axis=1)
    features = features.loc[complete & finite].copy()
    features = features.sort_values(["Code", "Date"], kind="stable").reset_index(drop=True)
    if features.empty:
        raise PsychologyInputError(
            "워밍업 구간을 넘긴 행이 없습니다. 종목당 최소 "
            f"{config.warmup_trading_days}거래일이 필요합니다."
        )

    metadata = {
        "feature_profile": FEATURE_PROFILE,
        "generator_version": GENERATOR_VERSION,
        "config": asdict(config),
        "warmup_trading_days": config.warmup_trading_days,
        "features": {
            "raw": list(RAW_FEATURES),
            "summary_axes": list(SUMMARY_AXES),
            "recommended_treatment": list(TREATMENT_FEATURES),
        },
        "input": {
            "rows": input_rows,
            "codes": int(panel["Code"].nunique()),
            "start_date": panel["Date"].min().strftime("%Y-%m-%d"),
            "end_date": panel["Date"].max().strftime("%Y-%m-%d"),
            "fingerprint_sha256": input_fingerprint,
        },
        "output": {
            "rows": int(len(features)),
            "codes": int(features["Code"].nunique()),
            "start_date": features["Date"].min().strftime("%Y-%m-%d"),
            "end_date": features["Date"].max().strftime("%Y-%m-%d"),
            "dropped_warmup_rows": input_rows - int(len(features)),
            "fingerprint_sha256": _fingerprint(features),
        },
    }
    return features, metadata


def _fingerprint(frame: pd.DataFrame) -> str:
    """행 순서에 의존하지 않는 내용 지문."""
    hashes = np.sort(pd.util.hash_pandas_object(frame, index=False).to_numpy())
    return hashlib.sha256(hashes.tobytes()).hexdigest()
