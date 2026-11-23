"""기간(월/년) 요약 파이프라인 — (ticker, period)에 대해 기간 전체를 요약한 한 건을 만든다.

- 뉴스: 기간 감성은 '관련 기사 전체'의 기사 단위 평균(= 기사수 가중)이다.
  기간 모드는 빅카인즈 엑셀 전용이다. 네이버 폴백은 과거 날짜 조회가 불가능하고, 기간 중
  일부만 다른 소스로 채우면 기간 간 피처가 비교 불가능해지기 때문이다.
- 재무: '기간 종료일' 기준 point-in-time — 종료일에 이미 공시된 사업보고서만 쓴다.
- LLM은 기간 경로에서 호출하지 않는다 — 핵심 이벤트도 감성 절댓값 상위 헤드라인으로 뽑는다.
"""
from __future__ import annotations

import calendar
import datetime as dt
import re

from . import collectors, staleness
from .agents import (
    _text_of,
    financial_agent,
    impact_score,
    relevant_indices,
    synthesize_scores,
    validation_agent,
)
from .config import SETTINGS
from .schema import (
    DailyNewsMetrics,
    FinancialMetrics,
    KeyEvent,
    PeriodValueSignal,
    ValidationResult,
)
from .sentiment import aggregate, score_texts

_PERIOD_RE = re.compile(r"(\d{4})(?:-(\d{2}))?")


def parse_period(period: str) -> tuple[str, str]:
    """'YYYY'(1년) 또는 'YYYY-MM'(1개월) → (시작일, 종료일) ISO 문자열."""
    m = _PERIOD_RE.fullmatch((period or "").strip())
    if not m:
        raise ValueError(f"기간 형식은 YYYY 또는 YYYY-MM 입니다: {period!r}")
    year = int(m.group(1))
    if m.group(2) is None:
        return f"{year:04d}-01-01", f"{year:04d}-12-31"
    month = int(m.group(2))
    if not 1 <= month <= 12:
        raise ValueError(f"월은 01~12 입니다: {period!r}")
    last = calendar.monthrange(year, month)[1]
    return f"{year:04d}-{month:02d}-01", f"{year:04d}-{month:02d}-{last:02d}"


