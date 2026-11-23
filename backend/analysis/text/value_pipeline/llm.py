"""Gemini LLM 래퍼(선택적) + 결정론 보장 캐시.

GEMINI_API_KEY가 없으면 None을 반환해 각 에이전트가 규칙 기반 폴백으로 동작하게 한다.

LLM은 temperature=0으로도 결정론이 아니다 — 서버가 함께 배치하는 요청 수에 따라
커널 결과가 달라지기 때문(batch invariance)이며, 이는 우리 통제 밖이다.
그래서 LLM은 한 번만 돌고 출력은 content-hash 키로 동결되며, 재실행은 파일을 읽는다.

캐시 키에 프롬프트·모델·스키마·파라미터를 전부 넣어야 한다. 프롬프트가 빠지면
프롬프트를 고쳐도 옛 답이 나오는 조용한 staleness가 생긴다.
캐시가 완전하면 모델이 은퇴해도 결과를 재현할 수 있다.
"""
from __future__ import annotations

import hashlib
import json
import warnings
from functools import lru_cache
from pathlib import Path
from typing import TypeVar

from pydantic import BaseModel

from .config import SETTINGS

T = TypeVar("T", bound=BaseModel)

CACHE_DIR = Path(__file__).parent / "llm_cache"

# 프롬프트 템플릿을 바꾸면 이 값을 올린다 → 캐시 키가 바뀌어 옛 답이 재사용되지 않는다.
PROMPT_VERSION = "2"

# 런타임 강제 차단 스위치 (CLI --no-llm). 키 유무와 별개로 API 호출을 막는다.
# .env에 키를 등록해 둔 채 대량 생성을 돌리다 무료 한도를 태우는 실수를 막는 용도.
_FORCE_DISABLED = False


def set_llm_enabled(enabled: bool) -> None:
    """끄면 새 API 호출은 안 하지만 이미 있는 캐시는 읽는다(캐시 재생은 결정론적이고 비용이 없다)."""
    global _FORCE_DISABLED
    _FORCE_DISABLED = not enabled
    get_llm.cache_clear()


class LLMCacheMissError(RuntimeError):
    """재생(replay) 모드인데 캐시에 없음 → LLM 호출 대신 실패."""


@lru_cache(maxsize=1)
def get_llm():
    if _FORCE_DISABLED or not SETTINGS.has_gemini:
        return None
    try:
        from langchain_google_genai import ChatGoogleGenerativeAI

        return ChatGoogleGenerativeAI(
            model=SETTINGS.gemini_model,
            google_api_key=SETTINGS.gemini_api_key,
            temperature=0.0,
        )
    except Exception:
        return None


def _cache_key(prompt: str, schema: type[BaseModel]) -> str:
    payload = "\x1f".join(
        [
            prompt,
            schema.__name__,
            json.dumps(schema.model_json_schema(), sort_keys=True, ensure_ascii=False),
            SETTINGS.gemini_model,
            "temp=0.0",
            f"promptver={PROMPT_VERSION}",
        ]
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _cache_path(key: str) -> Path:
    return CACHE_DIR / f"{key}.json"


def structured(prompt: str, schema: type[T]) -> T | None:
    """LLM 미사용/실패 시 None. LLM_REPLAY_ONLY=1이면 캐시 미스가 LLMCacheMissError."""
    key = _cache_key(prompt, schema)
    path = _cache_path(key)

    if path.exists():
        try:
            return schema.model_validate_json(path.read_text(encoding="utf-8"))
        except Exception as e:
            warnings.warn(f"LLM 캐시 파손({key[:12]}), 재생성합니다: {e}", stacklevel=2)

    if SETTINGS.llm_replay_only:
        raise LLMCacheMissError(
            f"재생 모드인데 LLM 캐시에 없습니다 (key={key[:12]}). "
            f"LLM_REPLAY_ONLY=0으로 캐시를 먼저 생성하세요. "
            f"재생 중 LLM을 호출하면 결정론이 깨집니다."
        )

    llm = get_llm()
    if llm is None:
        return None
    try:
        result = llm.with_structured_output(schema).invoke(prompt)
    except Exception:
        return None
    if result is None:
        return None

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    path.write_text(result.model_dump_json(indent=2), encoding="utf-8")
    return result
