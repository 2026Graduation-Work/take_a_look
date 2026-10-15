"""실시간 뉴스의 종목 관련성: 명시 규칙, 학습·LLM 호출 없음.

과거 BigKinds 필터는 변경하지 않는다. 기사 전체의 감성이 특정 기업의
감성과 같다는 보장은 없으며, 결정 근거는 별도 검토 표에 기록할 수 있다.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Any

POLICY_VERSION = "live-context-v3-subject-industry-market"
# Supported company names match the six-stock collection targets.
_ALIASES = {
    "삼성전자": ("삼성전자", "Samsung Electronics"),
    "현대차": ("현대차", "현대자동차"),
    "카카오": ("카카오", "KAKAO"),
    "네이버": ("네이버", "NAVER"),
    "셀트리온": ("셀트리온", "CELLTRION"),
    "에코프로비엠": ("에코프로비엠", "ECOPRO BM", "ECOPROBM"),
}
CONTEXTUAL_LIVE_COMPANIES = frozenset(_ALIASES)
_COLLISIONS = {
    "삼성전자": ("삼성전자서비스", "삼성전자판매", "Samsung Electronics Service"),
    "현대차": ("현대차증권", "현대자동차증권"),
    "카카오": ("카카오뱅크", "카카오페이", "카카오게임즈", "카카오엔터테인먼트", "카카오모빌리티", "카카오엔터프라이즈", "카카오헬스케어"),
    "네이버": ("네이버웹툰", "네이버클라우드", "네이버파이낸셜", "네이버제트", "NAVER WEBTOON", "NAVER CLOUD"),
    "셀트리온": ("셀트리온제약", "셀트리온헬스케어", "CELLTRION PHARM", "CELLTRION HEALTHCARE"),
    "에코프로비엠": ("에코프로머티리얼즈", "에코프로에이치엔"),
}
_EXECUTIVES = {"현대차": ("정의선",)}
_COMPANY_BUSINESS = {
    "삼성전자": r"반도체|메모리|hbm|파운드리|양산|갤럭시|스마트폰|가전|칩|공정",
    "현대차": r"전기차|하이브리드|자동차|모터쇼|수소|로봇",
    "카카오": r"카카오톡|플랫폼|광고|콘텐츠|인공지능|ai|데이터센터|서비스|개편",
    "네이버": r"검색|광고|커머스|플랫폼|인공지능|ai|데이터센터|서비스|개편",
    "셀트리온": r"임상|허가|승인|바이오시밀러|의약품|신약|치료제|fda|ema",
    "에코프로비엠": r"양극재|전구체|배터리|이차전지|2차전지|증설|가동률|리튬|니켈",
}
_MARKET = re.compile(r"코스피|코스닥|(?:일본|미국|뉴욕|국내|아시아)?증시|시황|사이드카|인기검색종목|신문톱뉴스|주요신문|시장분석|증시키워드|특징주와테마주|신문.{0,8}1면|오늘의.{0,15}1면")
_BUSINESS = re.compile(r"매출|영업이익|실적|공장|생산|판매|출시|출고|신차|투자|수주|공급|수익|주가|목표가|목표주가|배당|할인|사업|파업|전시|미술관|마케팅|모터쇼|수소|로봇|가격|공동기획|공동개발|공동투자")
_CAUSAL = re.compile(r"파업|생산중단|공급중단|납품|공급.{0,8}계약|수주계약|공동기획|공동개발|공동투자")
_INCIDENTAL = re.compile(r"정몽구재단|치맥|치킨|튀김|회동")
_OTHER_COMPANIES = ("LG전자", "엔씨소프트", "크래프톤", "삼성바이오로직스", "SK바이오팜", "포스코퓨처엠", "엘앤에프", "삼성전기", "삼성SDI", "LG에너지솔루션", "현대로템", "현대모비스", "에이아이웍스", "이노션", "삼성전자", "SK하이닉스", "셀트리온", "카카오", "네이버", "기아", "에코프로비엠", "에코프로머티리얼즈", "카카오뱅크", "카카오페이", "네이버웹툰", "셀트리온제약")
_WIDGET = re.compile(r"관련기사|함께보면좋은|추천기사|랭킹뉴스")


def _compact(value: object) -> str:
    return re.sub(r"\s+", "", unicodedata.normalize("NFC", str(value or ""))).casefold()


def _target_causality(passage: str, aliases: tuple[str, ...]) -> bool:
    # 절을 넘어서 다른 회사의 계약을 대상 기업에 귀속하지 않는다.
    for clause in re.split(r"했고|했으며|하였고|했지만|반면|그러나", passage):
        for alias in aliases:
            for target in re.finditer(re.escape(alias), clause):
                tail = clause[target.end():target.end() + 50]
                action = _CAUSAL.search(tail)
                if action is None:
                    continue
                before_action = tail[:action.start()]
                other_subject = any(
                    re.search(re.escape(_compact(c)) + r"(?:은|는|이|가)", before_action)
                    for c in _OTHER_COMPANIES if _compact(c) not in aliases
                )
                joint_subject = any(
                    re.match(r"(?:와|과|·|및)" + re.escape(_compact(c)) + r"(?:은|는|이|가|와|과|·|및)", tail)
                    for c in _KNOWN_SUBJECTS if _compact(c) not in aliases
                )
                if not other_subject or joint_subject:
                    return True
    return False


@dataclass(frozen=True)
class RelevanceDecision:
    category: str
    reason: str
    matched_alias: str = ""

    @property
    def included(self) -> bool:
        return self.category in {"direct", "indirect", "industry", "market"}


def _classify_company_context(
    item: dict[str, Any], company: str, *, key_override: str | None = None,
) -> RelevanceDecision:
    """기업 활동·인과 근거는 유지하고 시장·부수 언급·불확실 입력은 제외한다.

    title/summary만 읽는다. URL, 페이지 위젯, 모델 감성점수는 판정 근거가 아니다.
    reason은 고정 규칙 코드이며 matched_alias에는 회사명만 남긴다.
    """
    name = _compact(company)
    if not name:
        return RelevanceDecision("review", "company_missing")
    aliases = tuple(_compact(a) for a in (_ALIASES.get(name, (name,))))
    if key_override:
        aliases = tuple(dict.fromkeys((*aliases, _compact(key_override))))
    original_title = _compact(item.get("title"))
    title = original_title
    business_pattern = re.compile(_BUSINESS.pattern + "|" + _COMPANY_BUSINESS.get(name, r"(?!)"))
    summary = unicodedata.normalize("NFC", str(item.get("summary") or ""))
    for collision in _COLLISIONS.get(name, ()):
        title = title.replace(_compact(collision), "")
        summary = re.sub(r"\s*".join(map(re.escape, collision)), "", summary, flags=re.IGNORECASE)
    widget = re.search(r"관련\s*기사|함께\s*보면\s*좋은|추천\s*기사|랭킹\s*뉴스", summary)
    if widget:
        summary = summary[:widget.start()]
    # 공급자 본문에 관련기사 링크가 섞여도 그 문장으로 관련성을 입증하지 않는다.
    passages = [
        _compact(s) for s in re.split(r"[\n!?。]+|(?<!\d)\.|\.(?!\d)", summary)
        if s.strip() and not _WIDGET.search(_compact(s))
    ]
    title_alias = next((a for a in aliases if a in title), "")
    body_alias = next((a for a in aliases if any(a in s for s in passages)), "")
    executive = any(e in title for e in _EXECUTIVES.get(name, ()))
    if not (title_alias or body_alias or executive):
        return RelevanceDecision("irrelevant", "target_not_found")
    market = _MARKET.search(title)
    target_position = min((title.index(a) for a in aliases if a in title), default=len(title))
    title_business_pattern = re.compile(
        r"판매|매출|실적|영업이익|신차|출시|생산|공장|공동투자|"
        + _COMPANY_BUSINESS.get(name, r"(?!)")
    )
    title_business_subject = False
    for alias in aliases:
        for match in re.finditer(re.escape(alias), title):
            tail = re.split(r"[·,;]|했고|했으며|반면|그러나", title[match.end():])[0][:24]
            # A later company's business word cannot justify a market-news exception.
            boundary = min(
                (tail.index(_compact(c)) for c in _OTHER_COMPANIES
                 if _compact(c) not in aliases and _compact(c) in tail),
                default=len(tail),
            )
            if title_business_pattern.search(tail[:boundary]):
                title_business_subject = True
    if market and market.start() < target_position and not title_business_subject:
        return RelevanceDecision("market", "market_roundup", title_alias or body_alias)
    explicit_agreement = re.compile(r"공동투자|공동개발|공동기획|공급계약|수주계약")
    if title_alias and (not _INCIDENTAL.search(title) or explicit_agreement.search(title)):
        return RelevanceDecision("direct", "target_in_title", title_alias)
    if executive and _BUSINESS.search(title) and not _INCIDENTAL.search(title):
        return RelevanceDecision("direct", "executive_business_news", name)
    target_passages = [s for s in passages if any(a in s for a in aliases)]
    business = [
        s for s in target_passages if business_pattern.search(s)
        and (not _INCIDENTAL.search(s) or explicit_agreement.search(s))
    ]
    other_title = any(_compact(c) in original_title for c in _OTHER_COMPANIES if _compact(c) not in aliases)
    other_title = other_title or any(_compact(c) in original_title for c in _COLLISIONS.get(name, ()))
    if other_title:
        if any(_target_causality(s, aliases) for s in business):
            return RelevanceDecision("indirect", "business_causality", body_alias)
        return RelevanceDecision("irrelevant", "other_company_subject", body_alias)
    if business:
        return RelevanceDecision("direct", "target_business_in_body", body_alias)
    if any(_INCIDENTAL.search(s) for s in target_passages):
        return RelevanceDecision("irrelevant", "incidental_mention", body_alias)
    return RelevanceDecision("review", "insufficient_business_context", title_alias or body_alias)


# Topic words and broad-scope evidence must occur in the headline together.
# A competitor's product announcement cannot pass through industry keywords.
_INDUSTRY_TOPICS = {
    "삼성전자": r"반도체|메모리|파운드리|스마트폰|가전",
    "현대차": r"자동차|전기차|하이브리드|완성차",
    "카카오": r"인터넷|플랫폼|메신저|온라인광고|커머스|디지털콘텐츠",
    "네이버": r"검색|온라인광고|커머스|인터넷|플랫폼|인공지능|ai|데이터센터",
    "셀트리온": r"바이오의약품|바이오시밀러|의약품|제약|바이오",
    "에코프로비엠": r"양극재|배터리|이차전지|2차전지|리튬|니켈|전구체",
}
_WIDE_SCOPE = re.compile(r"업계|산업|전반|업황|공급망|정책|규제|지원정책|지원사업|허가제도|시장|수요|경쟁")
_MARKET_TOPIC = re.compile(r"코스피|코스닥|증시|시황|시장분석|칠천피|7천피|7000피|금리|환율|국채|시장전체|외국인매도")
_TARGET_ACTION = re.compile(r"출시|개편|신설|양산|증설|투자|판매|생산|파업|수사.{0,8}의뢰|공급.{0,8}계약|공동개발|공동투자|공동기획|허가.{0,8}신청|연동|보안|정보보호")
_UNRELATED = re.compile(r"체중|생활속건강|해수욕장|실버타운|미술품|레스토랑|팝업|타이어|패션기업|형지엘리트|치킨|치맥")
_PARTICIPATION = re.compile(r"등.{0,8}(개사|기업|참여)|참여사|파트너.{0,8}(참여|참석)")
_KNOWN_SUBJECTS = tuple(dict.fromkeys((*_OTHER_COMPANIES, "에코프로", "토스", "엔비디아", "AMD", "콘티넨탈", "GS건설", "마이크론", "유튜브", "광무", "CJ대한통운", "CJ제일제당", "SK텔레콤", "형지엘리트", *(c for group in _COLLISIONS.values() for c in group))))


def classify_live_relevance(
    item: dict[str, Any], company: str, *, key_override: str | None = None,
) -> RelevanceDecision:
    """Deterministic subject-first Live policy; uncertain input is held for review.

    Market/industry decisions describe article scope, not target-company polarity.
    Historical aggregation uses its existing filter independently.
    """
    name = _compact(company)
    if name not in CONTEXTUAL_LIVE_COMPANIES:
        return RelevanceDecision("review", "unsupported_company")
    aliases = tuple(_compact(a) for a in _ALIASES[name])
    if key_override:
        aliases = tuple(dict.fromkeys((*aliases, _compact(key_override))))
    title = _compact(item.get("title"))
    body = str(item.get("summary") or "")
    widget = re.search(r"관련\s*기사|함께\s*보면\s*좋은|추천\s*기사|랭킹\s*뉴스", body)
    if widget:
        body = body[:widget.start()]
    clean_title = title
    clean_body = _compact(body)
    for collision in _COLLISIONS[name]:
        clean_title = clean_title.replace(_compact(collision), "")
        clean_body = clean_body.replace(_compact(collision), "")
    if re.search(r"신문.{0,8}1면|오프라인헤드라인|주요신문|신문톱뉴스", title):
        return RelevanceDecision("review", "mixed_headline_digest")
    title_target = any(a in clean_title for a in aliases)
    # Long aliases are removed before testing shorter companies, e.g. 에코프로.
    subject_title = title
    for alias in aliases:
        subject_title = subject_title.replace(alias, " " * len(alias))
    subjects = [(subject_title.index(_compact(c)), c) for c in _KNOWN_SUBJECTS
                if _compact(c) not in aliases and _compact(c) in subject_title]
    other_position = min((pos for pos, _ in subjects), default=len(title))
    other_subject = bool(subjects) or any(_compact(c) in title for c in _COLLISIONS[name])
    target_actions = False
    for clause in re.split(r"[.!?\n]|했고|했으며|하였고|했지만|하고|반면|그러나", clean_body):
        for alias in aliases:
            subject = re.search(re.escape(alias) + r"(?:는|은|가|이)", clause)
            if subject is None:
                continue
            tail = clause[subject.end():subject.end() + 60]
            action = _TARGET_ACTION.search(tail)
            if action is None:
                continue
            before = tail[:action.start()]
            competitor_actor = any(re.search(re.escape(_compact(c)) + r"(?:가|이|는|은)", before)
                                   for c in _KNOWN_SUBJECTS if _compact(c) not in aliases)
            if not competitor_actor:
                target_actions = True
    agreement = any(_target_causality(_compact(p), aliases)
                    for p in re.split(r"[.!?\n]", body))
    # Target participation/listing or comparisons are insufficient; a concrete
    # target action in the headline's event (or explicit agreement) is evidence.
    target_event = (title_target and target_actions) or agreement
    if name == "네이버" and re.search(r"네이버스토어|스마트스토어", title):
        if not re.search(r"네이버(?:는|가|,).{0,30}(수수료|정책|개편|변경)", clean_body):
            return RelevanceDecision("irrelevant", "sales_channel_only")
    if other_subject and _PARTICIPATION.search(title) and not target_event:
        return RelevanceDecision("irrelevant", "participation_only")
    market = _MARKET_TOPIC.search(title)
    # Index/macro-led roundups remain eligible; a company's earnings headline
    # mentioning the index later does not become market-wide news.
    target_position = min((clean_title.index(a) for a in aliases if a in clean_title), default=len(title))
    if market and market.start() < target_position and (not other_subject or market.start() < other_position) and not target_event:
        if not clean_body:
            return RelevanceDecision("review", "body_missing")
        return RelevanceDecision("market", "market_wide_topic")
    if not title_target and not other_subject and re.match(r"^[가-힣a-z0-9]{2,20}[,:]", title) and _TARGET_ACTION.search(title):
        return RelevanceDecision("review", "unknown_subject")
    lead_body = re.sub(r"^\[[^\]]*\]", "", clean_body)
    leading_actor = re.match(r"^([가-힣a-z0-9]{2,20}?)(?:는|은|가|이)", lead_body)
    if leading_actor and not title_target and not other_subject:
        actor = leading_actor.group(1)
        if title.startswith(actor) and actor not in aliases and not _WIDE_SCOPE.search(actor):
            return RelevanceDecision("review", "unknown_subject")
    topic_prefix = title[:other_position] if other_subject else title
    sector_pattern = _INDUSTRY_TOPICS[name]
    lead = re.split(r"[.!?\n]", body)[0]
    industry_wide = bool(re.search(sector_pattern, topic_prefix) and (
        _WIDE_SCOPE.search(topic_prefix)
        or (not other_subject and re.search(sector_pattern, _compact(lead)) and _WIDE_SCOPE.search(_compact(lead)))
    ))
    if not other_subject and target_actions:
        return RelevanceDecision("direct", "target_business_in_body", next((a for a in aliases if a in clean_body), ""))
    if industry_wide and not title_target and not _UNRELATED.search(title):
        if not clean_body:
            return RelevanceDecision("review", "body_missing")
        return RelevanceDecision("industry", "industry_wide_topic")
    if other_subject:
        if target_event:
            return RelevanceDecision("indirect" if agreement else "direct", "target_material_event")
        return RelevanceDecision("irrelevant", "other_company_subject")
    if not clean_body:
        return RelevanceDecision("review", "body_missing")
    decision = _classify_company_context(dict(item, summary=body), company, key_override=key_override)
    if decision.category in {"direct", "indirect"}:
        business_title = re.search(_BUSINESS.pattern + "|" + _COMPANY_BUSINESS[name] + "|공개|대표|수사|평점|쇼핑|연동|수요|둔화", clean_title)
        if decision.reason != "target_in_title" or business_title or target_actions:
            return decision
        return RelevanceDecision("review", "insufficient_business_context")
    if not title_target and re.match(r"^[가-힣a-z0-9]{2,20}[,:]", title) and _TARGET_ACTION.search(title):
        return RelevanceDecision("review", "unknown_subject")
    industry = re.search(_INDUSTRY_TOPICS[name], title)
    if industry and _WIDE_SCOPE.search(title) and not title_target and not _UNRELATED.search(title):
        return RelevanceDecision("industry", "industry_wide_topic")
    if decision.included or decision.category == "review":
        return decision
    if _UNRELATED.search(title):
        return RelevanceDecision("irrelevant", "unrelated_topic")
    if decision.reason == "target_not_found":
        return RelevanceDecision("review", "insufficient_topic_evidence")
    return decision
