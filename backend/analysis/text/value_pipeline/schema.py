"""출력/중간 데이터 스키마 (Pydantic v2).

출력 행 안의 모든 숫자를 그 행만 보고 재계산할 수 있어야 한다:

    composite  = clip(valuation_score*0.6 + financial_health_score*0.4
                      + news_sentiment*(news_impact_score/10)*2, 0, 10)
    signal     = band(composite)
    confidence = clip(0.5 + 0.125*real_sources - 0.15*news_sentiment_std
                      + 0.2*|composite-5|/5, 0.2, 0.95)

news_impact_score를 노출하는 이유가 이것이다 — composite 공식의 1급 항이라
빼면 재계산이 불가능해진다. article_count는 결측 지시자다: news_sentiment=0.0은
'기사 없음'과 '중립 기사' 둘 다이며 std도 양쪽 0.0이라 구분할 방법이 이것뿐이다.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

Signal = Literal["STRONG_BUY", "BUY", "HOLD", "SELL", "STRONG_SELL"]


class FinancialMetrics(BaseModel):
    """모델 입력용 '비중복' 핵심 재무 지표 (차원당 대표 1개).

    PER·PBR·PSR·PEG·EV/EBITDA(밸류에이션), ROE·ROA·마진(수익성),
    유동/당좌비율·이자보상배율(유동성) 등은 서로 강하게 상관(다중공선성)되어
    중복 지표를 제거하고 각 축의 대표값만 노출한다. 제거된 지표들의 정보는
    financial_health_score / valuation_score 두 종합점수에 이미 반영되어 있다.
    값이 없으면 None(결측).
    """

    per: float | None = None
    pbr: float | None = None
    roe: float | None = None
    revenue_growth: float | None = None   # 성장성 대표: 매출 증가율(전년 대비)
    debt_ratio: float | None = None       # 안정성 대표: 부채총계/자본총계 (배)
    altman_z: float | None = None


class KeyEvent(BaseModel):
    event: str
    news_ids: list[str] = Field(default_factory=list)


class NewsAnalysis(BaseModel):
    news_sentiment: float = Field(0.0, ge=-1, le=1)
    news_impact_score: int = Field(5, ge=1, le=10)    # 주가 영향력(부정이어도 클 수 있음)
    news_sentiment_std: float = Field(0.0, ge=0)
    key_events: list[KeyEvent] = Field(default_factory=list)
    article_count: int = 0                            # 관련성 필터 통과 기사 수
    article_count_raw: int = 0                        # 필터 전 그날 전체 기사 수
    article_count_dropped: int = 0                    # 상한에 걸려 버려진 관련 기사 수
    staleness: float = Field(0.0, ge=0, le=1)         # 직전 기사와의 중복률(Tetlock)
    backend: str = "none"  # 감성 산출 백엔드(kr-finbert / lexicon)
    event_backend: str = "none"  # 핵심 이벤트 추출 백엔드(llm / rule) — 설명 전용
    reasoning: str = ""


class FinancialAnalysis(BaseModel):
    financial_health_score: float = Field(5.0, ge=0, le=10)
    valuation_score: float = Field(5.0, ge=0, le=10)         # 저평가 정도
    metrics: FinancialMetrics = Field(default_factory=FinancialMetrics)
    fiscal_year: int | None = None
    source: str = "sample"  # dart / sample
    reasoning: str = ""


class ValidationResult(BaseModel):
    """규칙 기반 검증 결과 (LLM 아님 — 결정론).

    LLM 크리틱을 쓰지 않는 이유: 외부 피드백 없는 자기검증은 실증적으로
    성능을 떨어뜨린다(Huang et al., ICLR 2024 — CommonSenseQA 75.8→41.8).
    자기교정이 작동하는 경우는 도구·규칙·검증기 같은 '외부 피드백'뿐이다.
    """

    ok: bool = True
    errors: list[str] = Field(default_factory=list)    # 출력을 신뢰할 수 없음
    warnings: list[str] = Field(default_factory=list)  # 주의가 필요하나 치명적이진 않음


class ValueSignal(BaseModel):
    """최종 출력 — 다운스트림 모델용 가치투자 피처 한 줄(=하루치)."""

    ticker: str
    date: str
    company_name: str = ""

    news_sentiment: float = 0.0
    news_impact_score: int = 5
    news_sentiment_std: float = 0.0
    news_staleness: float = 0.0          # 0=새 정보, 1=직전 기사 재탕 (Tetlock 2011)
    key_events: list[KeyEvent] = Field(default_factory=list)
    article_count: int = 0               # 관련성 통과 기사 수 (결측 지시자)
    article_count_raw: int = 0           # 필터 전 전체 기사 수

    financial_health_score: float = 5.0
    valuation_score: float = 5.0
    financial_metrics: FinancialMetrics = Field(default_factory=FinancialMetrics)
    financial_fiscal_year: int | None = None

    composite_score: float = Field(5.0, ge=0, le=10)  # 시그널을 결정하는 실제 점수
    value_investment_signal: Signal = "HOLD"
    confidence: float = Field(0.5, ge=0, le=1)
    reasoning: str = ""

    news_source: str = ""       # bigkinds / naver_api / naver / sample
    financial_source: str = ""  # dart / sample

    validation: ValidationResult = Field(default_factory=ValidationResult)


class DailyNewsMetrics(BaseModel):
    """기간 요약 출력 내부의 일별 감사 행.

    기간 집계(감성·분산·영향력·신선도)를 이 행들만으로 재계산할 수 있어야 한다
    — 기간 출력의 self-auditing 은 이 리스트가 담보한다.
    """

    date: str
    article_count: int = 0        # 관련성 통과 기사 수
    article_count_raw: int = 0    # 필터 전 그날 전체 기사 수
    news_sentiment: float = 0.0
    news_sentiment_std: float = 0.0
    news_impact_score: int = 5
    staleness: float = Field(0.0, ge=0, le=1)


class PeriodValueSignal(BaseModel):
    """기간(월/년) 요약 출력 — 다운스트림 모델용 기간 피처 1건.

    ValueSignal(일별 1행)과 피처 축·점수 공식을 공유하되 집계 단위만 기간이다.
    - 뉴스: 기간 내 '관련 기사 전체'의 기사 단위 평균/분산(= 기사수 가중).
      영향력·신선도는 기사 있는 날들의 일별 값 평균.
    - 재무: '기간 종료일' 기준 point-in-time — 종료일에 이미 공시된 사업보고서만 사용.
    - composite/signal/confidence: ValueSignal 도크스트링의 공식과 동일.
    days_covered 는 결측 지시자다: 워크북이 기간을 아예 못 덮으면(0) 뉴스 축 전체가
    무데이터이며, article_count=0 과 함께 validation 에러로 드러난다.
    """

    ticker: str
    period: str          # 입력 그대로: 'YYYY' 또는 'YYYY-MM'
    period_start: str
    period_end: str
    company_name: str = ""

    news_sentiment: float = 0.0
    news_impact_score: int = 5
    news_sentiment_std: float = 0.0
    news_staleness: float = 0.0
    key_events: list[KeyEvent] = Field(default_factory=list)  # 감성 절댓값 상위 (규칙)
    article_count: int = 0        # 기간 내 관련성 통과 기사 총수
    article_count_raw: int = 0    # 기간 내 필터 전 전체 기사 총수
    avg_daily_articles: float = 0.0  # 관련 기사 일평균 — 월 길이·종목 노출량 정규화
    period_days: int = 0
    days_with_articles: int = 0   # 관련 기사가 1건 이상인 날 수
    days_covered: int = 0         # 워크북이 커버한 날 수 (결측 지시자)

    financial_health_score: float = 5.0
    valuation_score: float = 5.0
    financial_metrics: FinancialMetrics = Field(default_factory=FinancialMetrics)
    financial_fiscal_year: int | None = None
    # 재무 나이(개월): 기간 종료월 − 사업연도 종료월(12월 결산 가정).
    # 같은 FY2020 재무라도 2021-01엔 1개월, 2022-01엔 13개월 묵은 정보다 —
    # 이 신선도 차이가 모델이 쓸 수 있는 신호라 연도 대신 나이로 노출한다.
    financial_age_months: int | None = None

    composite_score: float = Field(5.0, ge=0, le=10)
    value_investment_signal: Signal = "HOLD"
    confidence: float = Field(0.5, ge=0, le=1)
    reasoning: str = ""

    news_source: str = ""       # bigkinds / none
    financial_source: str = ""  # dart / sample

    validation: ValidationResult = Field(default_factory=ValidationResult)
    daily_metrics: list[DailyNewsMetrics] = Field(default_factory=list)
