"""H5/H20 inference and signed explanations of the highest-scoring class."""

import hashlib
import json
import math

import numpy as np

BASE_INFO = {
    "Change": ("전일 대비 등락", "수정종가의 전일 대비 변화율"),
    "kmid": ("장중 종가 이동", "시가 대비 종가 이동 비율"),
    "klen": ("장중 가격 폭", "시가 대비 고가·저가 폭"),
    "kmid_2": ("가격 폭 안의 종가 이동", "고가·저가 폭 대비 시가에서 종가까지의 이동"),
    "kup": ("윗꼬리 길이", "시가 대비 고가와 시가·종가 중 높은 값의 차이"),
    "kup_2": ("윗꼬리 비중", "고가·저가 폭 중 윗꼬리의 비중"),
    "klow": ("아랫꼬리 길이", "시가 대비 시가·종가 중 낮은 값과 저가의 차이"),
    "klow_2": ("아랫꼬리 비중", "고가·저가 폭 중 아랫꼬리의 비중"),
    "ksft": ("종가의 범위 내 위치", "시가 대비 종가가 고가·저가 중간에서 벗어난 정도"),
    "ksft_2": ("종가의 상대 위치", "고가·저가 폭으로 나눈 종가의 중간 이탈"),
    "open_0": ("종가 대비 시가", "당일 시가를 수정종가로 나눈 값"),
    "high_0": ("종가 대비 고가", "당일 고가를 수정종가로 나눈 값"),
    "low_0": ("종가 대비 저가", "당일 저가를 수정종가로 나눈 값"),
    "vwap_0": ("종가 대비 평균 체결가", "수정 기준 거래대금·거래량 VWAP을 수정종가로 나눈 값"),
    "Barrier_Up": ("모델 입력 상방 가격", "학습 피처 규칙의 수정종가 × (1 + 1.5 Sigma)"),
    "Barrier_Down": ("모델 입력 하방 가격", "학습 피처 규칙의 수정종가 × (1 − 1.2 Sigma)"),
}
WINDOW_INFO = {
    "roc": ("과거 종가 비율", "기간 시작 종가 / 현재 종가"),
    "ma": ("평균 종가 비율", "기간 평균 종가 / 현재 종가"),
    "max": ("최고가 비율", "기간 최고가 / 현재 종가"),
    "min": ("최저가 비율", "기간 최저가 / 현재 종가"),
    "rsv": ("가격 범위 내 위치", "기간 고저 범위 안에서 현재 종가의 위치"),
    "std": ("종가 변동 폭", "기간 종가 표준편차 / 현재 종가"),
    "beta": ("가격 추세 기울기", "기간 종가의 일 단위 선형 추세 기울기"),
    "rsqr": ("가격 추세 적합도", "기간 선형 추세가 종가 변동을 설명하는 비율"),
    "resi": ("추세선 대비 종가", "추세선 대비 현재 종가 잔차 / 현재 종가"),
    "rank": ("종가 순위", "기간 종가와 비교한 현재 종가 순위"),
    "qtlu": ("상위 종가 분위", "기간 종가 80% 분위값 / 현재 종가"),
    "qtld": ("하위 종가 분위", "기간 종가 20% 분위값 / 현재 종가"),
    "imax": ("최고가 시점", "기간 내 최고가가 나온 위치"),
    "imin": ("최저가 시점", "기간 내 최저가가 나온 위치"),
    "imxd": ("고저 시점 차이", "최고가와 최저가가 나온 위치의 차이"),
    "cntp": ("상승일 비중", "기간 중 전일 대비 종가가 상승한 날의 비중"),
    "cntn": ("하락일 비중", "기간 중 전일 대비 종가가 하락한 날의 비중"),
    "cntd": ("상하락일 차이", "상승일 비중에서 하락일 비중을 뺀 값"),
    "sump": ("상승 이동 비중", "기간 절대 가격 이동 중 상승분의 비중"),
    "sumn": ("하락 이동 비중", "기간 절대 가격 이동 중 하락분의 비중"),
    "sumd": ("상하락 이동 차이", "상승 이동 비중에서 하락 이동 비중을 뺀 값"),
    "corr": ("가격·거래량 상관", "기간 종가 수준과 거래량 수준의 상관"),
    "cord": ("변화율 상관", "기간 종가 변화율과 거래량 변화율의 상관"),
    "vma": ("평균 거래량 비율", "기간 평균 거래량 / 현재 거래량"),
    "vstd": ("거래량 변동 폭", "기간 거래량 표준편차 / 현재 거래량"),
    "wvma": ("가중 장중 폭", "기간 거래량 가중 장중 가격 폭 / 현재 거래량"),
    "vsump": ("거래량 증가 비중", "기간 절대 거래량 변화 중 증가분 비중"),
    "vsumn": ("거래량 감소 비중", "기간 절대 거래량 변화 중 감소분 비중"),
    "vsumd": ("거래량 증감 차이", "증가 비중에서 감소 비중을 뺀 값"),
}


