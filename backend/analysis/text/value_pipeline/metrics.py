"""재무 지표 계산 (결정론적·검증가능).

LLM이 점수를 '추측'하게 두지 않고, 표준화된 재무 dict에서 공식으로 계산한다.
→ 재현성, 설명가능성, 디버깅 용이.

입력 financials dict의 표준 키(단위: 원, 비율은 그대로):
    revenue, revenue_prev, operating_profit, operating_profit_prev,
    net_income, net_income_prev, total_assets, total_liabilities,
    total_equity, current_assets, current_liabilities, inventories,
    retained_earnings, operating_cashflow, interest_expense, cash,
    shares_outstanding, price, sector_per, sector_pbr
누락된 키는 None 처리되어 해당 지표만 결측이 된다.
"""
from __future__ import annotations


def _num(f: dict, key: str) -> float | None:
    v = f.get(key)
    try:
        return float(v) if v is not None else None
    except (TypeError, ValueError):
        return None


def _div(a: float | None, b: float | None) -> float | None:
    if a is None or b is None or b == 0:
        return None
    return a / b


def _growth(cur: float | None, prev: float | None) -> float | None:
    # 전년 적자/0 기준은 성장률 왜곡 → 결측 처리
    if cur is None or prev is None or prev <= 0:
        return None
    return (cur - prev) / prev


def _altman_z(f: dict, mktcap: float | None) -> float | None:
    """Altman Z-Score (제조·상장 기준). >2.99 안전, <1.81 부실 위험."""
    ta = _num(f, "total_assets")
    tl = _num(f, "total_liabilities")
    if not ta or not tl or not mktcap:
        return None
    ca = _num(f, "current_assets") or 0.0
    cl = _num(f, "current_liabilities") or 0.0
    re = _num(f, "retained_earnings") or 0.0
    ebit = _num(f, "operating_profit") or 0.0
    sales = _num(f, "revenue") or 0.0
    x1 = (ca - cl) / ta          # 운전자본/총자산
    x2 = re / ta                 # 이익잉여금/총자산
    x3 = ebit / ta               # EBIT/총자산
    x4 = mktcap / tl             # 시가총액/총부채
    x5 = sales / ta              # 매출/총자산
    return 1.2 * x1 + 1.4 * x2 + 3.3 * x3 + 0.6 * x4 + 1.0 * x5


def compute_metrics(f: dict) -> dict:
    """표준화 재무 dict → FinancialMetrics 필드 dict."""
    shares = _num(f, "shares_outstanding")
    price = _num(f, "price")
    ni = _num(f, "net_income")
    eq = _num(f, "total_equity")
    ta = _num(f, "total_assets")
    tl = _num(f, "total_liabilities")
    rev = _num(f, "revenue")
    op = _num(f, "operating_profit")
    ca = _num(f, "current_assets")
    cl = _num(f, "current_liabilities")
    inv = _num(f, "inventories") or 0.0
    int_exp = _num(f, "interest_expense")
    cash = _num(f, "cash") or 0.0
    ebitda = _num(f, "ebitda") or op  # EBITDA 없으면 영업이익으로 근사

    eps = _div(ni, shares)
    bps = _div(eq, shares)
    mktcap = (price * shares) if (price is not None and shares) else None

    ni_growth = _growth(ni, _num(f, "net_income_prev"))
    per = _div(price, eps) if (eps is not None and eps > 0) else None
    # PEG: PER / 이익성장률(%). 성장률 0 이하면 의미 없음 → 결측
    peg = (per / (ni_growth * 100)) if (per is not None and ni_growth and ni_growth > 0) else None
    ev = (mktcap + tl - cash) if (mktcap is not None and tl is not None) else None

    return {
        "per": per,
        "pbr": _div(price, bps) if (bps is not None and bps > 0) else None,
        "psr": _div(mktcap, rev),
        "peg": peg,
        "ev_ebitda": _div(ev, ebitda) if (ebitda and ebitda > 0) else None,
        # 연간 보고서 경로(latest_financials)는 지배주주 순이익 ÷ 평균 지배주주지분을 넘긴다(#292). 없으면 기존식
        "roe": _div(_num(f, "roe_net_income"), _num(f, "roe_equity_avg")) if f.get("roe_equity_avg") else _div(ni, eq),
        "roa": _div(ni, ta),
        "operating_margin": _div(op, rev),
        "net_margin": _div(ni, rev),
        "revenue_growth": _growth(rev, _num(f, "revenue_prev")),
        "operating_profit_growth": _growth(op, _num(f, "operating_profit_prev")),
        "net_income_growth": ni_growth,
        "debt_ratio": _div(tl, eq),
        "current_ratio": _div(ca, cl),
        "quick_ratio": _div((ca - inv) if ca is not None else None, cl),
        "interest_coverage": _div(op, int_exp) if (int_exp and int_exp > 0) else None,
        "altman_z": _altman_z(f, mktcap),
    }


