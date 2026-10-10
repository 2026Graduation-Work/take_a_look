"""한국어 금융 감성 분석.

1순위: KR-FinBERT (snunlp/KR-FinBert-SC) 로컬 추론 — 무료, 한국어 금융 특화.
폴백 : transformers/torch/모델이 없으면 한국어 금융 사전 기반 점수.

→ 어떤 환경에서도 -1..1 점수를 반환하므로 파이프라인이 끊기지 않는다.
"""
from __future__ import annotations

import math
from functools import lru_cache

# 사전 기반 폴백용 최소 금융 감성 어휘
_POS = {
    "상승", "급등", "호재", "수주", "흑자", "성장", "개선", "최대", "돌파", "증가",
    "상향", "기대", "순항", "신고가", "호실적", "반등", "강세", "확대", "수익",
}
_NEG = {
    "하락", "급락", "악재", "적자", "감소", "부진", "우려", "하향", "리콜", "소송",
    "손실", "위기", "하한가", "경고", "둔화", "리스크", "파산", "약세", "축소", "충당금",
}


class SentimentBackendError(RuntimeError):
    """요청된 감성 백엔드를 사용할 수 없을 때 발생한다."""


@lru_cache(maxsize=1)
def _load_finbert():
    """KR-FinBERT 파이프라인 로드. 실패 시 None (폴백 신호)."""
    try:
        from transformers import pipeline

        from .config import SETTINGS

        if not SETTINGS.use_finbert:
            return None
        return pipeline("sentiment-analysis", model=SETTINGS.finbert_model, top_k=None)
    except Exception:
        return None


def _lexicon_score(text: str) -> float:
    pos = sum(1 for w in _POS if w in text)
    neg = sum(1 for w in _NEG if w in text)
    if pos == 0 and neg == 0:
        return 0.0
    return (pos - neg) / (pos + neg)


def _score_label_rows(rows: list[dict[str, object]]) -> float:
    probs = {str(d["label"]).lower(): float(d["score"]) for d in rows}
    pos = next((v for k, v in probs.items() if "pos" in k or "긍정" in k), 0.0)
    neg = next((v for k, v in probs.items() if "neg" in k or "부정" in k), 0.0)
    return pos - neg


def _normalize_batch_output(output: object, expected: int) -> list[list[dict[str, object]]]:
    """transformers 단건/배치 출력 모양을 입력별 label 행으로 통일한다."""
    if isinstance(output, dict):
        return [[output]]
    if not isinstance(output, list):
        raise TypeError("unexpected KR-FinBERT output")
    if expected == 1 and (not output or isinstance(output[0], dict)):
        return [output]
    normalized: list[list[dict[str, object]]] = []
    for item in output:
        if isinstance(item, dict):
            normalized.append([item])
        elif isinstance(item, list) and all(isinstance(row, dict) for row in item):
            normalized.append(item)
        else:
            raise TypeError("unexpected KR-FinBERT batch row")
    if len(normalized) != expected:
        raise ValueError("KR-FinBERT output count does not match input count")
    return normalized


def score_texts(
    texts: list[str], *, require_finbert: bool = False, batch_size: int = 16
) -> tuple[list[float], str]:
    """각 텍스트 감성(-1..1) 리스트와 사용 백엔드명 반환."""
    texts = [t for t in texts if t and t.strip()]
    if not texts:
        return [], "none"
    clf = _load_finbert()
    if clf is None and require_finbert:
        raise SentimentBackendError("KR-FinBERT를 불러오지 못했습니다")
    if clf is not None:
        try:
            output = clf([text[:512] for text in texts], batch_size=batch_size)
            rows_by_text = _normalize_batch_output(output, len(texts))
            scores = [
                max(-1.0, min(1.0, _score_label_rows(rows))) for rows in rows_by_text
            ]
            return scores, "kr-finbert"
        except Exception as exc:
            if require_finbert:
                raise SentimentBackendError("KR-FinBERT 추론에 실패했습니다") from exc
    return [_lexicon_score(t) for t in texts], "lexicon"


def aggregate(scores: list[float], weights: list[float] | None = None) -> tuple[float, float]:
    """가중 평균 감성과 표준편차(의견 분산=불확실성) 반환."""
    if not scores:
        return 0.0, 0.0
    if weights is None:
        weights = [1.0] * len(scores)
    wsum = sum(weights) or 1.0
    mean = sum(s * w for s, w in zip(scores, weights, strict=False)) / wsum
    var = sum(w * (s - mean) ** 2 for s, w in zip(scores, weights, strict=False)) / wsum
    return round(mean, 4), round(math.sqrt(var), 4)
