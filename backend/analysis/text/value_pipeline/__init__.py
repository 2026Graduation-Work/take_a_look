"""점수는 뉴스 관련성 판정까지 100% 결정론으로 산출한다. 어떤 기사를 채점할지 LLM이
정하면 그건 곧 점수를 LLM이 정하는 것이기 때문이다. LLM(Gemini)은 핵심 이벤트 추출·근거
문장 생성만 담당하며, GEMINI_API_KEY 유무로 숫자가 바뀌면 버그다.
"""

from .schema import PeriodValueSignal, ValueSignal

__all__ = ["PeriodValueSignal", "ValueSignal"]