# ── 점수화 헬퍼 ────────────────────────────────────────────────
def _band(
    value: float | None,
    thresholds: list[float],
    scores: list[float],
    higher_better: bool = True,
) -> float | None:
    """임계값(내림차순)에 따라 0~10 점수 부여. value 결측이면 None.

    higher_better=True  : value가 thresholds[i] 이상이면 scores[i]
    higher_better=False : value가 thresholds[i] 이하이면 scores[i]
    """
    if value is None:
        return None
    for t, s in zip(thresholds, scores, strict=False):
        if (value >= t) if higher_better else (value <= t):
            return s
    return scores[-1]


def health_score(m: dict) -> float:
    """재무 건전성 0~10. 가용한 지표만 평균."""
    parts = []
    # 부채비율(낮을수록 좋음): 0.5배 이하 우수 ~ 2배 초과 위험
    parts.append(_band(m.get("debt_ratio"), [0.5, 1.0, 2.0], [10, 7, 4], higher_better=False))
    # 유동비율(높을수록 좋음)
    parts.append(_band(m.get("current_ratio"), [2.0, 1.5, 1.0], [10, 7, 4]))
    # 이자보상배율(높을수록 좋음): 5배↑ 안전, 1배 미만 위험
    parts.append(_band(m.get("interest_coverage"), [5.0, 2.0, 1.0], [10, 7, 4]))
    # ROE(높을수록 좋음)
    parts.append(_band(m.get("roe"), [0.15, 0.08, 0.0], [10, 7, 4]))
    # Altman Z(높을수록 안전)
    parts.append(_band(m.get("altman_z"), [2.99, 1.81, 0.0], [10, 6, 2]))
    vals = [p for p in parts if p is not None]
    return round(sum(vals) / len(vals), 2) if vals else 5.0


def valuation_score(
    m: dict, sector_per: float | None = None, sector_pbr: float | None = None
) -> float:
    """저평가 정도 0~10. 동종업계 평균 대비 할인율 기반 (높을수록 저평가=매력적)."""
    parts = []
    per, pbr = m.get("per"), m.get("pbr")
    if per is not None and per > 0:
        if sector_per and sector_per > 0:
            disc = sector_per / per  # >1 이면 업계보다 쌈
            parts.append(_band(disc, [1.3, 1.0, 0.7], [10, 6, 3]))
        else:  # 절대 기준
            parts.append(_band(per, [8, 15, 25], [10, 6, 3], higher_better=False))
    elif m.get("roe") is not None and m["roe"] <= 0:
        # 적자(ROE<=0) → 밸류에이션 매력 낮음.
        # per가 None인 이유는 '적자'와 '데이터 결측' 둘 다다. roe로 둘을 구분해,
        # 결측(주가·발행주식수 누락 등)을 적자로 오인해 3점을 주지 않는다.
        parts.append(3.0)
    if pbr is not None and pbr > 0:
        if sector_pbr and sector_pbr > 0:
            disc = sector_pbr / pbr
            parts.append(_band(disc, [1.3, 1.0, 0.7], [10, 6, 3]))
        else:
            parts.append(_band(pbr, [1.0, 1.5, 3.0], [10, 6, 3], higher_better=False))
    # PEG 보조 (1 미만이면 성장 대비 저평가)
    parts.append(_band(m.get("peg"), [1.0, 1.5, 2.0], [9, 6, 4], higher_better=False))
    vals = [p for p in parts if p is not None]
    return round(sum(vals) / len(vals), 2) if vals else 5.0