def run_period_pipeline(ticker: str, period: str, company_name: str = "") -> dict:
    """기간 요약 실행 → PeriodValueSignal dict 반환.

    재무를 못 구하면 일별과 동일하게 FinancialsUnavailableError로 중단한다.
    """
    start, end = parse_period(period)

    fin, fin_src = collectors.collect_financials(ticker, end)
    name = company_name or fin.get("company_name") or ticker
    fin_result = financial_agent(
        {"raw_financials": fin, "financial_source": fin_src}
    )["financial_result"]

    # staleness 비교 풀: 기간 시작 직전 기사에서 출발해 기간 안에서 하루씩 굴린다.
    # 일별 파이프라인과 같은 기준 — 비교 대상은 관련성 필터 전 '전체' 직전 기사다.
    prior_texts = [
        _text_of(p)
        for p in collectors.collect_prior_news(
            ticker, name, start, SETTINGS.staleness_lookback_articles
        )
    ]

    daily: list[DailyNewsMetrics] = []
    scored_items: list[tuple[float, dict]] = []
    days_covered = 0
    total_raw = 0
    total_dropped = 0

    day = dt.date.fromisoformat(start)
    end_day = dt.date.fromisoformat(end)
    while day <= end_day:
        d = day.isoformat()
        day += dt.timedelta(days=1)

        workbook = collectors.preprocess.find_news_workbook(
            name, d, collectors.DATA_DIR, ticker
        )
        if workbook is None:
            # 워크북이 없는 날은 '기사 0건'이 아니라 '관측하지 않음'이다 — daily_metrics에
            # 0건으로 넣으면 수집 누락이 조용한 날로 학습된다.
            continue
        days_covered += 1
        items = collectors.preprocess.load_daily_news(
            name, d, collectors.DATA_DIR, limit=None, ticker=ticker
        )
        total_raw += len(items)

        keep = relevant_indices(items, name)
        relevant_all = [items[i] for i in keep]
        relevant = relevant_all[: SETTINGS.max_daily_articles]
        total_dropped += len(relevant_all) - len(relevant)

        texts = [_text_of(it) for it in relevant]
        scores, _backend = score_texts(texts)
        mean, std = aggregate(scores)
        stale = staleness.staleness_score(texts, prior_texts)
        # 길이 불일치는 텍스트 구성 계약 위반 — 조용히 잘리는 대신 그날 에러로 드러낸다
        scored_items.extend(zip(scores, relevant, strict=True))

        daily.append(
            DailyNewsMetrics(
                date=d,
                article_count=len(texts),
                article_count_raw=len(items),
                news_sentiment=mean,
                news_sentiment_std=std,
                news_impact_score=impact_score(len(texts), mean),
                staleness=stale,
            )
        )

        # 직전 기사 풀 갱신: 그날 전체 기사를 발행 시각 역순으로 앞에 붙이고
        # 최신 N건만 유지한다 (collect_prior_news의 '직전 N건'과 동일 의미).
        newest_first = sorted(items, key=collectors._published_at, reverse=True)
        prior_texts = [_text_of(it) for it in newest_first] + prior_texts
        del prior_texts[SETTINGS.staleness_lookback_articles :]

    all_scores = [s for s, _ in scored_items]
    p_mean, p_std = aggregate(all_scores)
    active = [dm for dm in daily if dm.article_count > 0]
    p_impact = (
        round(sum(dm.news_impact_score for dm in active) / len(active)) if active else 5
    )
    p_stale = (
        round(sum(dm.staleness for dm in active) / len(active), 4) if active else 0.0
    )

    # 제목 필터를 슬라이스보다 먼저 적용해 5건을 채운다.
    ranked = sorted(scored_items, key=lambda x: abs(x[0]), reverse=True)
    titled = [it for _, it in ranked if it.get("title")]
    key_events = [
        KeyEvent(event=str(it.get("title", "")), news_ids=[str(it.get("news_id", ""))])
        for it in titled[:5]
    ]

    valuation = fin_result["valuation_score"]
    health = fin_result["financial_health_score"]
    news_source = "bigkinds" if days_covered else "none"
    real_sources = sum(1 for s in (news_source, fin_src) if s not in ("sample", "none"))
    composite, signal, confidence = synthesize_scores(
        valuation, health, p_mean, p_impact, p_std, real_sources
    )

    # 일별 validation_agent의 재무·건수 규칙을 그대로 재사용하고,
    #    기간 고유 항목(워크북 커버리지)만 추가한다. date=기간 종료일이므로
    #    룩어헤드 검사도 point-in-time 기준과 일치한다.
    v_state = {
        "date": end,
        "ticker": ticker,
        "raw_news": [],
        "news_result": {
            "article_count": len(all_scores),
            "article_count_raw": total_raw,
            "article_count_dropped": total_dropped,
            "key_events": [e.model_dump() for e in key_events],
        },
        "financial_result": fin_result,
        "raw_financials": fin,
    }
    validation = validation_agent(v_state)["validation"]
    period_days = (end_day - dt.date.fromisoformat(start)).days + 1
    if days_covered == 0:
        validation["errors"].append(
            f"{start}~{end}를 커버하는 빅카인즈 워크북이 없음 → 뉴스 축 전체 무데이터. "
            f"기대 위치: {collectors.DATA_DIR}/{ticker}/{{회사명}}_{{YYYYMMDD}}-{{YYYYMMDD}}.xlsx"
        )
        validation["ok"] = False
    elif days_covered < period_days:
        # 부분 커버리지는 비율·일평균 피처의 분모를 오염시킨다 → 학습에서 제외(invalid).
        # '관련 기사 0건' 문구를 쓰지 않으므로 features.row_status가 결측으로 살리지 않는다.
        validation["errors"].append(
            f"기간 {period_days}일 중 {days_covered}일만 워크북이 커버 → 부분 커버리지. "
            "비관측일을 기사 0건으로 볼 수 없어 학습에서 제외"
        )
        validation["ok"] = False

    # 재무 나이(개월): 기간 종료월 − 사업연도 종료월. select_fiscal_year와 같은
    # 12월 결산 가정 — FY(y) 재무의 회계 정보는 y년 12월 말 기준이다.
    fy = fin_result.get("fiscal_year")
    financial_age_months = (
        (end_day.year - int(fy)) * 12 + end_day.month - 12 if fy is not None else None
    )

    reasoning = (
        f"{start}~{end} 관련 기사 {len(all_scores)}건(수집 {total_raw}건, 기사 있는 날 "
        f"{len(active)}/{period_days}일)의 기간 감성 {p_mean:+.2f}(분산 {p_std:.2f})과 "
        f"기간 종료일 기준 FY{fin_result.get('fiscal_year')} 재무(밸류에이션 {valuation}/10, "
        f"건전성 {health}/10)를 반영한 종합점수는 {composite:.1f}/10이며, "
        f"결정론적 구간 라벨은 '{signal}'이다."
    )

    out = PeriodValueSignal(
        ticker=ticker,
        period=(period or "").strip(),
        period_start=start,
        period_end=end,
        company_name=name,
        news_sentiment=p_mean,
        news_impact_score=p_impact,
        news_sentiment_std=p_std,
        news_staleness=p_stale,
        key_events=key_events,
        article_count=len(all_scores),
        article_count_raw=total_raw,
        avg_daily_articles=round(len(all_scores) / period_days, 4) if period_days else 0.0,
        period_days=period_days,
        days_with_articles=len(active),
        days_covered=days_covered,
        financial_health_score=health,
        valuation_score=valuation,
        financial_metrics=FinancialMetrics(**fin_result.get("metrics", {})),
        financial_fiscal_year=fy,
        financial_age_months=financial_age_months,
        composite_score=round(composite, 3),
        value_investment_signal=signal,
        confidence=confidence,
        reasoning=reasoning,
        news_source=news_source,
        financial_source=fin_src,
        validation=ValidationResult(**validation),
        daily_metrics=daily,
    )
    return out.model_dump()