def feature_info(name):
    if name in BASE_INFO:
        return BASE_INFO[name]
    stem, _, window = name.rpartition("_")
    if stem in WINDOW_INFO and window in {"5", "10", "20", "30", "60"}:
        label, meaning = WINDOW_INFO[stem]
        return f"{window}일 {label}", f"{window}거래일 {meaning}"
    raise ValueError(f"Unreviewed feature name: {name}")


def infer_batch(model, features, *, class_index=None):
    """One model call per horizon for all valid current stock rows."""
    names = model.feature_name()
    if features.empty or set(names) - set(features):
        raise ValueError("Compatible feature rows required")
    frame = features[names].astype(float)
    values = frame.to_numpy()
    if np.isinf(values).any():
        raise ValueError("Infinite feature input")
    scores = np.asarray(model.predict(frame, num_threads=2), dtype=float)
    raw = np.asarray(model.predict(frame, raw_score=True, num_threads=2), dtype=float)
    contributions = np.asarray(model.predict(frame, pred_contrib=True, num_threads=2), dtype=float)
    if (scores.shape != (len(frame), 3) or raw.shape != (len(frame), 3)
        or contributions.shape != (len(frame), 3 * (len(names) + 1))
        or not np.isfinite(scores).all() or not np.isfinite(raw).all()
        or not np.isfinite(contributions).all() or not np.allclose(scores.sum(axis=1), 1)):
        raise ValueError("Invalid multiclass output")
    all_contrib = contributions.reshape(len(frame), 3, len(names) + 1)
    result = []
    for row_index, row_values in enumerate(values):
        target = int(np.argmax(scores[row_index])) if class_index is None else class_index
        row_contrib = all_contrib[row_index, target]
        if not math.isclose(float(row_contrib.sum()), float(raw[row_index, target]),
                            rel_tol=1e-6, abs_tol=1e-8):
            raise ValueError("Selected-class contributions do not sum to raw score")
        ordered = sorted(range(len(names)), key=lambda i: (-abs(row_contrib[i]), names[i]))[:5]
        features_top = []
        for index in ordered:
            label, meaning = feature_info(names[index])
            features_top.append({"name": names[index], "label_ko": label, "meaning_ko": meaning,
                                 "value": None if np.isnan(row_values[index]) else float(row_values[index]),
                                 "contribution": float(row_contrib[index])})
        canonical = json.dumps({name: None if np.isnan(value) else float(value)
                                for name, value in zip(names, row_values)}, sort_keys=True)
        feature_hash = hashlib.sha256(canonical.encode()).hexdigest()
        result.append(({"down": float(scores[row_index, 0]),
                        "neutral": float(scores[row_index, 1]),
                        "up": float(scores[row_index, 2])}, features_top, feature_hash,
                       float(np.abs(row_contrib[:-1]).sum())))
    return result
