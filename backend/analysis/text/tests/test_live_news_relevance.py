from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest
from analysis.text.value_pipeline import news_tracks


def _item(news_id: str, title: str, summary: str) -> dict:
    return {
        "news_id": news_id, "title": title, "summary": summary,
        "published_at": "2026-10-13T05:00:00Z", "date": "2026-10-13",
        "url": f"https://example.com/{news_id}", "press": "example.com",
    }


def _scores(texts: list[str], **kwargs: object) -> tuple[list[float], str]:
    # The external model is replaced; filtering and aggregation run unchanged.
    return [0.2 if "투싼" in text else 0.99 for text in texts], "kr-finbert"


def test_live_sentiment_does_not_transfer_other_company_or_incidental_good_news(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(news_tracks.sentiment, "score_texts", _scores)
    items = [
        _item("direct", "현대차, 신형 투싼 공개", "유럽 시장 공략을 강화한다."),
        _item("lg", "LG에너지솔루션, 나홀로 상승", "현대차(-5.0%) 등 시총 상위주는 하락했다."),
        _item("food", "세계 1위 오른 한국 치킨", "현대차 정의선 회장은 치맥 회동에 참석했다."),
        _item("ai", "에이아이웍스, 매출 62% 성장", "대표는 현대차 정몽구 재단 행사에 참석한다."),
        _item("market", "코스피 6000선 붕괴", "현대차(-5.0%), 삼성전자(-8.0%)가 하락했다."),
        _item("rotem", "현대로템 목표주가 하향", "수주 시점이 불확실하다. 관련기사 현대차 스마트팩토리 기술 도입"),
    ]
    result = news_tracks.build_live_track(
        items, "005380", "현대차",
        as_of=datetime(2026, 10, 13, 15, 0, tzinfo=ZoneInfo("Asia/Seoul")),
    )
    assert [row["news_id"] for row in result["articles"]] == ["direct", "market"]
    assert result["window"]["sentiment_mean"] == pytest.approx((0.2 + 0.99) / 2)


def test_live_filter_keeps_business_causality_and_executive_company_news(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(news_tracks.sentiment, "score_texts", _scores)
    items = [
        _item("causal", "현대모비스 수익성 전망 하회", "현대차 파업에 따른 생산 중단으로 모듈 매출이 줄었다."),
        _item("executive", "정의선 취임 6년, 매출 300조 시대", "자동차 사업과 로봇 투자를 점검한다."),
        _item("body", "유럽 SUV 경쟁 가열", "현대자동차는 신형 투싼을 출시해 판매를 확대한다."),
    ]
    result = news_tracks.build_live_track(
        items, "005380", "현대차",
        as_of=datetime(2026, 10, 13, 15, 0, tzinfo=ZoneInfo("Asia/Seoul")),
    )
    assert [row["news_id"] for row in result["articles"]] == ["causal", "executive", "body"]


@pytest.mark.parametrize("title, summary, expected", [
    ("시장분석: 외국인 매도세가 시장 하락 견인", "현대차 판매 둔화 우려가 언급됐다.", "market"),
    ("오늘 신문 1면: 식품 안전과 반도체 경쟁", "현대차는 일본 판매를 확대한다.", "review"),
    ("이노션, 브랜드 영화 사업 확대", "현대차와 이노션이 공동 기획한 영화의 성과를 소개했다.", "indirect"),
    ("국내 수입차 시장 경쟁 격화", "BYD 가격은 현대차 캐스퍼 기본 가격보다 낮다.", "direct"),
    ("현대차 주가, 코스피 급락에도 선방", "현대차의 판매 증가가 주목받았다.", "direct"),
    ("EV 주행거리 늘리는 방법", "쉐보레, 현대차, 벤츠 앱에서 에너지 사용량을 확인한다.", "review"),
    ("현대로템 목표가 하향", "관련기사 현대차 스마트팩토리 공급 계약", "irrelevant"),
])
def test_context_filter_preserves_specific_business_and_separates_roundups(
    title: str, summary: str, expected: str,
) -> None:
    from analysis.text.value_pipeline.news_relevance import classify_live_relevance

    result = classify_live_relevance(_item("sample", title, summary), "현대차")
    assert result.category == expected


@pytest.mark.parametrize("title, summary, expected", [
    ("현대차증권 목표주가 상향, 실적 개선", "현대차증권은 순이익이 늘었다.", "irrelevant"),
    ("삼성전자 실적 개선", "삼성전자는 공급계약을 체결했고 현대차 주가는 하락했다.", "irrelevant"),
    ("현대로템 목표주가 하향", "수주 지연 우려가 크다. 관련기사\n현대차 스마트팩토리 공급 계약", "irrelevant"),
    ("코스피 급락에도 현대차 판매 호조", "현대차는 북미 신차 판매를 늘렸다.", "direct"),
    ("현대차, 젠슨 황과 치맥 회동 뒤 공동투자", "현대차와 엔비디아가 회동에서 로봇 공동투자를 합의했다.", "direct"),
])
def test_independent_review_counterexamples(title: str, summary: str, expected: str) -> None:
    from analysis.text.value_pipeline.news_relevance import classify_live_relevance

    result = classify_live_relevance(_item("review", title, summary), "현대차")
    assert result.category == expected


@pytest.mark.parametrize("title, summary, expected", [
    ("삼성전자 실적 개선", "현대차 주가는 하락했고 삼성전자는 공급계약을 체결했다.", "irrelevant"),
    ("유럽 SUV 경쟁 가열", "현대차는 3.5조원을 투자해 신형 투싼 생산을 확대한다.", "direct"),
    ("현대모비스 공급 계약 체결", "현대모비스는 현대차에 전동화 부품을 공급하는 계약을 체결했다.", "indirect"),
])
def test_causal_target_and_decimal_business_amounts(title: str, summary: str, expected: str) -> None:
    from analysis.text.value_pipeline.news_relevance import classify_live_relevance

    assert classify_live_relevance(_item("causal-review", title, summary), "현대차").category == expected


@pytest.mark.parametrize("ticker, company, direct_title, direct_body, collision", [
    ("005930", "삼성전자", "반도체 기술 경쟁", "Samsung Electronics는 HBM 양산을 확대한다.", "삼성전자서비스"),
    ("005380", "현대차", "유럽 자동차 경쟁", "현대자동차는 전기차를 출시한다.", "현대차증권"),
    ("035720", "카카오", "AI 서비스 경쟁", "KAKAO는 광고 플랫폼을 개편한다.", "카카오뱅크"),
    ("035420", "네이버", "AI 서비스 경쟁", "NAVER는 검색 광고 서비스를 개편한다.", "네이버웹툰"),
    ("068270", "셀트리온", "바이오 시장 경쟁", "CELLTRION은 바이오시밀러의 임상과 허가를 추진한다.", "셀트리온제약"),
    ("247540", "에코프로비엠", "배터리 소재 경쟁", "ECOPRO BM은 양극재 증설을 추진한다.", "에코프로머티리얼즈"),
])
def test_six_stock_live_rollout_keeps_business_and_market_but_excludes_affiliates(
    monkeypatch, ticker, company, direct_title, direct_body, collision,
):
    monkeypatch.setattr(news_tracks.sentiment, "score_texts", _scores)
    result = news_tracks.build_live_track([
        _item("business", direct_title, direct_body),
        _item("market", "코스피 급락, 시총 상위주 약세", f"{company} 주가는 하락했다."),
        _item("affiliate", f"{collision} 실적 개선", f"{collision}는 매출이 늘었다."),
    ], ticker, company, as_of=datetime(2026, 10, 13, 15, tzinfo=ZoneInfo("Asia/Seoul")))
    assert [row["news_id"] for row in result["articles"]] == ["business", "market"]
    assert result["window"]["article_count"] == 2


@pytest.mark.parametrize("company, title, body, expected", [
    ("삼성전자", "메모리 업계 동향", "삼성전자는 HBM 양산을 확대한다.", "direct"),
    ("카카오", "AI 서비스 경쟁", "카카오는 플랫폼을 개편한다.", "direct"),
    ("네이버", "AI 검색 경쟁", "네이버는 검색엔진을 개편한다.", "direct"),
    ("셀트리온", "바이오시밀러 경쟁", "셀트리온은 FDA 허가를 신청했다.", "direct"),
    ("에코프로비엠", "배터리 소재 경쟁", "에코프로비엠은 양극재를 증설한다.", "direct"),
    ("카카오", "카카오뱅크 영업이익 증가", "카카오뱅크 실적이 개선됐다.", "irrelevant"),
    ("네이버", "네이버웹툰 실적 개선", "네이버웹툰은 매출이 늘었다.", "irrelevant"),
    ("셀트리온", "셀트리온제약 신약 출시", "셀트리온제약은 신약을 출시했다.", "irrelevant"),
    ("삼성전자", "삼성전기 목표가 상승", "삼성전자 주가도 하락했으며 삼성전기는 공급계약을 체결했다.", "irrelevant"),
    ("네이버", "카카오 AI 투자", "카카오는 투자를 늘렸다. 네이버는 검색엔진을 개편했다.", "irrelevant"),
    ("셀트리온", "셀트리온제약 공급 계약", "셀트리온제약은 셀트리온에 의약품을 공급하는 계약을 체결했다.", "indirect"),
    ("에코프로비엠", "에코프로머티리얼즈 공급 계약", "에코프로머티리얼즈는 에코프로비엠에 전구체를 공급하는 계약을 체결했다.", "indirect"),
    ("카카오", "카카오뱅크 실적 개선", "카카오뱅크 매출 증가가 기대된다. 관련기사 카카오 AI 플랫폼 개편", "irrelevant"),
])
def test_company_specific_context_and_affiliate_boundaries(company, title, body, expected):
    from analysis.text.value_pipeline.news_relevance import classify_live_relevance

    assert classify_live_relevance(_item("six-stock", title, body), company).category == expected


@pytest.mark.parametrize("company, title, summary", [
    ("네이버", "코스피 약세, 네이버 하락·카카오 AI 호조", "네이버는 하락했고 카카오 AI 사업은 성장했다."),
    ("카카오", "코스피 약세, 카카오 하락·네이버 광고 호조", "카카오는 하락했고 네이버 광고 사업은 성장했다."),
    ("삼성전자", "코스피 약세, 삼성전자 하락·SK하이닉스 HBM 호조", "삼성전자는 하락했고 SK하이닉스 HBM 사업은 성장했다."),
])
def test_market_title_does_not_borrow_other_company_business_words(company, title, summary):
    from analysis.text.value_pipeline.news_relevance import classify_live_relevance

    assert classify_live_relevance(_item("roundup", title, summary), company).category == "market"


def test_competitor_comparison_is_not_target_business_causality():
    from analysis.text.value_pipeline.news_relevance import classify_live_relevance

    item = _item("competitor", "LG전자 AI 가전 실적 개선", "삼성전자와 LG전자는 가전 사업에서 경쟁한다.")
    assert classify_live_relevance(item, "삼성전자").category == "irrelevant"


@pytest.mark.parametrize('company,industry,competitor', [
    ('삼성전자', '반도체 업계 메모리 수요 반등', 'SK하이닉스, HBM 신제품 출시'),
    ('현대차', '자동차 산업 전반 전기차 수요 둔화', '기아, 신형 전기차 출시'),
    ('카카오', '인터넷 플랫폼 업계 광고 시장 회복', '네이버, 멤버십 출시'),
    ('네이버', '인터넷 플랫폼 산업 멤버십 경쟁 심화', '카카오, 멤버십 출시'),
    ('셀트리온', '바이오시밀러 산업 전반 허가 제도 변경', '삼성바이오로직스, 공장 증설'),
    ('에코프로비엠', '양극재 업계 전반 수요 반등', '엘앤에프, 양극재 공급 계약'),
])
def test_final_policy_industry_market_and_competitor(company, industry, competitor):
    from analysis.text.value_pipeline.news_relevance import classify_live_relevance
    sector = classify_live_relevance(_item('sector', industry, industry + ' 여러 업체가 영향을 받는다.'), company)
    assert sector.category == 'industry' and sector.included
    market = classify_live_relevance(_item('market', '7천피 붕괴, 금리 상승 부담', '시장 전체에서 외국인 매도가 늘었다.'), company)
    assert market.category == 'market' and market.included
    other = classify_live_relevance(_item('other', competitor, competitor + ' 회사의 개별 사업 소식이다.'), company)
    assert other.category == 'irrelevant' and not other.included


@pytest.mark.parametrize('title,body,category', [
    ('콘티넨탈, 네이버 스토어 이벤트', '콘티넨탈타이어가 네이버 스토어 구매자에게 혜택을 제공한다.', 'irrelevant'),
    ('카카오, 네이버와 멤버십 전면전', '카카오가 멤버십을 출시했다. 네이버와 월 구독료가 같다.', 'irrelevant'),
    ('검색 순위 왜곡 논란, 토스 리워드광고서 네이버 제외', '네이버는 검색 왜곡으로 인한 업무방해 혐의로 경찰에 수사를 의뢰했다.', 'direct'),
    ('엔비디아 AI 데이 개최, 네이버 등 20개사 참여', '엔비디아가 행사를 개최한다. 네이버클라우드 등 파트너사가 참석한다.', 'irrelevant'),
    ('패션 기업 AI 스타일링 출시', '형지엘리트가 AI를 활용해 의류를 판매한다.', 'irrelevant'),
    ('산업 소식', '', 'review'),
    ('네이버 사업 변화', '관련기사 네이버 검색 광고 개편', 'review'),
])
def test_final_policy_naver_subject_and_insufficient_input(title, body, category):
    from analysis.text.value_pipeline.news_relevance import classify_live_relevance
    assert classify_live_relevance(_item('boundary', title, body), '네이버').category == category


def test_target_action_is_not_borrowed_from_later_competitor_clause():
    from analysis.text.value_pipeline.news_relevance import classify_live_relevance
    item = _item('split', '카카오와 네이버 주가 비교', '네이버는 하락했고 카카오는 광고 서비스를 개편했다.')
    assert not classify_live_relevance(item, '네이버').included


def test_unknown_named_company_product_news_is_held_instead_of_industry_keyword_pass():
    from analysis.text.value_pipeline.news_relevance import classify_live_relevance
    item = _item('unknown', '새빛자동차, 전기차 수요 증가에 신제품 출시', '새빛자동차는 신제품을 출시했다.')
    assert classify_live_relevance(item, '현대차').category == 'review'


def test_topic_only_title_with_no_target_event_is_held():
    from analysis.text.value_pipeline.news_relevance import classify_live_relevance
    assert classify_live_relevance(_item('unclear', '네이버 이야기', '행사장에서 이야기가 오갔다.'), '네이버').category == 'review'


@pytest.mark.parametrize('company,title,body,category', [
    ('네이버', '카카오, 네이버와 멤버십 전면전', '네이버는 기존 서비스를 유지하고 카카오는 멤버십을 출시했다.', 'irrelevant'),
    ('삼성전자', '반도체 업계 전반 수요 둔화, SK하이닉스도 감산', '반도체 업체 전반이 수요 둔화로 감산에 나섰다. SK하이닉스와 삼성전자가 영향을 받는다.', 'industry'),
    ('현대차', '새빛자동차 전기차 시장 공략 신차 출시', '새빛자동차는 전기차 신제품을 출시했다.', 'review'),
    ('에코프로비엠', "K양극재 캐즘 터널 끝 보인다, 탈중국 ESS 타고 실적 반등", '국내 양극재 업계가 공급망 수요와 ESS 시장 확대에 힘입어 반등하고 있다.', 'industry'),
    ('에코프로비엠', '정부가 4000억 투입, 차세대 배터리에 승부수', '산업통상부가 배터리 산업 경쟁력 강화 정책을 추진한다.', 'industry'),
])
def test_reviewed_subject_boundaries(company, title, body, category):
    from analysis.text.value_pipeline.news_relevance import classify_live_relevance
    assert classify_live_relevance(_item('reviewed', title, body), company).category == category


@pytest.mark.parametrize('company,title,body', [
    ('네이버', '카카오, 네이버와 멤버십 전면전', '네이버는 카카오가 출시한 멤버십과 경쟁한다.'),
    ('삼성전자', 'SK하이닉스, HBM 공급계약 체결', '삼성전자와 경쟁하는 SK하이닉스는 HBM 공급계약을 체결했다.'),
])
def test_subordinate_competitor_actions_are_not_joint_target_events(company, title, body):
    from analysis.text.value_pipeline.news_relevance import classify_live_relevance
    assert not classify_live_relevance(_item('subordinate', title, body), company).included


def test_live_diagnostics_exposes_category_means_without_changing_track(monkeypatch, caplog):
    import json
    monkeypatch.setattr(news_tracks.sentiment, 'score_texts', lambda texts, **kwargs: ([-0.9, 0.3, 0.5], 'kr-finbert'))
    with caplog.at_level('INFO', logger=news_tracks.__name__):
        track = news_tracks.build_live_track([
            _item('company', '네이버 실적 하락', '네이버 영업이익이 줄었다.'),
            _item('industry', '인터넷 플랫폼 산업 전반 광고 수요 회복', '인터넷 플랫폼 업계 전반이 회복했다.'),
            _item('market', '코스피 상승', '시장 전체에 외국인 매수가 유입됐다.'),
            _item('other', '카카오 멤버십 출시', '카카오는 멤버십을 출시했다.'),
        ], '035420', '네이버', as_of=datetime(2026, 10, 13, 15, tzinfo=ZoneInfo('Asia/Seoul')))
    records = [json.loads(r.message) for r in caplog.records if r.message.startswith('{')]
    audit = next(r for r in records if r.get('event') == 'live_news_sentiment_breakdown')
    assert audit['groups']['direct'] == {'article_count': 1, 'sentiment_mean': -0.9}
    assert audit['groups']['industry'] == {'article_count': 1, 'sentiment_mean': 0.3}
    assert audit['groups']['market'] == {'article_count': 1, 'sentiment_mean': 0.5}
    assert audit['decision_counts']['irrelevant'] == 1
    assert track['window']['sentiment_mean'] == pytest.approx(-0.0333)
    assert len(track['articles']) == 3
    assert 'groups' not in track and 'relevance_category' not in track['articles'][0]
