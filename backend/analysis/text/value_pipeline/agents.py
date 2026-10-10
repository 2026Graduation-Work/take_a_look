"""멀티 에이전트 노드 (LangGraph에서 호출).

    ingest → {news_agent ∥ financial_agent} → validation_agent → synthesis_agent

설계 원칙 (AGENTS.md '정량/정성 분리')
- 수치 피처(감성·재무점수·영향력·시그널·신뢰도)는 결정론적으로 계산 → 재현성·설명가능성.
- LLM은 핵심 이벤트 추출과 자연어 근거 설명만 담당한다. 뉴스 관련성도 규칙으로 판정한다.
  LLM 출력은 llm.structured가 content-hash로 동결하므로 재실행 시 결정론이 유지된다.
- validation_agent는 규칙 기반이다. LLM 크리틱은 쓰지 않는다 —
  자기검증은 실증적으로 성능을 떨어뜨리고(ICLR 2024), 판사 LLM은 저perplexity
  텍스트를 선호해 매끄러운 보도자료를 진짜 새 정보보다 높게 친다.

## 관련성 필터는 왜 규칙인가 (실측)

빅카인즈 키워드 검색이라 무관 기사가 섞이고, 이걸 거르면 감성 부호가 뒤집힌다.
2022-06-15(삼성전자 52주 신저가일): 필터 없이 73건 = +0.0191(긍정, 틀림),
'삼성' 필터 37건 = -0.0189(부정, 맞음). '구미대-희망디딤돌 업무협약'·'두산 반도체
투자'·'미래에셋 ELW 상장' 같은 기사가 FinBERT에서 만점 긍정을 받는데, 판정은 다 맞다
— 삼성전자 기사가 아닐 뿐이다.

**필터는 필요하지만 LLM일 필요는 없다.** 2022년 6일 표본 측정:

    필터없음 vs LLM 평균 절대차 : 0.1160
    규칙     vs LLM 평균 절대차 : 0.0337  (상관 0.9901, Jaccard 0.87, 부호 불일치 0/6일)

필터 유무는 3.4배 더 중요하고, 어떤 필터냐는 거의 차이가 없다. 그래서 관련성은
결정론 규칙으로 하고 LLM은 점수 경로에서 완전히 뺀다 — 라벨이 채점 대상을 정하면
그건 곧 점수를 정하는 것이라 AGENTS.md '점수 산출 100% 결정론' 위반이다.

(본문 200자 중간 절단(82.4%)도 FinBERT 감성에 영향이 없다: raw vs 완전문장 트리밍 r=0.9995.)
"""
from __future__ import annotations

from pydantic import BaseModel, Field

from . import metrics, staleness
from .config import SETTINGS
from .llm import structured
from .schema import (
    FinancialAnalysis,
    FinancialMetrics,
    KeyEvent,
    NewsAnalysis,
    ValidationResult,
    ValueSignal,
)
from .sentiment import aggregate, score_texts


# ── LLM 보조 출력 스키마 ────────────────────────────────────────
# 주의: 이 스키마들에 '점수'도 '어떤 기사를 쓸지 고르는 필드'도 추가하지 말 것.
# 점수든 채점 대상 선택이든 LLM이 정하면 결과가 LLM에 의존한다. LLM 출력 계약에
# 그런 필드가 없어야 실수로 점수 경로에 다시 연결되지 않는다(관례가 아니라 구조로 강제).
# 여기 남은 것은 전부 '사람이 읽는 텍스트'이며 어떤 숫자에도 영향을 주지 않는다.
class _NewsExtract(BaseModel):
    key_events: list[str] = Field(
        default_factory=list, description="그날의 핵심 이벤트 3~6개, 간결한 한국어 명사구"
    )


class _Reason(BaseModel):
    reasoning: str = Field(
        "",
        description="수치와 핵심 이벤트의 관계를 설명하는 한국어 2~3문장, 행동 제안 금지",
    )


_BEHAVIOR_ADVICE_MARKERS = (
    "매수를 권",
    "매도를 권",
    "보유를 권",
    "관망을 권",
    "매수하는 것이",
    "매도하는 것이",
    "보유하는 것이",
    "관망하는 것이",
    "매수를 고려",
    "매도를 고려",
    "보유를 고려",
    "관망을 고려",
    "신규 진입",
    "진입을 고려",
    "진입하는 것이",
    "청산을 고려",
    "청산하는 것이",
    "비중을 늘",
    "비중을 줄",
    "비중을 확대",
    "비중을 축소",
    "비중을 조절",
    "비중을 점검",
    "포지션을 유지",
    "포지션을 확대",
    "포지션을 축소",
    "손절",
    "익절",
)


def _contains_behavior_advice(reasoning: str) -> bool:
    normalized = "".join((reasoning or "").split())
    return any(
        "".join(marker.split()) in normalized for marker in _BEHAVIOR_ADVICE_MARKERS
    )


def _clip(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


def impact_score(article_count: int, mean_sentiment: float) -> int:
    """뉴스 영향력 1~10 — 기사 수·감성 강도의 결정론 규칙 (일별·기간 모드 공용)."""
    return int(_clip(3 + min(4, article_count // 3) + round(abs(mean_sentiment) * 3), 1, 10))


def synthesize_scores(
    valuation: float,
    health: float,
    news_sentiment: float,
    impact: int,
    sentiment_std: float,
    real_sources: int,
) -> tuple[float, str, float]:
    """(composite, signal, confidence) 결정론 공식 — 일별·기간 모드 공용.

    schema.ValueSignal 도크스트링의 공식 그 자체다. 한 곳에만 두는 이유:
    일별(synthesis_agent)과 기간(period.py)에 복제되어 있으면 한쪽만 고치는
    사고가 난다(PR #67 리뷰 Q2). 양쪽 self-auditing 테스트가 이 공식을 못박는다.
    """
    fundamental = valuation * 0.6 + health * 0.4              # 0~10
    sentiment_adj = news_sentiment * (impact / 10.0) * 2.0    # ±2 내외
    composite = _clip(fundamental + sentiment_adj, 0.0, 10.0)
    signal = _to_signal(composite)

    # 신뢰도: 데이터 품질 + 시그널 마진 - 뉴스 의견분산 (LLM 자기보고 대신 직접 산출)
    quality = 0.5 + 0.125 * real_sources                      # 0.5~0.75 (2소스)
    margin = abs(composite - 5.0) / 5.0                       # 0~1 (확신 강도)
    confidence = round(_clip(quality + 0.2 * margin - 0.15 * sentiment_std, 0.2, 0.95), 3)
    return composite, signal, confidence


def _text_of(item: dict) -> str:
    return f"{item.get('title', '')} {item.get('summary', '')}".strip()


# ── News Agent ─────────────────────────────────────────────────
# 종목별 관련성 키워드 override — 접미사 휴리스틱으로 안 잡히는 회사만 명시한다.
# AGENTS.md '알려진 한계 6'이 요구하는 "종목별 relevance_key 검증"의 결과물이다.
# 에코프로비엠: 언론이 그룹명 '에코프로'로 쓰는 기사가 많다(실측: 전량 탈락하던
# 1,010일 중 126일이 이 키워드로 복구). 삼성전자→'삼성'과 같은 그룹명 방식이다.
_RELEVANCE_KEY_OVERRIDES = {
    "에코프로비엠": "에코프로",
}


def relevance_key(company: str) -> str:
    """회사명에서 관련성 판정용 키워드를 만든다.

    '삼성전자' → '삼성'. 제목에 '삼성전자'를 그대로 박는 기사는 폭락일엔 대부분
    주가 기사라, 그것만 남기면 표본이 편향된다(실측: 2022-06-15에 10건만 남고
    감성 -0.80). ASML·롤러블폰 기사는 '삼성'이라고만 쓴다.
    법인격 접미사를 떼어 회사 그룹명을 키워드로 쓴다.
    접미사 규칙으로 안 되는 종목은 _RELEVANCE_KEY_OVERRIDES에 명시한다.
    """
    key = (company or "").replace(" ", "")
    if key in _RELEVANCE_KEY_OVERRIDES:
        return _RELEVANCE_KEY_OVERRIDES[key]
    for suffix in ("전자", "그룹", "주식회사", "(주)", "홀딩스"):
        if len(key) > len(suffix) and key.endswith(suffix):
            return key[: -len(suffix)]
    return key


def relevant_indices(
    items: list[dict], company: str, *, key_override: str | None = None
) -> list[int]:
    """해당 기업 관련 기사의 인덱스. 100% 결정론 — LLM을 쓰지 않는다.

    제목+본문에 회사 키워드가 있으면 관련으로 본다. 빅카인즈 본문은 200자로
    잘려 있어 스쳐 지나가는 언급이 적고, 실측상 LLM 판정과 거의 일치한다
    (2022년 6일 표본: 상관 0.9901, Jaccard 0.87, 감성 부호 불일치 0/6일).

    회사명이 비면 전량을 관련으로 본다 — 거를 근거가 없는데 임의로 거르면 안 된다.
    """
    key = (key_override or "").replace(" ", "") or relevance_key(company)
    if not key:
        return list(range(len(items)))
    return [
        i
        for i, it in enumerate(items)
        if key in f"{it.get('title', '')} {it.get('summary', '')}".replace(" ", "")
    ]


def _extract_events(items: list[dict], company: str) -> list[str]:
    """LLM 배치 1콜로 핵심 이벤트 추출. 설명 텍스트 전용 — 어떤 숫자에도 안 쓰인다.

    LLM이 하는 일은 같은 사건을 다룬 기사들을 하나로 묶는 것이다
    (예: ASML 관련 8건 → '이재용 부회장, ASML 반도체 장비 수급 논의' 1줄).
    실패하면 빈 리스트 → 호출자가 규칙 폴백(감성 절댓값 상위 헤드라인)을 쓴다.
    """
    if not items:
        return []
    listing = "\n".join(f"- {_text_of(it)[:150]}" for it in items[:60])
    out = structured(
        f"다음은 '{company}' 관련 하루치 뉴스다.\n\n{listing}\n\n"
        f"같은 사건을 다룬 기사들을 하나로 묶어, 그날의 핵심 이벤트를 3~6개의 "
        f"간결한 한국어 명사구로 추출하라. 기사에 없는 내용을 지어내지 말 것.",
        _NewsExtract,
    )
    return out.key_events[:6] if out is not None else []


def news_agent(state: dict) -> dict:
    items = state.get("raw_news") or []
    company = state.get("company_name") or state.get("ticker") or ""
    raw_count = len(items)

    # 관련성 판정은 100% 결정론. 전부 걸러지면 그대로 0건으로 둔다 —
    # 전량 복원하면 '무관 기사로 만든 감성'이 정상 행처럼 보인다.
    # article_count=0 이면 validation_agent가 실패시킨다.
    keep = relevant_indices(items, company)
    relevant_all = [items[i] for i in keep]
    relevant = relevant_all[: SETTINGS.max_daily_articles]
    dropped = len(relevant_all) - len(relevant)
    texts = [_text_of(it) for it in relevant]
    scores, backend = score_texts(texts)
    mean, std = aggregate(scores)

    # 영향력 점수는 결정론 규칙으로 산출한다.
    # (AGENTS.md: 점수 산출은 100% 결정론, LLM은 설명 텍스트 생성에만)
    impact = impact_score(len(texts), mean)

    # 핵심 이벤트(설명 전용). LLM 문구를 실제 기사에 그라운딩해 출처 news_id를 붙인다.
    llm_events = _extract_events(relevant, company)
    if llm_events:
        key_events = [_ground_event(e, relevant) for e in llm_events]
        event_backend = "llm"
    else:  # 규칙 기반 폴백: 감성 절댓값이 큰 헤드라인을 핵심 이벤트로
        ranked = sorted(
            zip(relevant, scores, strict=True), key=lambda x: abs(x[1]), reverse=True
        )
        # 제목 필터를 슬라이스보다 먼저 — 상위 5건 중 무제목이 있어도 5건을 채운다
        # (로더가 무제목 기사를 이미 걸러 실제로는 방어적 정리다. PR #67 리뷰 3)
        titled = [it for it, _ in ranked if it.get("title")]
        key_events = [
            KeyEvent(event=str(it.get("title", "")), news_ids=[str(it.get("news_id", ""))])
            for it in titled[:5]
        ]
        event_backend = "rule"

    prior = state.get("prior_news") or []
    stale = staleness.staleness_score(texts, [_text_of(p) for p in prior])

    result = NewsAnalysis(
        news_sentiment=mean,
        news_impact_score=impact,
        news_sentiment_std=std,
        key_events=key_events,
        article_count=len(texts),
        article_count_raw=raw_count,
        article_count_dropped=dropped,
        staleness=stale,
        backend=backend,
        event_backend=event_backend,
        reasoning=(
            f"수집 {raw_count}건 중 관련 {len(texts)}건 분석"
            f"(감성 {mean:+.2f}, 분산 {std:.2f}, 신선도 {1 - stale:.2f}, 백엔드 {backend})."
        ),
    )
    return {"news_result": result.model_dump()}


# 이벤트-기사 연결 최소 토큰 겹침. 1이면 '삼성전자' 하나만 겹쳐도 매칭돼
# 사실상 모든 기사가 후보가 된다(실측: 이벤트 1개가 73건 중 38건과 1토큰 겹침 →
# 2 이상은 13건). 회사명 하나로 엉뚱한 기사를 출처로 다는 것을 막는다.
_MIN_GROUNDING_OVERLAP = 2


def _ground_event(event: str, items: list[dict]) -> KeyEvent:
    """LLM이 쓴 이벤트 문구를 실제 기사에 연결해 출처 news_id를 붙인다.

    토큰 겹침이 _MIN_GROUNDING_OVERLAP 이상인 기사만 후보로 본다. 하나도 없으면
    news_ids=[] → validation_agent가 '출처 없는 이벤트'로 잡아낸다(환각 탐지).
    """
    ev_tokens = staleness.tokenize(event)
    if not ev_tokens:
        return KeyEvent(event=event, news_ids=[])
    scored = []
    for it in items:
        overlap = len(ev_tokens & staleness.tokenize(_text_of(it)))
        if overlap >= _MIN_GROUNDING_OVERLAP:
            scored.append((overlap, str(it.get("news_id", ""))))
    scored.sort(reverse=True)
    return KeyEvent(event=event, news_ids=[nid for _, nid in scored[:2] if nid])


# ── Financial Agent ────────────────────────────────────────────
def financial_agent(state: dict) -> dict:
    f = state.get("raw_financials") or {}
    m = metrics.compute_metrics(f)
    health = metrics.health_score(m)
    valuation = metrics.valuation_score(m, f.get("sector_per"), f.get("sector_pbr"))

    def fmt(x, pct=False):
        if x is None:
            return "N/A"
        return f"{x * 100:.1f}%" if pct else f"{x:.2f}"

    reasoning = (
        f"PER {fmt(m['per'])}, PBR {fmt(m['pbr'])}, ROE {fmt(m['roe'], pct=True)}, "
        f"부채비율 {fmt(m['debt_ratio'])}배, 매출성장 {fmt(m['revenue_growth'], pct=True)} "
        f"→ 건전성 {health}/10, 밸류 {valuation}/10."
    )

    result = FinancialAnalysis(
        financial_health_score=health,
        valuation_score=valuation,
        metrics=FinancialMetrics(**m),
        fiscal_year=f.get("fiscal_year"),
        source=state.get("financial_source", "sample"),
        reasoning=reasoning,
    )
    return {"financial_result": result.model_dump()}


# ── Validation Agent (규칙 기반, 결정론) ────────────────────────
_PLAUSIBLE = {  # 지표별 상식 범위 — 벗어나면 단위/매핑 오류 의심
    # 하한이 중요하다: 발행주식수가 과소하면 EPS가 폭증해 PER이 0에 수렴한다.
    # 단위 오류는 지표를 크게 만드는 만큼 작게도 만든다.
    # 하한 근거: '수정주가 × 분할 전 주식수' 사고(삼성 50:1 → per 0.28, pbr 0.03이
    # 옛 하한 0.1/0.005를 통과해 ok=true로 새어나간 실사고)를 잡도록 올렸다.
    # 실존 극단값(경기순환주 PER ~1, 심저평가주 PBR ~0.15)보다는 낮게 유지한다.
    "per": (0.5, 500.0),
    "pbr": (0.1, 100.0),
    "roe": (-1.0, 2.0),
    "debt_ratio": (0.0, 50.0),
    "altman_z": (-5.0, 30.0),
    "revenue_growth": (-1.0, 10.0),
}

# 한국 상장사 시가총액 상식 범위 (원). 발행주식수·주가 단위 오류를 잡는다.
_MKTCAP_RANGE = (1e9, 1e16)


def validation_agent(state: dict) -> dict:
    """앞 단계 두 에이전트의 산출물이 실제로 정합적인지 규칙으로 검증한다.

    _DART_MAP은 best-effort 매핑이고 DART는 회사마다 계정 구조가 달라, 매핑이
    조용히 실패해도 지표는 '그럴듯한 float'로 남는다. 항등식 검사만이 그걸 잡는다.
    """
    errors: list[str] = []
    warns: list[str] = []

    news = state.get("news_result") or {}
    fin = state.get("financial_result") or {}
    f = state.get("raw_financials") or {}
    m = fin.get("metrics") or {}

    # 1) 회계 항등식: 자산총계 = 부채총계 + 자본총계
    ta, tl, eq = f.get("total_assets"), f.get("total_liabilities"), f.get("total_equity")
    if ta and tl and eq:
        gap = abs(ta - (tl + eq)) / ta
        if gap > 0.005:
            errors.append(
                f"회계 항등식 위배: 자산({ta:,.0f}) != 부채+자본({tl + eq:,.0f}), "
                f"괴리 {gap:.2%} → 연결/별도 재무제표 혼입 의심"
            )
    else:
        warns.append("재무상태표 3항목(자산/부채/자본) 중 결측 있음 → 항등식 검증 불가")

    # 2) 시가총액 상식 범위.
    # per×eps≈price 같은 검사는 동어반복이다 — compute_metrics가 per=price/eps로
    # 계산하므로 항상 참이다. 대신 독립 입력(주가·발행주식수)의 곱이 상식적인지 본다.
    price, sh = f.get("price"), f.get("shares_outstanding")
    if price and sh:
        mktcap = price * sh
        lo, hi = _MKTCAP_RANGE
        if not (lo <= mktcap <= hi):
            errors.append(
                f"시가총액 {mktcap:,.0f}원이 상식 범위 밖 "
                f"(주가 {price:,.0f} × 주식수 {sh:,.0f}) → 단위 오류 의심"
            )
    if m.get("per") is None and (sh is None or price is None):
        warns.append("발행주식수 또는 주가 결측 → per/pbr/altman_z 계산 불가")

    # 3) 지표 상식 범위 (_band는 조용히 saturate하므로 여기서 잡아야 한다)
    for k, (lo, hi) in _PLAUSIBLE.items():
        v = m.get(k)
        if v is not None and not (lo <= v <= hi):
            errors.append(f"{k}={v:.4g} 이 상식 범위 [{lo}, {hi}] 밖 → 단위 오류 의심")

    # 4) 파생 항목 정합성
    #
    # '이익잉여금 ≤ 자본총계'는 넣지 않는다 — 회계 항등식이 아니다.
    # 자본총계 = 자본금 + 이익잉여금 + 기타포괄손익 − 자기주식이라, 자기주식을
    # 많이 보유한 회사는 이익잉여금이 자본총계를 넘는 것이 정상이다
    # (실측: 네이버 FY2022 이익잉여금 23.65조 > 자본총계 23.45조, 자산=부채+자본
    # 항등식은 0.0000% 오차로 성립. 이 잘못된 규칙이 멀쩡한 731행을 폐기했다).
    # 매핑 오류 탐지는 자산총계 상한(아래)과 항등식 검사(1번)가 담당한다.
    for a, b, label in [
        ("current_assets", "total_assets", "유동자산 ≤ 자산총계"),
        ("current_liabilities", "total_liabilities", "유동부채 ≤ 부채총계"),
        ("retained_earnings", "total_assets", "이익잉여금 ≤ 자산총계"),
    ]:
        x, y = f.get(a), f.get(b)
        if x is not None and y is not None and x > y * 1.005:
            errors.append(f"{label} 위배: {a}={x:,.0f} > {b}={y:,.0f}")

    # 5) 뉴스 날짜 정렬 (point-in-time)
    date = state.get("date")
    bad = [
        str(it.get("date"))
        for it in (state.get("raw_news") or [])
        if str(it.get("date", "")) != date
    ]
    if bad:
        errors.append(f"기준일({date})이 아닌 기사 {len(bad)}건 혼입: {sorted(set(bad))[:3]}")

    # 6) point-in-time 재무: 기준일보다 미래 회계연도를 쓰면 룩어헤드
    fy = fin.get("fiscal_year")
    if fy is not None and date:
        expected = int(date[:4]) - 1 if date[5:10] >= "04-01" else int(date[:4]) - 2
        if fy > expected:
            errors.append(
                f"룩어헤드: FY{fy} 재무를 {date} 피처에 사용 (기대 FY{expected}) "
                f"→ 미래 정보 유출"
            )

    # 7) 결측 vs 0 구분
    if news.get("article_count", 0) == 0:
        raw = news.get("article_count_raw", 0)
        errors.append(
            f"관련 기사 0건(수집 {raw}건) → news_sentiment=0.0은 '중립'이 아니라 '무데이터'. "
            f"{'관련성 필터가 전부 걸렀음 — 회사명 키워드 확인 필요' if raw else '그날 기사 자체가 없음'}"
        )
    if all(m.get(k) is None for k in _PLAUSIBLE):
        errors.append("재무 지표가 전부 결측 → 점수가 기본값으로 채워짐")

    # 8) 이벤트 그라운딩: 출처 기사가 없는 이벤트 = 환각 의심
    ungrounded = [e.get("event") for e in (news.get("key_events") or []) if not e.get("news_ids")]
    if ungrounded:
        warns.append(f"출처 기사를 찾지 못한 이벤트 {len(ungrounded)}건: {ungrounded[:2]}")

    # 9) 관련성 필터가 너무 많이 걸러냈는지
    raw, kept = news.get("article_count_raw", 0), news.get("article_count", 0)
    if raw and kept / raw < 0.1:
        warns.append(f"관련성 필터가 {raw}건 중 {kept}건만 남김({kept / raw:.0%}) → 과대 필터 의심")

    # 10) 상한에 걸려 관련 기사가 버려졌는지 (조용한 유실 금지).
    # 어느 기사를 버릴지가 임의 선택이라, 관련성 필터로 없앤 노이즈가 되살아난다.
    dropped = news.get("article_count_dropped", 0)
    if dropped:
        warns.append(
            f"관련 기사 {dropped}건이 상한({SETTINGS.max_daily_articles})에 걸려 "
            f"임의로 버려짐 → max_daily_articles 상향 검토"
        )

    result = ValidationResult(ok=not errors, errors=errors, warnings=warns)
    return {"validation": result.model_dump()}


# ── Synthesis Agent ────────────────────────────────────────────
_SIGNAL_BANDS = [(8.0, "STRONG_BUY"), (6.5, "BUY"), (4.5, "HOLD"), (3.0, "SELL")]


def _to_signal(composite: float) -> str:
    for thr, sig in _SIGNAL_BANDS:
        if composite >= thr:
            return sig
    return "STRONG_SELL"


def synthesis_agent(state: dict) -> dict:
    news = state.get("news_result") or {}
    fin = state.get("financial_result") or {}
    valid = state.get("validation") or {}

    valuation = fin.get("valuation_score", 5.0)
    health = fin.get("financial_health_score", 5.0)
    news_sent = news.get("news_sentiment", 0.0)
    impact = news.get("news_impact_score", 5)

    # 펀더멘털(가치투자 핵심) + 뉴스 감성 보정 — 공식은 synthesize_scores 한 곳에만.
    # 실데이터 소스는 뉴스·재무 2개뿐이라 base/계수가 2소스 기준으로 잡혀 있다.
    real_sources = sum(
        1
        for s in (state.get("news_source"), state.get("financial_source"))
        if s and s != "sample"
    )
    composite, signal, confidence = synthesize_scores(
        valuation, health, news_sent, impact,
        news.get("news_sentiment_std", 0.0), real_sources,
    )

    # 근거: LLM 있으면 생성, 없으면 템플릿
    events = [e.get("event", "") for e in (news.get("key_events") or [])][:4]
    reason_obj = structured(
        f"종목 {state.get('ticker')} 가치투자 분석 결과:\n"
        f"- 밸류에이션 {valuation}/10, 재무건전성 {health}/10\n"
        f"- 뉴스감성 {news_sent:+.2f}(영향력 {impact}/10)\n"
        f"- 종합점수 {composite:.2f}/10 → 시그널 {signal}\n"
        f"핵심이벤트: {', '.join(events)}\n"
        "위 수치와 핵심 이벤트의 관계만 2~3문장으로 설명하라. "
        "매수·매도·보유·관망·진입·청산·비중·손절·익절 등 독자의 행동을 "
        "권하거나 제안하지 말고, 시그널을 행동 지시로 풀어 쓰지 마라.",
        _Reason,
    )
    candidate_reasoning = reason_obj.reasoning.strip() if reason_obj is not None else ""
    if candidate_reasoning and not _contains_behavior_advice(candidate_reasoning):
        reasoning = candidate_reasoning
    else:
        reasoning = (
            f"밸류에이션 {valuation}/10·재무건전성 {health}/10에 뉴스감성 {news_sent:+.2f}"
            f"(영향력 {impact}/10)를 반영한 종합점수는 {composite:.1f}/10이며, "
            f"결정론적 구간 라벨은 '{signal}'이다."
        )

    out = ValueSignal(
        ticker=state["ticker"],
        date=state["date"],
        company_name=state.get("company_name", ""),
        news_sentiment=news_sent,
        news_impact_score=impact,
        news_sentiment_std=news.get("news_sentiment_std", 0.0),
        news_staleness=news.get("staleness", 0.0),
        key_events=[KeyEvent(**e) for e in (news.get("key_events") or [])],
        article_count=news.get("article_count", 0),
        article_count_raw=news.get("article_count_raw", 0),
        financial_health_score=health,
        valuation_score=valuation,
        financial_metrics=FinancialMetrics(**fin.get("metrics", {})),
        financial_fiscal_year=fin.get("fiscal_year"),
        composite_score=round(composite, 3),
        value_investment_signal=signal,
        confidence=confidence,
        reasoning=reasoning,
        news_source=state.get("news_source", ""),
        financial_source=state.get("financial_source", ""),
        validation=ValidationResult(**valid) if valid else ValidationResult(),
    )
    return {"final": out.model_dump()}
